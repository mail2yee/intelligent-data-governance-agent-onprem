"""
On-prem Camunda 7 (self-managed) integration via its REST API.

**Corrected 2026-07-29:** originally built against Camunda 8
(self-managed Zeebe, gRPC, `pyzeebe`) per an earlier, incorrect
assumption - the user confirmed the company's actual instance is
**Camunda 7.22**, an entirely different product (REST API, no gRPC, no
job-worker model). Rewritten from scratch and verified against a real
local `camunda/camunda-bpm-platform:7.22.0` container (not just docs),
confirming:

- REST API root: `{CAMUNDA_BASE_URL}` (default
  `http://localhost:8080/engine-rest`), unauthenticated by default.
- Deploy: `POST {base}/deployment/create`, multipart form
  (`deploy-changed-only=true` makes re-deploying the same BPMN a no-op,
  so calling this on every backend startup, as `entrypoint.sh` does, is
  safe).
- Start: `POST {base}/process-definition/key/{key}/start` with
  `{"variables": {...}}`. A *collection* variable (needed here for the
  multi-instance user task, one per owner) must be encoded as
  `{"value": "<json array as a string>", "type": "Object",
  "valueInfo": {"objectTypeName": "java.util.ArrayList",
  "serializationDataFormat": "application/json"}}` - a plain
  `{"type": "Json", ...}` does **not** work for this (confirmed: raises
  `InvalidRequestException`).
- Query tasks: `GET {base}/task?processInstanceId=X&assignee=Y`.
- Complete: `POST {base}/task/{id}/complete` with `{"variables": {...}}`
  -> `204 No Content`.
- The BPMN process (`camunda/data-gov-approval.bpmn`, deployed by this
  app itself) uses a multi-instance user task
  (`camunda:collection="owners" camunda:elementVariable="owner"`) -
  confirmed this creates one independent task per owner (each with
  `assignee` set to that owner's email); completing one doesn't affect
  the others, and the process instance itself ends (404s on a
  follow-up `GET`) once every owner's task is complete. This app's own
  ticket/approval state machine (`main.py`) remains the actual source
  of truth for ticket status - Camunda's role here is to mirror
  progress, not decide it.

No background worker/job-polling needed (unlike Camunda 8's Zeebe) -
completing a task is a single synchronous REST call, so
`submit_approval()` in `main.py` calls `complete_approval_task()`
directly in its own request/response cycle.

If the base URL is unreachable, the process/task doesn't exist, or
anything else goes wrong, both functions fail gracefully (caught
exception -> a "Skipped" status, never raised) rather than breaking
ticket creation or approval submission - mirrors the LLM fallback
pattern in `chat.py`.
"""

import json
import logging
from dataclasses import dataclass

import httpx

from ..config import settings

logger = logging.getLogger("dgo")


@dataclass
class ProcessStartResult:
    status: str
    process_instance_id: str | None


def _auth() -> httpx.BasicAuth | None:
    if settings.camunda_basic_auth_username and settings.camunda_basic_auth_password:
        return httpx.BasicAuth(settings.camunda_basic_auth_username, settings.camunda_basic_auth_password)
    return None


def _collection_variable(values: list[str]) -> dict:
    """Encodes a list as the Object/ArrayList-typed variable Camunda 7's
    REST API needs for a multi-instance collection - confirmed the more
    obvious `{"type": "Json", ...}` form raises instead of working."""
    return {
        "value": json.dumps(values),
        "type": "Object",
        "valueInfo": {"objectTypeName": "java.util.ArrayList", "serializationDataFormat": "application/json"},
    }


async def start_approval_process(
    ticket_id: str, products: list[str], owners: list[str], purpose: str
) -> ProcessStartResult:
    """Starts a new process instance for this ticket. The returned
    `process_instance_id` must be persisted by the caller (see
    `main.py`'s `create_ticket`) - it's the only way to later find and
    complete the right owner's task in `complete_approval_task()`."""
    variables = {
        "ticket_id": {"value": ticket_id, "type": "String"},
        "purpose": {"value": purpose, "type": "String"},
        "products": _collection_variable(products),
        "owners": _collection_variable(owners),
    }
    url = (
        f"{settings.camunda_base_url}/process-definition/key/{settings.camunda_process_definition_key}/start"
    )
    try:
        async with httpx.AsyncClient(timeout=10, auth=_auth()) as client:
            resp = await client.post(url, json={"variables": variables})
            resp.raise_for_status()
            process_instance_id = resp.json()["id"]
        logger.info(
            "Camunda process '%s' started for ticket %s (instance %s)",
            settings.camunda_process_definition_key,
            ticket_id,
            process_instance_id,
        )
        return ProcessStartResult("Successfully triggered in Camunda", process_instance_id)
    except Exception as e:
        logger.warning("Camunda process start failed for ticket %s: %s", ticket_id, e)
        return ProcessStartResult(f"Skipped (Camunda unavailable: {e})", None)


async def complete_approval_task(
    process_instance_id: str | None, owner_email: str, decision: str, reason: str
) -> str:
    """Completes `owner_email`'s task in `process_instance_id` (if any) -
    best-effort, same fallback shape as `start_approval_process()` above.
    The returned string is for logging only; approval submission
    succeeds in this app's own database regardless of Camunda's state."""
    if not process_instance_id:
        return "Skipped (no Camunda process instance for this ticket)"

    try:
        async with httpx.AsyncClient(timeout=10, auth=_auth()) as client:
            tasks_resp = await client.get(
                f"{settings.camunda_base_url}/task",
                params={"processInstanceId": process_instance_id, "assignee": owner_email},
            )
            tasks_resp.raise_for_status()
            tasks = tasks_resp.json()
            if not tasks:
                return (
                    f"Skipped (no pending Camunda task for {owner_email} on instance {process_instance_id})"
                )
            task_id = tasks[0]["id"]

            complete_resp = await client.post(
                f"{settings.camunda_base_url}/task/{task_id}/complete",
                json={
                    "variables": {
                        "decision": {"value": decision, "type": "String"},
                        "reason": {"value": reason, "type": "String"},
                    }
                },
            )
            complete_resp.raise_for_status()
        logger.info(
            "Camunda task %s completed for ticket instance %s (%s, %s)",
            task_id,
            process_instance_id,
            owner_email,
            decision,
        )
        return "Completed in Camunda"
    except Exception as e:
        logger.warning(
            "Camunda task completion failed for instance %s owner %s: %s", process_instance_id, owner_email, e
        )
        return f"Skipped (Camunda unavailable: {e})"

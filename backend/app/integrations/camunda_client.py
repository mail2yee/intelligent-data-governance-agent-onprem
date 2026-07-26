"""
On-prem Camunda 8 (self-managed) integration.

Uses pyzeebe (https://pypi.org/project/pyzeebe/, confirmed against its
PyPI page) to start a process instance on a self-managed Zeebe gateway:

    from pyzeebe import ZeebeClient, create_insecure_channel
    channel = create_insecure_channel(grpc_address="host:port")
    await ZeebeClient(channel).run_process(bpmn_process_id="...", variables={...})

Auth: defaults to `create_insecure_channel` (no auth) - confirmed with
the user this is likely fine for their trusted internal network. If
CAMUNDA_OAUTH_* env vars are all set, an OAuth2 client-credentials-
authenticated secure channel is built instead, directly on core `grpc`
primitives (`grpc.access_token_call_credentials`) rather than a pyzeebe
convenience function - pyzeebe's public docs didn't confirm one for
self-managed + Identity/Keycloak (only `create_insecure_channel` was
documented). **This OAuth path is unverified against a live Camunda
Identity/Keycloak instance - test it once real credentials exist, and
adjust if pyzeebe turns out to expose a purpose-built helper for this.**

Process ID: no BPMN process is deployed yet (confirmed with the user) -
CAMUNDA_PROCESS_ID in .env is a placeholder. Deploy a real process and
update it there; no code change needed here.

If the gateway is unreachable, unauthenticated, or no process with this
ID has been deployed, this fails gracefully (caught exception ->
"Skipped" status) rather than breaking ticket creation - mirrors the
LLM fallback pattern in chat.py.
"""
import logging

import grpc
import httpx
from pyzeebe import ZeebeClient, create_insecure_channel

from ..config import settings

logger = logging.getLogger("dgo")


def _oauth_configured() -> bool:
    return bool(
        settings.camunda_oauth_client_id
        and settings.camunda_oauth_client_secret
        and settings.camunda_oauth_token_url
    )


def _build_channel():
    if not _oauth_configured():
        return create_insecure_channel(grpc_address=settings.camunda_gateway_address)

    def _get_token(_context, callback):
        try:
            resp = httpx.post(
                settings.camunda_oauth_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.camunda_oauth_client_id,
                    "client_secret": settings.camunda_oauth_client_secret,
                    "audience": settings.camunda_oauth_audience,
                },
                timeout=5,
            )
            resp.raise_for_status()
            token = resp.json()["access_token"]
            callback((("authorization", f"Bearer {token}"),), None)
        except Exception as e:  # noqa: BLE001 - must report failure via callback, not raise
            callback(None, e)

    call_credentials = grpc.metadata_call_credentials(_get_token)
    channel_credentials = grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(), call_credentials
    )
    return grpc.aio.secure_channel(settings.camunda_gateway_address, channel_credentials)


async def start_approval_process(
    ticket_id: str, products: list[str], owners: list[str], purpose: str
) -> str:
    try:
        channel = _build_channel()
        client = ZeebeClient(channel)
        await client.run_process(
            bpmn_process_id=settings.camunda_process_id,
            variables={
                "ticket_id": ticket_id,
                "products": products,
                "owners": owners,
                "purpose": purpose,
            },
        )
        logger.info("Camunda process '%s' started for ticket %s", settings.camunda_process_id, ticket_id)
        return "Successfully triggered in Camunda"
    except Exception as e:
        logger.warning("Camunda process start failed for ticket %s: %s", ticket_id, e)
        return f"Skipped (Camunda unavailable: {e})"

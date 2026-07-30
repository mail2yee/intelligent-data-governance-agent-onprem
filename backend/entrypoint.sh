#!/bin/sh
set -e

# POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB in wren_project/connection_profile.json
# are literal ${VAR} strings - wren resolves them from the environment at
# connection time, not when this profile is registered, so no manual
# substitution is needed here (confirmed against the sibling
# agent_mem0_poc repo's identical setup).
wren profile add dgo-catalog \
  --from-file /app/wren_project/connection_profile.json \
  --activate \
  --no-validate

wren context build --path /app/wren_project

# Best-effort: deploy the BPMN process to Camunda if it's reachable.
# `deploy-changed-only=true` makes re-running this on every startup a
# no-op once the BPMN is already deployed (confirmed against a real
# local Camunda 7.22 instance). Uses `|| echo ...` rather than dropping
# `set -e` for just this step, since Camunda being unreachable must not
# block backend startup - same fallback philosophy as
# app/integrations/camunda_client.py itself. Done via a small inline
# Python/httpx script (httpx is already a dependency) instead of curl,
# since this image (python:3.11-slim) doesn't have curl installed.
python3 - <<'PY' || echo "Camunda deploy skipped (unreachable or failed) - continuing"
import os
import sys

import httpx

base = os.environ.get("CAMUNDA_BASE_URL", "http://localhost:8080/engine-rest")
try:
    with open("/app/camunda/data-gov-approval.bpmn", "rb") as f:
        resp = httpx.post(
            f"{base}/deployment/create",
            data={"deployment-name": "data-gov-approval", "deploy-changed-only": "true"},
            files={"data-gov-approval.bpmn": f},
            timeout=10,
        )
    resp.raise_for_status()
    print(f"Camunda: deployed data-gov-approval.bpmn (deployment {resp.json().get('id')})")
except Exception as e:
    print(f"Camunda deploy skipped: {e}")
    sys.exit(1)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

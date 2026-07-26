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

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

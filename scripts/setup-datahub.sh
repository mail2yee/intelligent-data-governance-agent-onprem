#!/usr/bin/env bash
set -euo pipefail

# Brings up a local DataHub instance and seeds it with sample dataset
# entities matching backend/app/integrations/datahub_client.py's expected
# shape (see datahub/seed_catalog.py). Run once before `docker compose up`
# if you want the app talking to a real DataHub instead of its built-in
# mock catalog fallback.
#
# DataHub runs as its own independent `datahub docker quickstart` stack
# (not a service in this repo's docker-compose.yml) - confirmed 2026-07-30
# this mirrors the sibling agent_mem0_poc repo's approach, and matters in
# practice: this dev machine already had a DataHub instance from that other
# project, and reusing it here (rather than each repo running its own)
# avoids two DataHub stacks fighting over the same GMS port.
#
# GMS listens on host port 8080 by default (the `datahub` CLI's own
# default, unconfigurable without a custom compose file override) - this
# repo's frontend deliberately uses 8090 instead, to leave 8080 free (see
# docker-compose.yml's comments).

if ! command -v datahub >/dev/null 2>&1; then
  echo "找不到 datahub CLI，安裝中: pip install 'acryl-datahub[datahub-rest]'"
  pip install --quiet 'acryl-datahub[datahub-rest]'
fi

if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
  echo "DataHub GMS already running on :8080, skipping docker quickstart."
else
  datahub docker quickstart
  echo "Waiting for DataHub GMS..."
  until curl -sf http://localhost:8080/health >/dev/null 2>&1; do sleep 3; done
fi

echo "Seeding sample dataset catalog..."
python3 "$(dirname "${BASH_SOURCE[0]}")/../datahub/seed_catalog.py"

cat <<'EOF'

Done. DataHub GMS: http://localhost:8080 (GraphQL: /api/graphql)
DataHub UI:        http://localhost:9002 (username/password: datahub/datahub)

The backend picks this up automatically:
  - via docker-compose.yml (DATAHUB_API_URL=http://host.docker.internal:8080)
  - or locally, set DATAHUB_API_URL=http://localhost:8080 in backend/.env

Re-run this script any time to re-seed (safe - DataHub upserts by URN).
EOF

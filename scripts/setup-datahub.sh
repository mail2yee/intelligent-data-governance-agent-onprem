#!/usr/bin/env bash
set -euo pipefail

# Seeds sample dataset entities matching
# backend/app/integrations/datahub_client.py's expected shape (see
# datahub/seed_catalog.py) into this repo's own self-hosted DataHub
# instance (datahub/docker-compose.datahub.yml, brought up via
# ./deploy.sh or `docker compose -f docker-compose.yml -f
# datahub/docker-compose.datahub.yml up -d`).
#
# Run this AFTER that instance is up and healthy - it does not start
# anything itself. Re-run any time to re-seed (safe - DataHub upserts by
# URN).
#
# Historical note: this used to launch its own separate `datahub docker
# quickstart` stack, shared with the sibling agent_mem0_poc repo (see
# git history / HANDOFF.md) - reversed 2026-08-05 when DataHub moved
# into this repo's own docker-compose stack instead. GMS is now at
# :18080, not the old shared instance's :8080.

if ! curl -sf http://localhost:18080/health >/dev/null 2>&1; then
  echo "DataHub GMS not reachable at http://localhost:18080 - bring it up first:" >&2
  echo "  ./deploy.sh" >&2
  echo "  (or: docker compose -f docker-compose.yml -f datahub/docker-compose.datahub.yml up -d)" >&2
  exit 1
fi

echo "Seeding sample dataset catalog..."
python3 "$(dirname "${BASH_SOURCE[0]}")/../datahub/seed_catalog.py"

cat <<'EOF'

Done. DataHub GMS: http://localhost:18080 (GraphQL: /api/graphql)
DataHub UI:        http://localhost:19002 (username/password: datahub/datahub)

The backend picks this up automatically once the datahub overlay is
included (see docker-compose.yml/deploy.sh) - no manual DATAHUB_API_URL
change needed for the containerized backend.
EOF

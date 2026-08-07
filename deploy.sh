#!/usr/bin/env bash
set -uo pipefail

# One-command deploy: self-hosted images by default for Camunda and
# DataHub, falling back to whatever CAMUNDA_BASE_URL/DATAHUB_API_URL are
# already set to in backend/.env (presumably the company's real
# instances) if the self-hosted image can't be pulled - e.g. the office
# network can reach ghcr.io but the exact image tag got removed, or this
# is a machine without ghcr.io access at all. Postgres has no such
# fallback on purpose (self-hosting it is the actual plan, not a
# convenience - see docker-compose.yml's comment) - a failed postgres
# pull is a hard error, not a silent skip.
#
# See HANDOFF.md's "Self-hosted images with a config fallback" section
# for the full reasoning. This script only decides *which docker-compose
# files to combine*; the actual fallback behavior at runtime (Camunda
# "Skipped" status, DataHub mock catalog) already existed before this
# script did - this just decides whether to even attempt running the
# local container in the first place.
#
# Usage: ./deploy.sh

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== Config files =="
if [ ! -f backend/.env ]; then
  echo "backend/.env not found - copying from backend/.env.example."
  echo "Edit it before continuing if you have real company endpoints to fill in."
  cp backend/.env.example backend/.env
fi
if [ ! -f .env ]; then
  cp .env.example .env
fi

COMPOSE_FILES=(-f docker-compose.yml)

echo
echo "== Postgres (mandatory - no fallback) =="
if docker compose pull postgres; then
  echo "postgres: OK"
else
  echo "ERROR: could not pull the postgres image (ghcr.io/mail2yee/postgres:16-alpine)." >&2
  echo "Unlike Camunda/DataHub, this app doesn't fall back to a company Postgres" >&2
  echo "automatically - self-hosting Postgres is the actual plan here. Fix" >&2
  echo "connectivity to ghcr.io and retry." >&2
  exit 1
fi

echo
echo "== Camunda (self-hosted image, falls back to backend/.env's CAMUNDA_BASE_URL) =="
if docker compose -f docker-compose.yml -f docker-compose.camunda.yml pull camunda; then
  echo "camunda: image pulled OK - will self-host locally."
  COMPOSE_FILES+=(-f docker-compose.camunda.yml)
else
  echo "camunda: image NOT pullable - skipping the local container."
  echo "  The app will use whatever CAMUNDA_BASE_URL is set to in backend/.env"
  echo "  instead (make sure that's the company's real Camunda 7 instance, not"
  echo "  the http://localhost:8082/... local-dev default, or ticket creation"
  echo "  will just report a graceful 'Skipped' Camunda status instead of"
  echo "  actually connecting anywhere)."
fi

echo
echo "== DataHub (7 self-hosted images, falls back to backend/.env's DATAHUB_API_URL) =="
if docker compose -f docker-compose.yml -f datahub/docker-compose.datahub.yml pull \
  datahub-gms-quickstart frontend-quickstart kafka-broker mysql opensearch \
  system-update-quickstart datahub-actions-quickstart; then
  echo "datahub: all images pulled OK - will self-host locally."
  COMPOSE_FILES+=(-f datahub/docker-compose.datahub.yml)
else
  echo "datahub: one or more images NOT pullable - skipping the local stack."
  echo "  The app will use whatever DATAHUB_API_URL is set to in backend/.env"
  echo "  instead (make sure that's the company's real DataHub instance, or"
  echo "  it'll fall back further to the app's own built-in mock catalog)."
fi

echo
echo "== Backend / frontend =="
# Build FIRST, pull only as a fallback - not the other way around. This
# repo's own source is what's actually being worked on here; a bare
# `docker compose pull` would happily succeed against whatever was last
# published to ghcr.io and silently overwrite today's local changes with
# a stale image (confirmed this the hard way: an old Camunda-8/Zeebe
# error showed up in a pull-first test run, from code already rewritten
# for Camunda 7 weeks ago - the pull had clobbered the fresh local build
# without any error). Building requires PyPI/npm access, which is
# exactly what fails cleanly at the office - that's when this falls back
# to pulling the pre-published image instead.
if docker compose "${COMPOSE_FILES[@]}" build backend frontend; then
  echo "backend/frontend: built from local source."
else
  echo "backend/frontend: local build failed (no PyPI/npm access?) - falling back to a pull."
  docker compose pull backend frontend
fi

echo
echo "== Bringing the stack up: docker compose ${COMPOSE_FILES[*]} up -d =="
docker compose "${COMPOSE_FILES[@]}" up -d

cat <<EOF

Done.
  Frontend: http://localhost:8090
  Backend:  http://localhost:8000/health
EOF
if [[ " ${COMPOSE_FILES[*]} " == *" docker-compose.camunda.yml "* ]]; then
  echo "  Camunda:  http://localhost:8082/engine-rest (self-hosted)"
else
  echo "  Camunda:  using backend/.env's CAMUNDA_BASE_URL (not self-hosted this run)"
fi
if [[ " ${COMPOSE_FILES[*]} " == *" datahub/docker-compose.datahub.yml "* ]]; then
  echo "  DataHub:  http://localhost:19002 (self-hosted UI), GMS on :18080"
else
  echo "  DataHub:  using backend/.env's DATAHUB_API_URL (not self-hosted this run)"
fi

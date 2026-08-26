#!/usr/bin/env bash
set -uo pipefail

# One-command deploy, in one of two modes:
#
#   ./deploy.sh            local dev mode (default) - self-host Camunda
#                          and DataHub via image if pullable, falling
#                          back to backend/.env's CAMUNDA_BASE_URL /
#                          DATAHUB_API_URL otherwise. Convenient for
#                          testing the agent without any company infra.
#
#   ./deploy.sh --office   office mode - Camunda and DataHub are NEVER
#                          self-hosted here, full stop. No image pull is
#                          even attempted for them; the app always talks
#                          to whatever CAMUNDA_BASE_URL/DATAHUB_API_URL
#                          are set to in backend/.env (point those at
#                          the company's real instances first). Adopted
#                          2026-08-26 after the company's vulnerability
#                          scanner blocked the mirrored Camunda/DataHub
#                          images outright and further version bumps
#                          couldn't get the count to zero (see
#                          HANDOFF.md's "Vulnerability remediation
#                          round" and "Office mode" sections) - rather
#                          than keep chasing CVE counts on third-party
#                          images, the office just uses the company's
#                          own already-approved services via config.
#                          Backend/frontend also skip the GHCR pull
#                          fallback in this mode (git-pulled source +
#                          local build is the only path) - the whole
#                          point is not depending on any GHCR-hosted
#                          image at the office anymore.
#
# Postgres is unchanged in both modes: always self-hosted via image, no
# fallback - see docker-compose.yml's comment for why (the company's
# own Postgres is an unwieldy HA setup, self-hosting a plain instance is
# the actual plan, not a convenience).
#
# See HANDOFF.md's "Self-hosted images with a config fallback" and
# "Office mode" sections for the full reasoning.
#
# Usage: ./deploy.sh [--office]

MODE="local"
if [ "${1:-}" = "--office" ]; then
  MODE="office"
fi

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
echo "== Postgres (mandatory - no fallback, same in every mode) =="
if docker compose pull postgres; then
  echo "postgres: OK"
else
  echo "ERROR: could not pull the postgres image (ghcr.io/mail2yee/postgres:16-alpine)." >&2
  echo "Unlike Camunda/DataHub, this app doesn't fall back to a company Postgres" >&2
  echo "automatically - self-hosting Postgres is the actual plan here. Fix" >&2
  echo "connectivity to ghcr.io and retry." >&2
  exit 1
fi

if [ "$MODE" = "office" ]; then
  echo
  echo "== Camunda (office mode: backend/.env's CAMUNDA_BASE_URL only, never self-hosted) =="
  echo "  Make sure CAMUNDA_BASE_URL points at the company's real Camunda 7 instance."

  echo
  echo "== DataHub (office mode: backend/.env's DATAHUB_API_URL only, never self-hosted) =="
  echo "  Make sure DATAHUB_API_URL points at the company's real DataHub instance."
else
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
fi

echo
echo "== Backend / frontend =="
# Build FIRST, pull only as a fallback (local mode) - not the other way
# around. This repo's own source is what's actually being worked on
# here; a bare `docker compose pull` would happily succeed against
# whatever was last published to ghcr.io and silently overwrite today's
# local changes with a stale image (confirmed this the hard way: an old
# Camunda-8/Zeebe error showed up in a pull-first test run, from code
# already rewritten for Camunda 7 weeks ago - the pull had clobbered
# the fresh local build without any error).
if [ "$MODE" = "office" ]; then
  echo "office mode: build from source only, no GHCR pull fallback."
  if docker compose "${COMPOSE_FILES[@]}" build backend frontend; then
    echo "backend/frontend: built from local source."
  else
    echo "ERROR: local build failed." >&2
    echo "Office mode doesn't fall back to a GHCR pull for backend/frontend -" >&2
    echo "that's the point (avoid the company scanner blocking our own images" >&2
    echo "too). Fix build access (e.g. an internal PyPI/npm mirror) and retry." >&2
    exit 1
  fi
else
  if docker compose "${COMPOSE_FILES[@]}" build backend frontend; then
    echo "backend/frontend: built from local source."
  else
    echo "backend/frontend: local build failed (no PyPI/npm access?) - falling back to a pull."
    docker compose pull backend frontend
  fi
fi

echo
echo "== Bringing the stack up: docker compose ${COMPOSE_FILES[*]} up -d =="
docker compose "${COMPOSE_FILES[@]}" up -d

cat <<EOF

Done. (mode: $MODE)
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

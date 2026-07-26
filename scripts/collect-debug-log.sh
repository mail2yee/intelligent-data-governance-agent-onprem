#!/usr/bin/env bash
# Run at the office (no Claude Code there) to collect debug info about the
# docker-compose / GHCR pull setup, then push it to git so it can be read
# and reviewed from home. See ../TESTING_LOG.md for the manual version of
# this same workflow.
#
# Usage:
#   ./scripts/collect-debug-log.sh          # collect, show you the log, ask before pushing
#   ./scripts/collect-debug-log.sh --yes     # collect and push without asking (still redacts secrets)
set -euo pipefail
cd "$(dirname "$0")/.."

AUTO_YES=false
if [[ "${1:-}" == "--yes" ]]; then
  AUTO_YES=true
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p debug-logs
OUTFILE="debug-logs/${TIMESTAMP}.log"

{
  echo "=== debug log collected $(date) ==="

  echo; echo "--- git ---"
  git log -1 --oneline 2>&1 || true
  git status --short 2>&1 || true

  echo; echo "--- docker / compose versions ---"
  docker --version 2>&1 || true
  docker compose version 2>&1 || true

  echo; echo "--- network reachability (curl -sS -m 5) ---"
  for host in github.com ghcr.io registry-1.docker.io pypi.org registry.npmjs.org; do
    echo "-- $host --"
    curl -sS -m 5 -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" "https://$host" 2>&1 \
      || echo "FAILED to reach $host"
  done

  echo; echo "--- docker compose config (resolved, before redaction) ---"
  docker compose config 2>&1 || true

  echo; echo "--- docker compose pull ---"
  docker compose pull 2>&1 || true

  echo; echo "--- docker compose ps ---"
  docker compose ps 2>&1 || true

  echo; echo "--- docker compose logs (last 200 lines, if anything is running) ---"
  docker compose logs --no-color --tail=200 2>&1 || true
} > "$OUTFILE" 2>&1

# Best-effort secret redaction - docker compose config in particular prints
# resolved env values, which can include POSTGRES_PASSWORD / API keys / PATs.
# Review the output yourself too; this is a safety net, not a guarantee.
sed -i.bak -E \
  -e 's/(PASSWORD[A-Z_]*=)[^[:space:]]+/\1REDACTED/gi' \
  -e 's/(TOKEN[A-Z_]*=)[^[:space:]]+/\1REDACTED/gi' \
  -e 's/(SECRET[A-Z_]*=)[^[:space:]]+/\1REDACTED/gi' \
  -e 's/(API_KEY[A-Z_]*=)[^[:space:]]+/\1REDACTED/gi' \
  -e 's|(postgresql\+asyncpg://[^:]+:)[^@]+(@)|\1REDACTED\2|gi' \
  "$OUTFILE"
rm -f "${OUTFILE}.bak"

echo "Wrote $OUTFILE"
echo "---"
cat "$OUTFILE"
echo "---"

if [[ "$AUTO_YES" != true ]]; then
  read -r -p "Everything above look safe to push (no leftover secrets)? [y/N] " reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Not pushing. File is still saved at $OUTFILE - edit or delete it, then re-run if needed."
    exit 0
  fi
fi

git add "$OUTFILE"
git commit -m "Add office debug log ${TIMESTAMP}"
git push
echo "Pushed. Pull it at home with: git pull"

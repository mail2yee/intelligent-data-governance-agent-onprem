#!/usr/bin/env bash
set -euo pipefail

# Mirrors a public third-party image (Docker Hub, etc.) to this project's
# GHCR namespace, so it can be pulled from inside the company's
# air-gapped network - confirmed 2026-08-04 that ghcr.io itself IS
# reachable from the office, but the company's own registries (Harbor,
# Nexus) don't mirror everything (e.g. no Camunda image there) - see
# HANDOFF.md's "Getting Camunda + Postgres into the office network"
# section for the full reasoning.
#
# This is a straight retag-and-push - the image bytes are unchanged, not
# rebuilt or customized. All runtime config (env vars, volumes) still
# happens the same way it always does, in docker-compose.yml - mirroring
# an image here never means editing config "inside" it.
#
# Requires `docker login ghcr.io` first (run that yourself with your own
# PAT - this script never touches credentials). After the first push of a
# new package, it defaults to private - flip it to public in GHCR's
# package settings (Settings -> Danger Zone -> Change visibility), same
# as already done for this repo's backend/frontend images, or `docker
# pull` from the office will fail with a 401 instead of working
# anonymously.
#
# Usage:
#   scripts/mirror-image-to-ghcr.sh <source-image> <ghcr-image-name>
#
# Example:
#   scripts/mirror-image-to-ghcr.sh camunda/camunda-bpm-platform:7.22.0 camunda-bpm-platform:7.22.0

if [ $# -ne 2 ]; then
  echo "Usage: $0 <source-image> <ghcr-image-name>" >&2
  echo "Example: $0 camunda/camunda-bpm-platform:7.22.0 camunda-bpm-platform:7.22.0" >&2
  exit 1
fi

SOURCE_IMAGE="$1"
GHCR_IMAGE_NAME="$2"
GHCR_NAMESPACE="ghcr.io/mail2yee"
TARGET="$GHCR_NAMESPACE/$GHCR_IMAGE_NAME"

# Always resolve and pull the amd64 manifest explicitly, by digest -
# confirmed 2026-08-04 the hard way: on an Apple Silicon dev machine,
# neither a bare `docker pull` nor `docker pull --platform linux/amd64`
# reliably avoided pulling arm64 (a Docker Desktop caching quirk, not a
# one-off) - only pulling the exact amd64 digest from the manifest list
# actually worked. The company's servers are x86_64 - this is the same
# platform-mismatch bug that already broke frontend's first GHCR push
# earlier in this project, worth never repeating by hand again.
echo "Resolving amd64 digest for $SOURCE_IMAGE..."
AMD64_DIGEST=$(docker manifest inspect "$SOURCE_IMAGE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for m in d.get('manifests', []):
    p = m.get('platform', {})
    if p.get('architecture') == 'amd64' and p.get('os') == 'linux':
        print(m['digest'])
        break
")

if [ -z "$AMD64_DIGEST" ]; then
  echo "No amd64/linux entry found in $SOURCE_IMAGE's manifest list - falling back to a plain pull (verify the architecture yourself after)." >&2
  docker pull "$SOURCE_IMAGE"
  docker tag "$SOURCE_IMAGE" "$TARGET"
else
  echo "Pulling $SOURCE_IMAGE@$AMD64_DIGEST (amd64)..."
  docker pull "${SOURCE_IMAGE%%:*}@$AMD64_DIGEST"
  docker tag "${SOURCE_IMAGE%%:*}@$AMD64_DIGEST" "$TARGET"
fi

ACTUAL_ARCH=$(docker image inspect "$TARGET" --format '{{.Architecture}}/{{.Os}}')
echo "Resolved local image architecture: $ACTUAL_ARCH"
if [ "$ACTUAL_ARCH" != "amd64/linux" ]; then
  echo "WARNING: expected amd64/linux, got $ACTUAL_ARCH - double-check before pushing." >&2
fi

echo "Pushing $TARGET..."
docker push "$TARGET"

cat <<EOF

Done. Pull it elsewhere with:
  docker pull $TARGET

If this is the first push of this package name, it starts out private -
flip it to public in GHCR's package settings before relying on an
anonymous pull (e.g. from the office) working.
EOF

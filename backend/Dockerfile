# Build context is the repo root (see docker-compose.yml), not backend/,
# so this can also COPY in ../wren/project - the WrenAI semantic model
# (see app/integrations/wrenai_client.py).
#
# TODO: once building inside the company network, point this at the
# internal registry mirror's copy of this image instead of Docker Hub
# directly (e.g. internal-registry.company.internal/python:3.11-slim) -
# exact hostname/path unconfirmed, ask IT.
FROM python:3.11-slim
WORKDIR /app

# wrenai's Rust engine (wren-core-py) ships a prebuilt wheel for
# linux/amd64 (manylinux) and macOS, but NOT linux/aarch64 (confirmed via
# PyPI's file listing for wren-core-py 0.7.2, 2026-07) - build/ship this
# image for linux/amd64 (e.g. `docker buildx build --platform linux/amd64`)
# to get the prebuilt wheel and skip a Rust toolchain entirely. If you
# must build on arm64, add a Rust toolchain before `pip install` (see the
# sibling agent_mem0_poc repo's Dockerfile for a working example) - it'll
# compile wren-core-py from source instead, which needs crates.io
# reachable during the build, not just PyPI.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/entrypoint.sh .
RUN chmod +x entrypoint.sh
COPY wren/project ./wren_project

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]

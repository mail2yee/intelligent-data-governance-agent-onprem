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
# PyPI's file listing for wren-core-py 0.7.5, 2026-08) - the office/GHCR
# image is still built+pushed for linux/amd64 specifically (see
# docker-compose.yml's platform: pin), but a Rust toolchain is installed
# unconditionally below (same pattern as the sibling agent_mem0_poc
# repo's Dockerfile, confirmed working there) so this same Dockerfile
# also builds natively on arm64 - useful for local testing (e.g. a
# local arm64 `kind` cluster, see k8s/README.md) without needing QEMU
# emulation for the build itself. On amd64 this toolchain just sits
# unused (pip still picks the prebuilt wheel) - a bit of extra build
# time/image size, not worth branching the Dockerfile over.
# mysqlclient (pulled in by wrenai[mysql], for WrenAI's own MariaDB
# connector - see wren/project/connection_profile.json) ships no Linux
# wheel on PyPI, only an sdist - needs MariaDB/MySQL client headers and a
# C compiler to build. default-libmysqlclient-dev resolves to
# MariaDB's client library on this Debian base.
# wrenai[postgres] (psycopg[binary]) is also pulled in - a SECOND,
# separate WrenAI datasource for the fake business-data connection (see
# wren/business_capacity_plan/ and
# app/integrations/business_data.py) - ships prebuilt binary wheels, no
# extra apt packages needed for this one.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config default-libmysqlclient-dev curl \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/entrypoint.sh .
RUN chmod +x entrypoint.sh
COPY wren/project ./wren_project
COPY wren/business_capacity_plan ./wren_business_capacity_plan
COPY camunda/data-gov-approval.bpmn ./camunda/data-gov-approval.bpmn

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]

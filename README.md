# Intelligent Data Governance — On-Prem

On-prem build of the data governance agent, for the company's air-gapped
internal network. See **`HANDOFF.md` first** — it explains why this is a
separate repo from the GCP PoC, what's swapped (Gemini → on-prem LLM,
Firestore → PostgreSQL, Dataplex → DataHub, Camunda SaaS → self-managed
Camunda), and what business logic / UI direction to carry over.

## Status: full PoC UI ported, verified end-to-end

- Backend (FastAPI + PostgreSQL) tested end-to-end against a real
  Postgres: catalog fetch, SSE chat streaming (greeting fast-path,
  zero-hallucination guard, local-keyword fallback when the LLM endpoint
  isn't reachable instead of just erroring out), ticket create/list, and
  the full approve/reject state machine (including SLA cycle-time
  tracking).
- Frontend (React + Vite) is a full port of the GCP PoC's UI: Discover
  search with live SSE streaming (reasoning steps + answer text appear
  as they happen, not after one big wait), Approvals list with SLA
  highlighting, cart + submit dialog, connection-code dialog, Copilot
  dock, zh/en toggle, light/dark toggle (light by default regardless of
  OS preference), collapsible nav rail. Verified via a full Playwright
  run through every flow against the real backend — zero console errors.
- Camunda (`pyzeebe`) and DataHub (GraphQL) integrations are **real,
  wired clients** now, not mocks — verified to correctly attempt a
  connection and fail gracefully when nothing's listening yet. Still
  need: a deployed BPMN process (`CAMUNDA_PROCESS_ID` is a placeholder),
  and validation of the DataHub field-mapping assumptions once there's a
  real instance to test against. See HANDOFF.md "What's actually in this
  repo right now" for the full list of what's confirmed vs. assumed.
- LLM integration assumes an OpenAI-compatible endpoint — **unconfirmed**
  against the real on-prem gateway, see `backend/app/integrations/llm_client.py`.

## Run it locally

```bash
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend: http://localhost:8000 (docs at `/docs`)
- Postgres: localhost:5432 (user/pass/db: `dgo`/`dgo`/`dgo`)

Or run backend/frontend separately without Docker — see
`backend/README.md` and `frontend/README.md`.

**Before building inside the company network:** confirm whether there's
an internal PyPI/npm mirror in addition to the Docker image mirror — see
the TODO comments in both Dockerfiles. If there isn't one, build images
somewhere with internet access and get them into the internal registry
some other way, rather than `docker build` on-site.

### Testing the "build at home, run at office" path via GHCR

`docker-compose.yml` sets both `image:` and `build:` on the `backend` and
`frontend` services, pointing at `ghcr.io/mail2yee/intelligent-data-governance-agent-onprem-{backend,frontend}:latest`.
This is a first attempt at a registry the company network might reach
without needing an internal mirror at all, since GitHub itself is
reachable from inside — **unconfirmed whether `ghcr.io` specifically is
allowed through the firewall, that's what this is testing.**

At home (internet access):
```bash
docker compose build
docker login ghcr.io -u mail2yee   # personal access token with write:packages, as the password
docker compose push
```
The pushed packages need to be flipped to **public** once in GitHub's
package settings (GHCR defaults new packages to private even though this
repo is private) — done as a deliberate choice for the testing phase, so
the office side needs no `docker login`/PAT at all. Revisit before any
real rollout: switch back to private once this is confirmed to work, and
handle the PAT at the office properly at that point.

At the office (no internet, testing whether `ghcr.io` is reachable):
```bash
git pull
docker compose pull
docker compose up
```
If `docker compose pull` fails to resolve/connect to `ghcr.io`, that
confirms the internal Docker registry mirror is the only viable path and
this GHCR approach should be dropped.

## Repo layout

```
backend/    FastAPI API (Python) — see backend/README.md
frontend/   React + Vite SPA — see frontend/README.md
k8s/        placeholder for future Kubernetes manifests (not needed yet — Docker is fine for now)
docker-compose.yml   local/on-prem multi-container dev setup
HANDOFF.md  why this repo exists, what to port from the GCP PoC, current constraints
```

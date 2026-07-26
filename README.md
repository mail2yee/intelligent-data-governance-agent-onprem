# Intelligent Data Governance — On-Prem

On-prem build of the data governance agent, for the company's air-gapped
internal network. See **`HANDOFF.md` first** — it explains why this is a
separate repo from the GCP PoC, what's swapped (Gemini → on-prem LLM,
Firestore → PostgreSQL, Dataplex → DataHub, Camunda SaaS → self-managed
Camunda), and what business logic / UI direction to carry over.

## Status: scaffold, verified end-to-end

Not a feature port yet — a skeleton verified to actually run:

- Backend (FastAPI + PostgreSQL) tested end-to-end against a real
  Postgres: catalog fetch, SSE chat streaming (greeting fast-path,
  zero-hallucination guard, graceful failure when the LLM endpoint isn't
  reachable), ticket create/list, and the full approve/reject state
  machine (including SLA cycle-time tracking).
- Frontend (React + Vite) verified to actually fetch from the backend
  through the dev proxy and render live data, using the design tokens
  ported from the PoC.
- Camunda and DataHub integrations are **stubs** — see their docstrings
  in `backend/app/integrations/` for exactly what's needed before they're
  real.
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

## Repo layout

```
backend/    FastAPI API (Python) — see backend/README.md
frontend/   React + Vite SPA — see frontend/README.md
k8s/        placeholder for future Kubernetes manifests (not needed yet — Docker is fine for now)
docker-compose.yml   local/on-prem multi-container dev setup
HANDOFF.md  why this repo exists, what to port from the GCP PoC, current constraints
```

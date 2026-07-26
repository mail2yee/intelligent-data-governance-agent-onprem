# Backend

FastAPI, Python 3.11+. See `../HANDOFF.md` for the behavior this ports
from the GCP PoC and what's still a stub.

## Local dev (without Docker)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit with real values once you have them
uvicorn app.main:app --reload --port 8000
```

Needs a reachable Postgres for `/api/tickets*` to work (see
`../docker-compose.yml` for a local Postgres container, or point
`DATABASE_URL` at any Postgres instance). `/health` and `/api/catalog`
work without one - well, `/api/tickets*` will error without a DB, but the
app itself will still start.

## What's implemented vs. stubbed

- `/health`, `/api/catalog`, `/api/catalog/{id}/connection` (falls back to
  a hardcoded mock catalog), `/api/chat` (SSE streaming, ported
  greeting/zero-hallucination/bilingual logic from the PoC, plus a local
  keyword-match fallback if the LLM call fails), `/api/tickets*` (real
  Postgres persistence, real approval state machine) — **implemented**.
- LLM call (`app/integrations/llm_client.py`) — implemented against an
  **assumed** OpenAI-compatible endpoint shape. Unconfirmed against the
  real on-prem model gateway.
- Camunda (`app/integrations/camunda_client.py`) — **real client**
  (`pyzeebe`), defaults to an unauthenticated channel. Falls back to a
  "Skipped" status if the gateway is unreachable or `CAMUNDA_PROCESS_ID`
  (currently a placeholder — no process deployed yet) doesn't exist.
  Optional OAuth path is implemented but untested against a live
  Identity/Keycloak server.
- DataHub (`app/integrations/datahub_client.py`) — **real client**
  (GraphQL), falls back to a hardcoded mock catalog if unreachable.
  Assumes extra fields (maturity_level, etc.) live as DataHub
  customProperties — see the module docstring for exactly what's
  confirmed vs. assumed about the schema shape.

## Routes

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness check |
| GET | `/api/catalog` | data subjects (DataHub, currently mocked) |
| GET | `/api/catalog/{id}/connection` | db_type/host/port/schema for the "connection code" UI feature |
| POST | `/api/chat` | SSE stream: `step` / `token` / `final` events. Body: `{message, lang}` |
| POST | `/api/tickets` | create a ticket. Body: `{products, objective, purpose}` |
| GET | `/api/tickets` | list tickets, newest first |
| POST | `/api/tickets/{id}/approvals` | Body: `{owner_email, decision, reason}` |

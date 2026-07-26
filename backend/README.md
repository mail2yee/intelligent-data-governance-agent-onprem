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

- `/health`, `/api/catalog` (falls back to a hardcoded mock catalog),
  `/api/chat` (SSE streaming, ported greeting/zero-hallucination/bilingual
  logic from the PoC), `/api/tickets*` (real Postgres persistence, real
  approval state machine) — **implemented**.
- LLM call (`app/integrations/llm_client.py`) — implemented against an
  **assumed** OpenAI-compatible endpoint shape. Unconfirmed against the
  real on-prem model gateway.
- Camunda (`app/integrations/camunda_client.py`) — **stub**, returns a
  "not implemented" status. Needs gateway address + auth + a real
  deployed process before this can do anything.
- DataHub (`app/integrations/datahub_client.py`) — **stub**, returns
  hardcoded mock data. Needs instance URL + token.

## Routes

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness check |
| GET | `/api/catalog` | data subjects (DataHub, currently mocked) |
| POST | `/api/chat` | SSE stream: `step` / `token` / `final` events. Body: `{message, lang}` |
| POST | `/api/tickets` | create a ticket. Body: `{products, objective, purpose}` |
| GET | `/api/tickets` | list tickets, newest first |
| POST | `/api/tickets/{id}/approvals` | Body: `{owner_email, decision, reason}` |

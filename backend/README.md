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

## Linting, type checking, tests

```bash
pip install -r requirements-dev.txt   # adds ruff, mypy, pytest on top of requirements.txt
ruff check app/ tests/                # lint
ruff format app/ tests/               # format
mypy app/                             # type check
pytest -v                             # run the test suite
```

Config for all four lives in `pyproject.toml`. Tests run against a
temp-file SQLite database (not Postgres) for speed/simplicity - see the
docstring at the top of `tests/conftest.py` for why, and the tradeoff
that implies (nothing here relies on Postgres-specific SQL, so this is
fine for testing application logic, not a substitute for testing against
real Postgres if that ever becomes necessary).

## Evals (DeepEval + a configurable LLM judge)

`evals/` is a separate, slower suite from `tests/` - it hits the real,
running `/api/chat` (Docker Compose stack up, real Postgres/WrenAI) and
uses [DeepEval](https://deepeval.com) to score reply faithfulness,
relevancy, and recommendation precision on a small golden-query set (see
`evals/golden_queries.py`). Not part of a bare `pytest` run
(`pyproject.toml`'s `testpaths` excludes it) - run explicitly.

The judge model is DeepEval's `LocalModel` - a generic OpenAI-compatible
client, the same assumption `app/integrations/llm_client.py` already
makes. That means **the exact same three env vars point it at either a
local Ollama (to try the suite itself) or the company's real on-prem LLM
gateway (to actually evaluate that gateway, which is the real point of
this suite)** - only the values change:

```bash
pip install -r requirements-eval.txt
docker compose up -d --build            # from the repo root, real stack must be running

# Trying the suite out against a local Ollama:
DGO_EVAL_JUDGE_MODEL=qwen2.5:latest \
DGO_EVAL_JUDGE_BASE_URL=http://localhost:11434/v1 \
DGO_EVAL_TRIALS=3 pytest evals/ -v -s

# Evaluating the company's real gateway instead - same command, just
# point it at the real endpoint/model name and, if it needs one, a key:
DGO_EVAL_JUDGE_MODEL=<real-model-name> \
DGO_EVAL_JUDGE_BASE_URL=<real-gateway-url>/v1 \
DGO_EVAL_JUDGE_API_KEY=<real-key-if-needed> \
DGO_EVAL_TRIALS=3 pytest evals/ -v -s
```

**This only configures the eval judge, not the app under test.** For the
eval results to actually say something about the company's model, the
*app* also needs to be pointed at it - set `LLM_BASE_URL`/`LLM_MODEL`/
`LLM_SQL_MODEL` in `backend/.env` to the same real values (see that
file's comments) and restart the backend container before running the
suite, otherwise you're evaluating whatever `backend/.env` happens to be
configured with at the time (a local Ollama, a placeholder, or the real
gateway - check first).

Honest framing (see `evals/test_chat_eval.py`'s module docstring): this
is a repeatable signal, not a certified quality gate - LLM output is
non-deterministic, so each query runs `DGO_EVAL_TRIALS` times and results
get aggregated into a pass rate rather than asserted per-trial. The one
hard, non-LLM-judged assertion (matched products must always be real
catalog ids) is a regression guard on WrenAI's governance; everything
else is scored against a deliberately low floor, documented in
HANDOFF.md alongside the known keyword-precision limitation it's meant
to catch a regression against, not paper over. That floor and the
~50-65% reliability number in HANDOFF.md are both from testing against a
local Ollama model - expect (and record) a different number once this
runs against the real production LLM, that's the whole point of doing it.

Runs worth keeping a record of (e.g. after a real change to the chat/
WrenAI code, judge model, or trial count) get appended to `evals/EVAL_LOG.md`
- not every ad-hoc local run, just ones worth comparing against later.

## What's implemented vs. stubbed

- `/health`, `/api/catalog`, `/api/catalog/{id}/connection` (falls back to
  a hardcoded mock catalog), `/api/chat` (SSE streaming, ported
  greeting/zero-hallucination/bilingual logic from the PoC, plus a local
  keyword-match fallback if the LLM call fails), `/api/tickets*` (real
  Postgres persistence, real approval state machine) — **implemented**.
- LLM call (`app/integrations/llm_client.py`) — implemented against an
  **assumed** OpenAI-compatible endpoint shape, confirmed working for
  real against a local Ollama (see `.env.example`'s comments). The
  company's actual on-prem model gateway is still a different,
  unconfirmed endpoint - point `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`
  at it to find out.
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

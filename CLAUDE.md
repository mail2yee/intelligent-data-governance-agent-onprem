# Start here

Read `HANDOFF.md` first — it's the authoritative source of truth for
this repo (why it exists, constraints, integration swaps, UI direction,
and current status). Keep it updated as work progresses; a future
Claude Code session in this directory has no memory of past sessions
and relies entirely on this file plus git history to pick up where
things left off.

## Quick orientation

- On-prem rebuild of a GCP PoC (`data_governance_agent_poc.ai`, sibling
  repo, not linked here). Target: air-gapped company network that
  reaches GitHub but not PyPI/npm/Docker Hub.
- The two repos are **intentionally separate, no shared code**. A
  different sibling repo, `agent_mem0_poc`, has an already-proven
  reference implementation of WrenAI's current (2026) architecture -
  worth checking before assuming anything about how WrenAI works.
- Stack: FastAPI + PostgreSQL backend, React + Vite frontend (visual
  style aligned to the company's internal TADiS design system, see
  HANDOFF.md's UI/UX section), real Camunda **7.22** (REST API,
  `/engine-rest` - corrected 2026-07-29 from an earlier, wrong Camunda
  8/Zeebe assumption) and DataHub (GraphQL) integrations with graceful
  fallback to mocks on failure, plus WrenAI (embedded Python library, not
  a service) as a zero-hallucination semantic layer for chat.py's
  data-subject matching.
- **Camunda and DataHub can both be fully self-hosted locally now**
  (`docker-compose.yml`'s `camunda` service + `scripts/setup-datahub.sh`)
  - the full create-ticket -> Camunda-starts-process -> owner-approves ->
  Camunda-task-completes loop is verified end-to-end through the actual
  app. See HANDOFF.md "Camunda + DataHub: local hosting and the
  external-service switch" before touching either integration.
- Every `/api/*` route requires `X-API-Key` when `API_KEY` is set (empty
  = disabled, the default) - an interim, coarse auth gate added
  2026-07-30 after a security review found none. Does **not** fix
  `submit_approval()`'s separate owner-impersonation gap (needs real
  SSO/OIDC). Frontend also had 3 real XSS sites (raw LLM/user text via
  `dangerouslySetInnerHTML`) fixed the same session - see HANDOFF.md's
  "Security review" section before touching auth or chat rendering.
- Discover search has a general/AI mode toggle (defaults to general -
  plain keyword `ILIKE` match, no LLM call) - see HANDOFF.md's "General
  search / AI search toggle" section.
- `chat.py`'s greeting detection is keyword-only (`is_greeting()`) - an
  LLM-based fallback classification was tried and reverted (unreliable
  on a small local model, see HANDOFF.md's "Greeting detection fix"
  section) in favor of offline, human-reviewed query mining
  (`backend/scripts/review_unmatched_queries.py`).
- Backend: `ruff` + `mypy` clean, 88 pytest tests (`backend/tests/`) plus
  a separate DeepEval-based LLM-judge eval suite (`backend/evals/`, not
  part of a bare `pytest` run - see `backend/README.md`'s "Evals"
  section). Frontend: `oxlint` clean, 29 vitest tests. All pass.
- LLM integration (OpenAI-compatible assumption) is confirmed working
  against a real local Ollama, but **not yet against the company's
  actual on-prem gateway** - pointing both the app (`backend/.env`) and
  the eval judge (`DGO_EVAL_JUDGE_*`) at the real gateway is the current
  top of the "not done yet" list, see HANDOFF.md.
- **GHCR (`ghcr.io/mail2yee/...`) confirmed reachable from the office**
  (2026-08-04) - not just a fallback path anymore, this is now the
  actual mechanism for getting `backend`/`frontend` (built by this repo)
  *and* `camunda`/`postgres` (mirrored from Docker Hub via
  `scripts/mirror-image-to-ghcr.sh`, since the company's internal
  registries don't have everything - no Camunda image there) onto the
  air-gapped network. All four images are public, pulled anonymously,
  confirmed `amd64/linux` (matching the company's servers, not this dev
  machine's arm64 - a real platform-mismatch bug hit and fixed twice
  now, see HANDOFF.md). Self-hosting Postgres this way is a
  dev-environment choice, not a production plan - revisit before any
  shared/production deployment, see HANDOFF.md's "Getting Camunda +
  Postgres into the office network" section.
- CI: intentionally NOT GitHub Actions — company uses internal Azure
  DevOps for CI/CD. Don't build `.github/workflows/`.
- Workflow: user develops with Claude Code at home, pulls via git (or a
  ZIP download, which loses the ability to `git pull`/auto-push results)
  at the (air-gapped) office to test — no Claude Code access there.
  README.md's "到公司後怎麼做" section is the step-by-step office
  checklist; keep it in sync if the startup/deployment story changes.

Full detail, open items, and the "not done yet" list live in
`HANDOFF.md` — don't duplicate them here; update that file instead.

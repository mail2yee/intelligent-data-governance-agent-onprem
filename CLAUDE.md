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
- Backend: `ruff` + `mypy` clean, 63 pytest tests (`backend/tests/`) plus
  a separate DeepEval-based LLM-judge eval suite (`backend/evals/`, not
  part of a bare `pytest` run - see `backend/README.md`'s "Evals"
  section). Frontend: `oxlint` clean, 29 vitest tests. All pass.
- LLM integration (OpenAI-compatible assumption) is confirmed working
  against a real local Ollama, but **not yet against the company's
  actual on-prem gateway** - pointing both the app (`backend/.env`) and
  the eval judge (`DGO_EVAL_JUDGE_*`) at the real gateway is the current
  top of the "not done yet" list, see HANDOFF.md.
- GHCR (`ghcr.io/mail2yee/...`) images are built, pushed, public, and
  confirmed pullable anonymously - a fallback path if the company
  network can't `pip install`/`npm ci` directly. Whether the office
  firewall reaches `ghcr.io` itself is still unconfirmed.
- CI: intentionally NOT GitHub Actions — company uses internal Azure
  DevOps for CI/CD. Don't build `.github/workflows/`.
- Workflow: user develops with Claude Code at home, pulls via git (or a
  ZIP download, which loses the ability to `git pull`/auto-push results)
  at the (air-gapped) office to test — no Claude Code access there.
  README.md's "到公司後怎麼做" section is the step-by-step office
  checklist; keep it in sync if the startup/deployment story changes.

Full detail, open items, and the "not done yet" list live in
`HANDOFF.md` — don't duplicate them here; update that file instead.

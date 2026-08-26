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
- **Camunda and DataHub can both be fully self-hosted locally** via
  optional compose overlays (`docker-compose.camunda.yml`,
  `datahub/docker-compose.datahub.yml` - DataHub is 7 containers: GMS,
  frontend, MySQL, Kafka, OpenSearch, Actions, a one-shot init job) -
  the full create-ticket -> Camunda-starts-process -> owner-approves ->
  Camunda-task-completes loop is verified end-to-end through the actual
  app. **`./deploy.sh` is the one-command entry point, with two modes**:
  no flag = local dev (tries to self-host Camunda/DataHub via image,
  falls back to `backend/.env`'s `CAMUNDA_BASE_URL`/`DATAHUB_API_URL`
  per-service if a pull fails); **`--office` = Camunda/DataHub are
  never self-hosted at all**, always config, adopted 2026-08-26 after
  the office's vulnerability scanner blocked the mirrored images and
  further version bumps couldn't get the CVE count to zero (Camunda has
  no newer patch available in its pinned 7.22.x line at all). Postgres
  has no fallback in either mode - self-hosting it is the actual plan,
  not a convenience (the company's own Postgres is an unwieldy HA
  setup). See HANDOFF.md's "Self-hosted images with a config fallback"
  and "Office mode" sections before touching either integration or
  `deploy.sh`.
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
- **GHCR (`ghcr.io/mail2yee/...`) is reachable from the office, but is
  no longer how the office gets Camunda/DataHub/backend/frontend**
  (reversed 2026-08-26, see "Office mode" in HANDOFF.md). GHCR mirroring
  (`scripts/mirror-image-to-ghcr.sh`, all images public, confirmed
  `amd64/linux` - a real platform-mismatch bug hit and fixed twice, see
  HANDOFF.md) is still how **local dev** self-hosts everything
  (`postgres`, `camunda`, DataHub's 7 images, plus a fallback path for
  backend/frontend if a local build fails) - just not what the office
  does anymore. `./deploy.sh --office` builds backend/frontend from
  source only (hard error if that fails, no GHCR fallback) and never
  touches Camunda/DataHub images at all (config-only, see above). Only
  `postgres` still reaches the office via `ghcr.io` in both modes -
  self-hosting it is the actual plan, not a dev-environment shortcut
  (the company's own Postgres is an unwieldy HA setup - MariaDB was
  considered as an alternative self-hosted engine and rejected, its
  image scanned with the same critical count and *worse* high count
  than `postgres:16-alpine`, see HANDOFF.md).
- CI: intentionally NOT GitHub Actions — company uses internal Azure
  DevOps for CI/CD. Don't build `.github/workflows/`.
- Workflow: user develops with Claude Code at home, pulls via git (or a
  ZIP download, which loses the ability to `git pull`/auto-push results)
  at the (air-gapped) office to test — no Claude Code access there.
  README.md's "到公司後怎麼做" section is the step-by-step office
  checklist; keep it in sync if the startup/deployment story changes.

Full detail, open items, and the "not done yet" list live in
`HANDOFF.md` — don't duplicate them here; update that file instead.

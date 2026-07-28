# Handoff: from the GCP PoC to the on-prem build

This project is a from-scratch, on-prem rebuild of the app in the sibling
repo `data-governance-agent-poc` (GCP PoC, private GitHub repo under
`mail2yee`). That repo is **not going away** — once the company's public
cloud access is approved, `deploy_dgo.sh` there is still the deployment
path for GCP. This repo exists because the GCP PoC's dependencies
(Gemini, Firestore, Dataplex, Camunda SaaS) are all cloud services
unreachable from the company's air-gapped internal network, and its
frontend is a single embedded-JS-string Python file, not React.

The two repos intentionally **do not share code**. Port ideas and design
decisions across manually; do not try to build a compatibility layer.

## Why this repo exists / constraints that shaped it

- Company internal network can reach GitHub (git clone/pull/push work),
  but **cannot** reach `pypi.org`, `registry.npmjs.org`, or `docker.io`.
  There is an internal Docker image registry/mirror. Whether there's also
  an internal PyPI/npm mirror is **unconfirmed** — if not, `pip install`/
  `npm install` during `docker build` needs to happen somewhere with
  internet access (e.g. building the image at home and pushing it to the
  internal registry, or `docker save`/`docker load`), not inside the
  company network. Confirm this before assuming `docker build` can run
  on-site.
- **Testing a second path (2026-07-27):** `docker-compose.yml` now also
  sets `image:` on `backend`/`frontend` pointing at
  `ghcr.io/mail2yee/intelligent-data-governance-agent-onprem-{backend,frontend}:latest`,
  so the workflow can be "build+push at home, `docker compose pull` at
  the office" instead of relying on the internal registry. The packages
  are being made **public** on GHCR deliberately for this test (repo
  stays private) so the office side needs no GitHub PAT/login — revisit
  and switch back to private once this is confirmed working, and figure
  out PAT handling at the office at that point. Whether the office
  firewall even lets `ghcr.io` through (distinct host from `github.com`)
  is **unconfirmed** — that's exactly what's being tested. See README.md
  "Testing the build at home, run at office path via GHCR".
- Runtime target is eventually Kubernetes; Docker (docker-compose) is
  what's usable right now. The `k8s/` folder is a placeholder — don't
  build it out until asked.
- Workflow: development happens with Claude Code at home (this machine
  has internet). The user carries the repo to the office via `git pull`
  (GitHub is reachable there), runs/tests it there, and commits test
  results back to git so they can be reviewed at home in a later
  session. Claude Code is not available inside the office network.

## Integration swaps (GCP PoC -> this repo)

| Concern | GCP PoC | This repo |
|---|---|---|
| LLM | Gemini via `google-genai`, streamed via SSE | On-prem model, assumed **OpenAI-compatible** `POST /v1/chat/completions` with `stream: true` (see `backend/app/integrations/llm_client.py`) — **unconfirmed**, adjust if the real endpoint shape differs |
| Workflow engine | Camunda SaaS (`login.cloud.camunda.io`), fire-and-forget, not really wired to approval state | Camunda **self-managed** (on-prem), real `pyzeebe` client wired in (see `backend/app/integrations/camunda_client.py`) — but no BPMN process is deployed yet (confirmed with the user), so it currently fails gracefully every time until one exists. `CAMUNDA_PROCESS_ID` in `.env` is the only thing to change once it does. |
| Data catalog | Dataplex (GCP) | DataHub GraphQL API, real client wired in (see `backend/app/integrations/datahub_client.py`) — assumes `maturity_level`/`data_quality_score`/etc. live as DataHub *customProperties* (confirmed assumption with the user) and derives each product's `id` by slugifying its DataHub display name. Falls back to the same hardcoded mock catalog as the GCP PoC if DataHub is unreachable or returns nothing. |
| Ticket storage | Firestore | PostgreSQL (see `backend/app/db.py`) |
| Semantic layer (zero-hallucination data-subject matching) | N/A | **Decided and built (2026-07-27):** WrenAI, embedded as a Python library (`wrenai[postgres]`) inside the backend process - see `backend/app/integrations/wrenai_client.py` and `wren/project/`. Scope is deliberately narrow: verify *which catalog data subject* matches a chat query, not full NL -> SQL -> real-data-answer execution (that stays out of scope, see below) |
| Frontend | Single Python string containing HTML/CSS/JS, served by FastAPI | React (Vite) SPA, calling the FastAPI backend as a separate JSON/SSE API |

## Business logic and data model to preserve

This is the part that's actually reusable know-how, even though the code
isn't shared. Port the *behavior*, not the files.

**Ticket / approval model** (was Firestore documents, now Postgres rows):
```
ticket: { id, products[], objective, purpose, status, created_at, owners[] }
approval: { ticket_id, owner_email, decision (PENDING/Approve/Reject),
            reason, created_at, completed_at, cycle_time_seconds }
```
Status derivation: `REJECTED` if any approval is `Reject`; `APPROVED` if
all owners have decided and none rejected; otherwise `PENDING_APPROVAL`.
Owners for a ticket are the union of each selected data product's
`owner`, padded to at least 3 with fallback compliance/security reviewer
emails if fewer than 3 (this padding rule is arbitrary PoC filler, worth
reconsidering rather than blindly porting).

**SLA highlighting:** for any ticket still pending, find the owner with
the longest elapsed time since their approval record was created; if
that exceeds 24 hours, surface a warning. This was client-side logic in
the PoC (computed from `created_at` timestamps) — fine to keep client-side
or move server-side, whichever is more natural in the new stack.

**Chat / search assistant** (`/chat` in the PoC):
- Detect greetings (see `is_greeting()` in the PoC — a word-list +
  punctuation-stripping check) and reply instantly, without calling the
  LLM at all. This was an explicit user requirement: greetings must be
  fast.
- Otherwise, ground the LLM strictly against the known catalog — the PoC
  used a prompt instructing the model to only recommend data subjects
  that literally exist in the catalog, and to reply with an exact
  "not found" sentence otherwise (checked post-hoc via substring match
  to decide whether to show result cards). Keep this "zero hallucination"
  guarding behavior.
- **Must support both zh and en**, driven by a `lang` field the frontend
  sends on every chat request — not just UI chrome translation, the
  actual LLM instructions and canned replies must branch on it too. This
  was a real bug fixed in the PoC (English input got no proper response)
  — don't reintroduce it.
- **Must stream via SSE**, not a single blocking JSON response. Event
  types: `step` (a reasoning-stage label, shown live), `token` (a chunk
  of the reply, appended live), `final` (the complete structured
  payload: reply, matched_products, thinking_steps). This was an
  explicit, deliberate choice — the user confirmed they want genuine
  live "steps popping up while it runs," which is why greetings skip any
  artificial delay but a non-LLM fallback path (if you ever need one)
  should fake pacing with short delays rather than dumping everything at
  once. See the PoC's `/chat` route for the exact event shapes.

## UI/UX direction (approved, carry into React)

Redesigned once already in the PoC from a dark neon aesthetic to a
Google Material-inspired design, then **restyled again on 2026-07-28** to
align with the company's internal TADiS design system (see
`TADiS-AI/TADiS`, a private repo — the boss's directive was "use this
style"). Layout/structure below is unchanged from the earlier Material
direction; only the color palette, font stack, and border-radius scale
moved. Scope was deliberately kept to visual tokens only — this app
stays its own independently-deployed React app (not merged into the
TADiS codebase, not turned into an "Applications" tile/widget there
either — those were both considered and explicitly not chosen, see the
options discussed in that session if this needs revisiting):

- **Layout:** top app bar + collapsible left nav rail (groups toggle via
  a chevron) + main content area. Not a single split-screen layout.
- **Color:** light theme by default **regardless of OS
  `prefers-color-scheme`** (explicit user requirement) with a manual
  toggle to dark. TADiS's brick/rust accent (`#9a3412` light /
  `#e44e1c` dark, taken from `TADiS-AI/TADiS`'s `defaultColorCode.jsx` /
  `darkModeColorCode.jsx`), neutral backgrounds tinted toward the accent
  (not pure grey), semantic colors (success/warning/critical) kept
  separate from the accent hue. All values are CSS custom properties in
  `frontend/src/index.css` — variable *names* are unchanged from the
  Google-blue version, only values moved, so no component needed
  touching.
- **Border radius:** bumped from an 8px scale to 12px across
  `frontend/src/App.css` (pills/circles/a couple of already-14px spots
  left alone) to read closer to TADiS's MUI `shape.borderRadius: 14`
  without adopting MUI itself.
- **Type:** Roboto/Segoe UI-first font stack with system fallbacks (was
  "Google Sans"-first — dropped since TADiS doesn't use it either and it
  was already just falling back to Roboto in practice, no `@font-face`
  ever loaded it), monospace for IDs/data values/timestamps.
- **Discover screen:** large centered Google-search-style search box as
  the hero, quick-suggestion chips, result cards below, a collapsed-by-
  default "show reasoning steps" disclosure (auto-expands live while a
  search is streaming in).
- **Approvals screen:** Gmail/Admin-console-style expandable ticket rows
  (not big stacked cards), status chips, SLA warning banner on the
  expanded row when relevant.
- **Assistant persona:** named "小幫手" / "Assistant" (not "Copilot" —
  renamed partway through the PoC), docked bottom-right collapsible
  panel, not a floating neon bubble.
- **i18n:** zh/en toggle covering all UI chrome and assistant replies
  (see chat section above).
- **Platform name:** 智慧資料治理平台 / "Intelligent Data Governance"
  (renamed from "半導體資料治理平台"/"Semiconductor Data Governance
  Platform" partway through the PoC — matches this repo's name).

The GCP PoC repo has a fully working reference implementation of all of
this in plain HTML/CSS/JS (`app/main.py`'s `index()` route) — it's what
the React port here was built from (same class names on purpose, to keep
future diffs against it readable).

## What's actually in this repo right now

**The full PoC UI has been ported to React** (Discover search with live
SSE streaming, Approvals list with SLA tracking, cart/submit dialog,
connection-code dialog, Copilot dock, zh/en toggle, light/dark toggle,
collapsible nav) and verified end-to-end against the real backend +
Postgres + Playwright (search → cart → submit → approve/reject →
i18n/theme toggles → copilot), zero console errors. See
`frontend/src/components/` — one file per UI piece, `frontend/src/api.js`
for the backend calls, `frontend/src/i18n.js` for translations.

Backend gained one thing beyond the original scaffold while wiring the
port up: `run_chat()` now falls back to a local keyword-match
(`local_rule_match()` in `backend/app/chat.py`) when the LLM call fails,
instead of just showing an error — mirrors the PoC's local-dev
convenience, and also just makes the app degrade gracefully if the LLM
gateway is ever briefly unreachable in real use. It only knows the mock
catalog's 3 entries; revisit once DataHub is wired with real catalog
contents.

**Camunda and DataHub are now real, wired clients** (not mock stubs):
`backend/app/integrations/camunda_client.py` uses `pyzeebe` to actually
start a process instance; `backend/app/integrations/datahub_client.py`
actually queries DataHub's GraphQL API. Confirmed against each project's
own docs (endpoint paths, auth header shape, the pyzeebe channel/run_process
call). Verified end-to-end that both correctly attempt a real
connection and fail gracefully (falling back to the mock catalog / a
"Skipped" ticket status) when nothing's listening yet — tested against
real Postgres + a real (unreachable, as expected) gateway/endpoint, not
just import-checked. What's still open, because it genuinely needs
facts only reachable from inside the company network:
- No BPMN process is deployed yet — `CAMUNDA_PROCESS_ID` in `.env` is a
  placeholder. Deploy one, point `.env` at it, done — no code change.
- Camunda auth defaults to unauthenticated (`create_insecure_channel`).
  If it turns out Identity/Keycloak OAuth is required, the OAuth path in
  `camunda_client.py` is implemented but **untested against a live
  server** — pyzeebe's docs didn't confirm a purpose-built helper for
  this, so it's built on core `grpc` primitives instead. Verify it once
  real credentials exist.
- DataHub field mapping assumes `maturity_level`/`data_quality_score`/etc.
  live as DataHub *customProperties* (confirmed assumption with the
  user) under `dataset.properties.customProperties` — the exact nesting
  for the `Dataset` type specifically wasn't confirmable from the docs
  fetched, only the general customProperties pattern across entity
  types. Check the query in `datahub_client.py` against your instance's
  GraphQL schema explorer (usually `{DATAHUB_API_URL}/api/graphiql`) and
  adjust if it doesn't match.
- LLM client's OpenAI-compatible assumption is still unconfirmed against
  the real on-prem gateway.

The "目錄維護"/Catalog Admin nav item is still a disabled placeholder
(was in the PoC too — no catalog editing UI ever existed there either).

**WrenAI semantic layer, added 2026-07-27** (`backend/app/integrations/wrenai_client.py`,
`wren/project/`): the user decided this is needed so that `chat.py`'s
data-subject matching is structurally zero-hallucination, not just
prompt-instructed. Confirmed by actually installing `wrenai` locally and
smoke-testing it (not just reading docs) — see the sibling
`agent_mem0_poc` repo's `memory-api/wren_client.py` / README for the
original proof-of-concept this was ported from (same pattern, already
verified end-to-end there against a real Postgres, including confirming
`strict_mode` governance actually rejects invalid columns):

- **Architecture note, easy to get wrong:** WrenAI had a major
  rearchitecture on 2026-05-07. The old "docker-compose service with a
  REST/GraphQL API" shape is now called **Wren GenBI Classic** (frozen on
  the upstream repo's `legacy/v1` branch) — current WrenAI is a plain
  **Python package** (`wrenai[postgres]`) imported directly into the
  backend process (`wren.engine.WrenEngine`), not a separate container.
  Don't reintroduce a `wren-ai-service`/`wren-ui` container based on
  older docs or search results — they describe the retired architecture.
- **What it actually does here:** `chat.py`'s LLM writes a SQL `SELECT`
  against a `data_products` table (mirroring the DataHub catalog, kept in
  sync via `wrenai_client.sync_catalog()`) using the field names declared
  in the semantic model (`wren/project/models/data_products/metadata.yml`).
  WrenAI's governed engine (`strict_mode`) executes it and structurally
  cannot return a row that doesn't exist — this is the actual
  zero-hallucination mechanism, not WrenAI generating SQL for us. This is
  layered *on top of* the existing prompt-instructed/substring-matching
  approach in `chat.py`, which now only serves as the fallback when this
  integration itself fails (LLM unreachable for the SQL-writing call,
  WrenAI/MDL unavailable, etc.) — see `resolve_via_semantic_layer()`.
- **Deliberately out of scope:** this only answers "which data subject
  matches this need" for the user to then select (same cart/ticket/
  approval flow as before) — it does **not** execute analytical queries
  against the real underlying business databases to hand back actual
  numbers. That's a distinct, larger decision (whether such queries
  should be gated by this app's approval workflow or not) that hasn't
  been made — don't expand this integration's scope to real query
  execution without that decision being made explicitly first.
- **One WrenAI project = one physical data source, full stop** (confirmed
  via the PoC's testing) — it can't join across the different databases
  the DataHub catalog's entries actually live in (see each mock entry's
  `db_host`/`db_type`, e.g. Postgres vs Oracle, different hosts even
  within Postgres). That's exactly why this models *our own Postgres
  mirror of the catalog*, not the underlying business databases.
- **Docker build note:** `wrenai`'s Rust engine (`wren-core-py`) has a
  prebuilt wheel for **linux/amd64** and macOS but **not linux/aarch64**
  (confirmed via PyPI's file listing for `wren-core-py` 0.7.2) — build/
  ship the backend image targeting `linux/amd64` to avoid needing a Rust
  toolchain + crates.io access during the Docker build (a fourth
  air-gapped-network landmine beyond PyPI/npm/Docker Hub, on top of
  everything already documented above about building at home). See the
  comment in `backend/Dockerfile`.
- **Verified end-to-end in this repo's actual Docker Compose stack
  (2026-07-28):** `docker compose up --build` (with `platform: linux/amd64`
  forced on the backend service - see docker-compose.yml, needed on
  Apple Silicon dev machines since `wren-core-py` has no linux/aarch64
  wheel) - `backend/entrypoint.sh`'s `wren profile add` + `wren context
  build` both succeeded against the real backend Postgres container, and
  a real governed query through the running container returned correct
  rows for a valid query and correctly rejected (`WrenError
  [GENERIC_USER_ERROR] column "made_up_column" does not exist`) an
  invalid one. Also confirmed via the actual Discover UI: with no real
  LLM gateway configured, the first LLM call fails as expected and falls
  back to `local_rule_match()`, which still returned the correct product
  card - the full graceful-degradation chain works as designed. Not yet
  confirmed: the semantic-layer verification path *specifically* (the
  LLM writing SQL, `resolve_via_semantic_layer()`) against a real LLM
  gateway, since none is configured yet - only the WrenAI/governed-engine
  half was exercised directly (via a manual `docker compose exec` check),
  not through a real two-LLM-call chat turn.

## Engineering standards / tests — IN PROGRESS as of this commit

The user asked for this explicitly (no hardcoding, linting/type
standards, and - emphatically - real tests, not just manual verification
during development). Status, so a fresh session picking this up mid-flight
knows exactly where things stand:

**Done:**
- Two real hardcodes fixed: the fallback-approver emails in
  `main.py`'s `create_ticket` now come from `settings.default_fallback_approvers_list`
  (env-configurable), and `docker-compose.yml`'s Postgres password now
  reads from a `POSTGRES_PASSWORD` env var (root `.env.example` added)
  instead of being hardcoded, defaulting to the same weak value only for
  zero-setup local dev.
- Backend: `ruff` (lint + format) and `mypy` configured via
  `backend/pyproject.toml`, both clean. Caught and fixed real issues in
  the process: an unused, incorrectly-typed `get_session()` function in
  `db.py` was dead code (removed, not fixed - nothing called it) and a
  nested-`with` simplification in `llm_client.py`.
- Backend: a real pytest suite exists now (`backend/tests/`, 42 tests as
  of the WrenAI addition, see `backend/README.md` for how to run it)
  covering `chat.py` (greetings, LLM success/failure streaming, local
  fallback matching, the semantic-layer verification/fallback chain), the
  full ticket/approval API and state machine, and all three integration
  clients' fallback behavior. **This caught two real bugs no amount of
  my manual curl/Playwright testing had surfaced:**
  1. `submit_approval`'s cycle-time calculation crashed
     (`TypeError: can't subtract offset-naive and offset-aware datetimes`)
     — SQLite doesn't round-trip timezone-aware datetimes the way
     Postgres does, so this only broke against the test DB, but the fix
     (normalize `created_at`'s tzinfo before subtracting, in `main.py`)
     is a genuine robustness improvement regardless of backend.
  2. `run_chat`'s matched-product detection only checked whether the
     literal hyphenated id slug (`customer-capacity-allocation`)
     appeared in the LLM's reply text — but a real LLM naturally answers
     with the human-readable name ("Specific Customer Capacity
     Allocation"), not the slug. This means matching likely never
     actually worked against a real model's natural phrasing, in
     *either* this repo or the original GCP PoC (which had the identical
     pattern) - nobody had tested that specific path against real output
     shaped like a real LLM would produce it. Fixed in `chat.py` to also
     check the catalog item's `name` field, not just its `id`.
- Frontend: `oxlint` (already present from the Vite scaffold) run for
  the first time - found and fixed two real unused-prop warnings in
  `TopBar.jsx`.
- Frontend: real test suite added (vitest + React Testing Library, 29
  tests) - `utils.js`, an `i18n.js` zh/en key-parity check (prevents
  translation drift), `streamChat()`'s SSE frame parsing (including a
  frame deliberately split across two chunks), and three components
  (ProductCard, NavRail's collapse behavior, TicketRow's approve/reject
  + SLA banner threshold). All passed first try - no bugs found here.

**Not done yet (next up):**
- CI - intentionally NOT GitHub Actions. Company uses internal CI/CD
  (Azure DevOps) - pipeline should be built there when that's next up,
  not `.github/workflows/`.

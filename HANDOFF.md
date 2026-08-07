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
- **Second path via GHCR — publish side done and confirmed working
  (2026-07-28):** `docker-compose.yml` sets `image:` on `backend`/
  `frontend` pointing at
  `ghcr.io/mail2yee/intelligent-data-governance-agent-onprem-{backend,frontend}:latest`.
  Both images have actually been built and pushed (`docker login
  ghcr.io` with a classic PAT scoped `write:packages` - a fine-grained
  PAT hit a `403 Forbidden` on the same push, switching to classic
  fixed it; GHCR's manifest-commit step also hit a couple of transient
  `500 Internal Server Error`s that cleared on retry, unrelated to
  auth), and both packages are flipped to **public** on GHCR (repo
  stays private) - confirmed by logging out locally and pulling both
  anonymously (no login at all) successfully, including re-confirming
  the backend needs `--platform linux/amd64` explicitly on an arm64
  puller (expected, see the Rust-wheel note above; not an issue on the
  company's x86_64 servers).
  **Still unconfirmed: whether the office firewall lets `ghcr.io`
  through at all** (distinct host from `github.com`, which is
  confirmed reachable) - today's test only confirms the publish side
  works and that images are pullable from an arbitrary internet
  connection, not that this specific office network can reach this
  specific host. That's the one thing left to test on-site. If it
  works, the office side is just `git pull && docker compose pull &&
  docker compose up -d`, no PAT needed. Revisit switching the packages
  back to private once past the testing phase. See README.md "Getting
  an image onto the air-gapped network".
- **Real bug found at the office (2026-07-29): `ghcr.io` reachability
  was fine, but only the backend image would pull - frontend had no
  matching manifest for the office's x86_64 servers.** Root cause: only
  `backend`'s `docker-compose.yml` service had a `platform: linux/amd64`
  pin (needed there for wrenai's Rust wheel, see above); `frontend` had
  none, so it silently built for whatever the dev machine's native
  architecture was (arm64, on this Apple Silicon Mac) when first pushed,
  and GHCR only ever got an arm64 manifest for it. Fixed: added the same
  `platform: linux/amd64` pin to `frontend`, rebuilt, and re-pushed -
  confirmed both images now have amd64 manifests and both still pull
  anonymously. This is exactly the kind of gap the "verify the same way
  the office will consume it" habit (rather than just "it built on my
  machine") is meant to catch - worth remembering if a similar
  build-at-home-ship-elsewhere path gets added for anything else later.
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
| LLM | Gemini via `google-genai`, streamed via SSE | On-prem model, assumed **OpenAI-compatible** `POST /v1/chat/completions` with `stream: true` (see `backend/app/integrations/llm_client.py`) — confirmed this shape works against a real local Ollama (2026-07-28), but the **company's actual gateway is still unconfirmed** (a different endpoint) — adjust `llm_client.py` if its real shape differs |
| Workflow engine | Camunda SaaS (`login.cloud.camunda.io`), fire-and-forget, not really wired to approval state | **Camunda 7 (self-managed, REST API)** — corrected 2026-07-29 from an earlier, wrong Camunda 8/Zeebe assumption; the company's real instance is **7.22**. Real REST client (`backend/app/integrations/camunda_client.py`), a verified BPMN process (`camunda/data-gov-approval.bpmn`), and a working local self-hosted instance (`docker-compose.yml`'s `camunda` service) — see "Camunda + DataHub: local hosting and the external-service switch" below for the full loop, including the owner-approves-in-app -> Camunda task completes mechanism. |
| Data catalog | Dataplex (GCP) | DataHub GraphQL API, real client wired in (see `backend/app/integrations/datahub_client.py`) — assumes `maturity_level`/`data_quality_score`/etc. live as DataHub *customProperties* (confirmed assumption with the user) and derives each product's `id` by slugifying its DataHub display name. Falls back to the same hardcoded mock catalog as the GCP PoC if DataHub is unreachable or returns nothing. Local self-hosting via `scripts/setup-datahub.sh` — see below. |
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

## Camunda + DataHub: local hosting and the external-service switch

**Camunda 8 -> 7.22 correction (2026-07-29):** the entire Camunda
integration was originally built against Camunda 8 (self-managed Zeebe,
gRPC, `pyzeebe`) based on the original HANDOFF description. The user
corrected this mid-session: the company's actual instance is **Camunda
7.22**, a completely different product - REST API (`/engine-rest`), no
gRPC, no job-worker/message-correlation model. `camunda_client.py` was
rewritten from scratch (not patched) and hands-on verified against a
real local `camunda/camunda-bpm-platform:7.22.0` container via raw curl
before writing any production code, then again through the actual
rewritten app code once wired up - see below.

**Local self-hosting, done and verified end-to-end 2026-07-29/30** (the
user's explicit ask: "一次全部做完：這兩項 + 簽核完成回報 Camunda" - local
hosting for both Camunda and DataHub, plus the approval-completion-
reports-back-to-Camunda mechanism):

- **Camunda**: `docker-compose.yml`'s `camunda` service
  (`camunda/camunda-bpm-platform:7.22.0`, host port 8082 - 8080 is
  reserved for DataHub's GMS, 8081 is taken by an unrelated project on
  this dev machine). `backend/entrypoint.sh` deploys
  `camunda/data-gov-approval.bpmn` on every backend startup via a small
  inline Python/httpx script (`deploy-changed-only=true` makes re-
  deploying a no-op) - tolerant of Camunda being unreachable, doesn't
  block backend startup. Verified the **full loop through the real,
  running app** (not just curl): `POST /api/tickets` -> Camunda process
  instance starts, one task per owner (multi-instance user task) ->
  `camunda_process_instance_id` persisted on the `Ticket` row ->
  `POST /api/tickets/{id}/approvals` for one owner -> that owner's
  Camunda task completes (confirmed via a direct Camunda REST query:
  task count drops from 3 to 2) -> after all owners approve, the ticket
  reaches `APPROVED` in this app's own DB *and* the Camunda process
  instance itself ends (`GET .../process-instance/{id}` 404s). This
  app's ticket/approval state machine remains the source of truth;
  Camunda mirrors progress, it doesn't decide it.
- **DataHub**: run as its own independent `datahub docker quickstart`
  stack (not a service in this repo's `docker-compose.yml`) via
  `scripts/setup-datahub.sh`, which also seeds 3 sample dataset entities
  (`datahub/seed_catalog.py`) matching `datahub_client.py`'s expected
  shape (`properties.name`/`description`/`customProperties`). **This
  choice matters in practice, not just style**: this dev machine already
  had a DataHub instance running from the sibling `agent_mem0_poc` repo,
  with its GMS bound to host port 8080 - reusing that shared instance
  (rather than each repo running its own) avoided two DataHub stacks
  fighting over the same port. Because of that, **this app's frontend
  moved from host port 8080 to 8090** (`docker-compose.yml`) to leave
  8080 free for DataHub. Verified end-to-end: seeded real dataset
  entities, confirmed `datahub_client.py`'s actual GraphQL query/parsing
  code reads them back correctly (both directly and through the running
  backend container via `host.docker.internal:8080`), then created a
  real ticket using a DataHub-sourced product id and confirmed it flowed
  correctly into Camunda too.
- **The config switch to point at the company's real external
  services** (the other half of the user's original ask) is already
  realized cleanly for both, since neither integration was ever built
  Docker-network-coupled: for Camunda, change `CAMUNDA_BASE_URL` (to the
  company's real `engine-rest` URL) and `CAMUNDA_BASIC_AUTH_USERNAME`/
  `PASSWORD` if it requires auth - `CAMUNDA_PROCESS_DEFINITION_KEY` stays
  as-is unless the company's own deployed process uses a different key.
  For DataHub, change `DATAHUB_API_URL`/`DATAHUB_API_TOKEN`. No code
  change needed either way, same pattern already used for `LLM_BASE_URL`.

**Gaps flagged during the original gap-analysis conversation, explicitly
deferred (not decided or built) rather than silently skipped:**
- **No authentication on `submit_approval()`** - anyone who knows a
  ticket id can approve/reject as any owner by supplying their email in
  the request body; there's no check that the caller *is* that owner.
  Matters more once "click a link in an email" is real (see next point) -
  a bare link with no auth would let anyone who intercepts/forwards the
  email approve on the real owner's behalf.
- **No email notification capability exists.** The original ask
  envisioned owners approving via a link in an email; nothing in this
  repo sends email today - would need an SMTP/mail-gateway integration
  plus a decision on trigger points (ticket created? each pending
  owner reminded on a schedule?).
- **No frontend deep-linking to a specific ticket** - approvals today
  only happen through the Approvals list UI, not a standalone URL a
  human could land on from an email link. Needed together with the two
  points above to actually realize the original "approve via email link"
  flow end-to-end.
- Camunda REST auth: `_auth()` in `camunda_client.py` supports HTTP Basic
  auth (the standard Camunda 7 approach via a servlet filter) but this is
  **unconfirmed against the company's real instance** - verify once
  reachable and adjust if it uses something else (e.g. an API key
  header, or Keycloak-fronted OAuth like Camunda 8 would have needed).
- DataHub field mapping assumes `maturity_level`/`data_quality_score`/etc.
  live as DataHub *customProperties* (confirmed assumption with the
  user) under `dataset.properties.customProperties` — the exact nesting
  for the `Dataset` type specifically wasn't confirmable from the docs
  fetched, only the general customProperties pattern across entity
  types. Check the query in `datahub_client.py` against your instance's
  GraphQL schema explorer (usually `{DATAHUB_API_URL}/api/graphiql`) and
  adjust if it doesn't match.
- **LLM client's OpenAI-compatible assumption is now confirmed working
  against a real endpoint (2026-07-28)** - tested against the user's own
  local Ollama (`http://host.docker.internal:11434/v1`, from inside the
  Docker container - note `localhost` inside the container is the
  container itself, not the host Mac, so `host.docker.internal` is
  required for this specific local-dev setup, not a company-gateway
  concern). Ollama's `/v1/chat/completions` streams the exact
  `data: {"choices":[{"delta":{"content":...}}]}` /
  `data: [DONE]` shape `llm_client.py` already expects - real reply text
  streamed correctly end-to-end through the Discover UI. Still
  unconfirmed: whether the real company on-prem gateway matches this
  same shape (Ollama is one concrete OpenAI-compatible implementation,
  not proof every on-prem gateway looks the same).
- **Found and fixed a real reliability gap in the semantic-layer SQL
  prompt** (`build_sql_prompt()` in `chat.py`) while testing against
  Ollama: the LLM would sometimes paste the user's entire sentence into
  a single `ILIKE '%...%'` pattern (which a short catalog description
  will essentially never contain as a substring) and sometimes emit a
  non-standard function-call form (`ilike(col, pattern)`) instead of the
  standard operator form. Fixed by explicitly instructing the model to
  extract 2-4 keywords first and giving a concrete example of the
  expected operator syntax. **Still not fully reliable with small local
  models** - repeated testing with `qwen2.5:latest` (7B) after the fix
  showed roughly 2/3 correct (right product matched, sometimes with one
  extra false-positive product included) and 1/3 reverting to "no match"
  even when the free-text reply correctly named the right product;
  `qwen3:14b` (14B) showed the same false-positive pattern and was
  noticeably slower. This mirrors exactly what the sibling
  `agent_mem0_poc` repo's README already documented about small local
  models struggling with strict structured-output tasks - not a bug
  specific to this integration, a known limitation of testing against
  small local models rather than a properly-sized production LLM. Revisit
  reliability once pointed at the real company gateway; if it's also a
  small/local model in production, the semantic-layer verification step
  may need a retry-on-empty or a stricter SQL validation pass before
  trusting an empty result over a text match that already looks correct.
- **Added a second, separately-configurable model for the SQL-generation
  step** (`LLM_SQL_MODEL` in `.env`, `settings.llm_sql_model` in
  `config.py`, threaded through `stream_chat_completion(messages, model=...)`
  in `llm_client.py`) - lets `chat.py`'s prose reply and its SQL-writing
  call use different models, on the theory that a tool-calling-tuned
  model would be more reliable at the strict SQL syntax than a general
  chat model. Blank (default) means "use `llm_model` for everything",
  unchanged from before this setting existed.
  **Tested against `llama3-groq-tool-use:8b` (tool-calling-tuned, ranks
  well on the Berkeley Function Calling Leaderboard) vs. `qwen2.5:latest`
  (general chat) for this specific step - no clear reliability
  improvement observed** in repeated local testing; both landed around
  the same ~50-65% correct rate. Diagnosed two concrete causes, neither
  fixed by model choice alone:
  1. **Traditional vs. Simplified Chinese mismatch** - the model
     sometimes extracts a Simplified Chinese keyword (e.g. `产能`) for a
     Traditional-Chinese catalog (`產能`); Postgres `ILIKE` does no
     script folding, so this silently never matched. **Fixed
     (2026-07-28):** relying on a prompt instruction to preserve script
     was correctly judged not reliable enough for a small local model
     (Qwen's training data leans Simplified regardless of instructions) -
     instead added `DataProduct.search_text` (`db.py`), a denormalized
     `name + description + tables_joined` blob stored in **both** scripts
     (`wrenai_client._search_text()`, using the pure-Python
     `opencc-python-reimplemented` package, `t2s` config - no native/Rust
     build step, installs cleanly). `build_sql_prompt()` now tells the
     LLM to match only against `search_text`, in whichever script it
     wants - confirmed via repeated testing that this also incidentally
     fixed the non-standard `ilike(col, pattern)` function-call syntax
     issue (a single column to match against seems to be a simpler
     pattern for the model to get the operator syntax right on too).
  2. **Overly generic extracted keywords** - e.g. extracting `客戶`
     ("customer") alone matches most catalog entries, since most of them
     mention a customer somewhere. **Not fixed** - still observed after
     the `search_text` change (repeated testing: correct product matched
     in most runs, but often with one extra unrelated product included
     via an overly generic keyword). This is a precision problem in
     keyword *specificity*, orthogonal to the script-matching fix above -
     the prompt already asks for a "specific enough" keyword but a small
     local model doesn't reliably judge that.
  Net result after both rounds of fixes: the two-model split
  (`LLM_SQL_MODEL`) is a reasonable thing to keep but wasn't the fix; the
  `search_text` dual-script column measurably improved things (no longer
  silently missing an obviously-correct match) but false-positive extra
  products from overly generic keywords remain a known, unresolved
  limitation of small local models for this step - revisit once pointed
  at the real company LLM gateway.

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

## Security review (2026-07-30) and fixes applied

A user-requested "is this ready to go live" review found this API had
**zero authentication anywhere** (critical) and three real,
`dangerouslySetInnerHTML`-based XSS vectors in the frontend (high) - both
fixed same-day. Also verified, empirically rather than assumed, that
WrenAI's governed SQL execution already structurally blocks destructive
SQL - see below.

**API key auth (interim measure, not a full fix):**
`backend/app/main.py`'s `require_api_key` gates every `/api/*` route
(via an `APIRouter(dependencies=[Depends(require_api_key)])`, so a route
added later is protected by default) behind an `X-API-Key` header,
checked against `settings.api_key` (`API_KEY` in `backend/.env`). Empty
(the default) disables the check entirely, matching this repo's existing
"empty = disabled" convention for optional integrations - **a real value
must be set before any real deployment**. `/health` stays unauthenticated
on purpose (status checks shouldn't need a secret).
Frontend: `frontend/src/api.js` sends the key via `VITE_API_KEY`, which
Vite bakes into the built JS **at image-build time** (not read at
container startup like the backend's `.env`) - wired through
`frontend/Dockerfile`'s `ARG VITE_API_KEY` and `docker-compose.yml`'s
`build.args`, sourced from the repo-root `.env` (see `.env.example`).
Verified end-to-end against the real running stack: rebuilt both images
with a real key set, confirmed direct backend requests without the
header get `401`, requests through the frontend's nginx proxy without
the header also get `401`, and the key literally baked into the built JS
bundle (`grep`'d for it in the built `dist/assets/*.js`) makes both
succeed. Then reverted back to the disabled default and reconfirmed
everything works exactly as before.
**Explicitly does NOT fix**: `submit_approval()`'s separate gap (nothing
verifies the caller actually *is* the `owner_email` they claim in the
request body) - this is a single shared secret, not per-user identity,
so it stops anonymous/external traffic but not an insider impersonating
a different owner. Closing that properly needs real per-user auth
(company SSO/OIDC), not attempted here.

**XSS fixes:** three `dangerouslySetInnerHTML` sites rendered
attacker-influenceable content as raw HTML with no sanitization -
`DiscoverView.jsx`'s `note` (raw LLM/local-match reply text),
`CopilotDock.jsx`'s user-typed message echoed straight back as HTML, and
`CopilotDock.jsx`'s streamed bot answer. All three now render as plain
text (React's default auto-escaping) instead. This required a matching
backend change: `chat.py`'s `GREETING_REPLY` and `local_rule_match()`'s
templated reply used to contain literal `<b>`/`<br>` tags (intentional,
developer-authored formatting) - these are now plain text too (`\n`
instead of `<br>`, no bold), since the frontend no longer renders any
reply as HTML at all - restoring the exact same one-off formatting
safely wasn't worth the added protocol complexity for two words of bold
and a line break. `frontend/src/App.css`'s `.assistant-note`/
`.copilot-answer` gained `white-space: pre-wrap` so the greeting's `\n`
still shows as a real line break without needing HTML.

**Verified (not assumed) that WrenAI's governed SQL execution already
blocks destructive queries** - relevant because `chat.py`'s
`resolve_via_semantic_layer()` lets an LLM write SQL from user input, so
a prompt-injection attack asking the model to write a `DROP`/`DELETE`
is a real threat model to check, not a hypothetical. Tested directly
against the real running engine: `DROP TABLE tickets` /
`DELETE FROM tickets` fail immediately at the planning stage (`tickets`
isn't a declared MDL model, only `data_products` is); `DELETE FROM
data_products` (a declared model) reports success but is silently
transpiled into a read-only probe query - confirmed by checking
Postgres's actual row count before and after execution: unchanged (3
rows), nothing was actually deleted. This is a real, structural guardrail
already built into the engine, not something this session added.
**Recommended (not yet done) defense-in-depth**: give WrenAI's own
Postgres connection a genuinely read-only DB role, separate from the
app's own read-write role for `tickets`/`approvals` - so this protection
doesn't depend solely on WrenAI's software behavior staying correct
across future version upgrades.

**Flagged but not yet acted on** (lower priority than the two fixes
above, see the review discussion for full detail):
- No rate limiting on `/api/chat` - combined with (now-mitigated, not
  eliminated) unauthenticated access, a resource-exhaustion/LLM-cost risk.
- No request body schema validation (`main.py` uses raw
  `await request.json()` + dict indexing, not Pydantic models) - no
  length caps on `objective`/`purpose`/chat `message`.
- Both Dockerfiles run as root (no `USER` directive) - standard hardening
  gap, not yet closed.
- `backend/requirements.txt` has no version pins - reproducibility/
  dependency-vulnerability-tracking gap.
- No `.dockerignore` in either `backend/` or `frontend/`.
- No schema migration tool (`init_db()` is still a bare `create_all`) -
  a real gap for evolving the schema post-launch without data loss.
- CORS origin and TLS termination need explicit confirmation/config at
  actual deployment time, not just left at their local-dev defaults.

## General search / AI search toggle (2026-07-31)

Added a Google "AI Mode"-style toggle on the Discover search box (not the
Copilot dock, which stays inherently conversational) - user-requested
after noticing not everyone wants natural-language search; some just
want literal keyword search. Two modes, persisted in `localStorage`
(`dgo_search_mode`) as a durable per-user preference, not a per-query
setting - defaults to **keyword** (general search first, matching the
Google pattern the user described):

- **`mode=keyword`** (default): `chat.py`'s new `keyword_search()` -
  plain `ILIKE` substring matching against `data_products.search_text`,
  multiple keywords (split on whitespace) all required to match (AND).
  No LLM/WrenAI call at all - `run_chat()` yields a single `final` SSE
  event immediately, no `step`/`token` events.
- **`mode=ai`**: the existing LLM + WrenAI semantic-layer chain,
  unchanged.

**Why plain `ILIKE` AND, not Postgres full-text search** (`tsvector`/
`to_tsquery`), even though the latter has native multi-keyword AND
support: confirmed this catalog's Chinese content has no whitespace
between words, so Postgres's default text-search parser can't tokenize
it into sub-string-matchable words the way `ILIKE` naturally does -
`to_tsvector` would treat an entire Chinese phrase as one token. Proper
CJK-aware full-text search needs an extra extension (`zhparser`, not
built-in) - unjustified complexity at this catalog's size (a few dozen
rows at most), where a bare sequential scan is sub-millisecond anyway.

**English input** was a related question the user raised: `search_text`
already contains the catalog's English fields (`name`, `tables_joined`)
verbatim, so an English keyword that literally appears in that text
(e.g. "capacity") already works with zero extra effort - confirmed via a
live test (`curl .../api/chat` with `mode: "keyword"`, message
`"capacity"`, returned the correct single match). What does *not* work,
by design: an English word whose only match is a *different-language
concept* in the catalog (e.g. "capacity" needing to match a
description that only says "產能", not "capacity") - this is a
translation problem, not a script-folding one (unlike Traditional/
Simplified, which OpenCC handles mechanically), so it's out of scope for
keyword mode; a query like that is what AI mode is for. Decided not to
build a bilingual synonym/glossary table for this - not worth the
maintenance burden until a real, specific term gap shows up in practice.

Verified end-to-end against the real running app (real DataHub-sourced
catalog, not mocks): a two-keyword AND query, a single Chinese keyword
matching two catalog entries, a no-match query, and confirmed omitting
`mode` entirely still defaults to the old AI-mode behavior (greeting
fast-path included) - no regression for existing callers.

## Greeting detection fix + tightened prompt (2026-07-31)

**Bug found via user testing**: "hi how are you?" got the zero-
hallucination "no data subject matches your request" reply instead of a
greeting - reproduced and root-caused against the real running app
before fixing. `is_greeting()`'s old heuristic was `len(cleaned) <= 12
and any(greeting word in cleaned)` - "hi how are you" is 14 characters
after punctuation-stripping, one accidental character-count away from
the arbitrary 12-char cutoff, so it fell through to the full LLM +
WrenAI pipeline, which then (correctly, for what it was given) found
nothing in the catalog matching "how are you" and reported zero
hallucination as designed.

**Fix**: replaced the length cutoff with a word-composition check -
`is_greeting()` now returns true if every whitespace-separated word in
the message is either part of a `GREETING_WORDS` phrase or one of a new
`CHITCHAT_WORDS` set (how/are/you/doing/today/etc.), no matter how long
the sentence spells it out. Chinese, having no whitespace between words,
gets a separate `CHITCHAT_PHRASES_ZH` exact-match set (你好嗎, 最近好嗎,
etc.) instead of word-splitting. Verified this doesn't reopen the
original problem the length cutoff was guarding against (a real request
that happens to start with a greeting word, e.g. "hi, I want to look at
customer capacity data", must NOT get short-circuited to the canned
greeting) - both a live curl test and a new parametrized pytest case
cover this specifically.

**Follow-up same day**: user immediately hit a second case - "hi how r
u?" (texting shorthand) still fell through, since `r`/`u` weren't in
`CHITCHAT_WORDS`. Added `r`, `u`, `ur`, `hru` to the set; verified
against the real running app.

**Also, per user feedback**: `GREETING_REPLY` now acknowledges "how are
you"-style small talk before explaining capability with a concrete
example query (previously just "I'm your Assistant, describe your
need" - fine for a bare "hi" but gave a first-time user no example of
what to actually type). And `build_prompt()`'s `[Role]` section now
explicitly frames every request through "this tool exists to help you
find data subject(s) for a report" rather than a generic "data
governance expert" framing - the user's stated reasoning: every use of
this tool is fundamentally about finding data to complete a report, so
saying that plainly up front should help the LLM interpret ambiguous or
terse requests better.

**Tried and reverted same day: LLM-based 3-way classification.** To also
catch greetings that slip past `is_greeting()`'s keyword check (new
phrasing, another language), `build_prompt()` was extended to a 3-way
decision - greeting / no-match / match - with `run_chat()` detecting a
"greeting" classification via markers in the reply and short-circuiting
before the WrenAI call. **Live-tested against the real local model
(qwen2.5) and found unreliable**: it correctly caught the intended case
("what's going on today") but also misclassified genuinely off-topic,
non-greeting messages ("what is the weather like today", "please tell
me a joke") as greetings - confirmed via direct curl tests, not
assumed. Consistent with this repo's other documented small-model
limitations (see the SQL-generation keyword-precision notes above) -
adding a 3rd category gave a weak model more room to conflate things
that were fine to distinguish under a plain 2-way decision.

**Reverted to a plain 2-way `build_prompt()`** (match / no-match, same
as originally) and removed the greeting-marker short-circuit from
`run_chat()`. `is_greeting()`'s keyword check remains the *only* thing
that catches greetings - no LLM involved in that decision anymore.
`NOT_FOUND_REPLY` absorbed the "here's how to ask, with an example"
guidance instead (same spirit as `GREETING_REPLY`), so it reads as
helpful regardless of *why* nothing matched - off-topic, a real but
uncataloged need, or a rare greeting that slipped through.

**Added instead: offline, human-in-the-loop query mining.** Every
`run_chat()` "no match" (both the semantic-layer-confirmed case and the
text-marker fallback case) now logs the raw message via
`chat.py`'s `record_unmatched_query()` into a new `unmatched_queries`
table (`db.py`'s `UnmatchedQuery` - `message`, `lang`, `created_at`,
`reviewed`). `backend/scripts/review_unmatched_queries.py` periodically
sends unreviewed rows to the LLM as a batch, asking it to flag which
look like greetings/chit-chat and suggest keywords - printed for a
**human** to read and decide whether to actually add to
`GREETING_WORDS`/`CHITCHAT_WORDS`/`CHITCHAT_PHRASES_ZH`, never applied
automatically. This sidesteps the exact reliability problem just found:
the same small model's judgment is fine here because a human is the
final filter, not the request path. Verified end-to-end against the
real running app: logged two genuinely off-topic messages, ran the
script against real Postgres + real Ollama, got back suggestions
(which, honestly, also mislabeled "weather"/"joke" as greetings - the
LLM's classification skill didn't improve just by moving it offline,
but the point of this design is that it doesn't need to: a human reads
the output before anything takes effect), confirmed rows got marked
`reviewed` and weren't resurfaced on a second run.

## Getting Camunda + Postgres into the office network (2026-08-04)

First real office test surfaced a new constraint: the company's internal
registries (Harbor, Nexus) don't mirror everything from Docker Hub -
specifically, no Camunda image - and the company's own PostgreSQL is a
heavyweight, centrally-managed HA offering, not something to casually
point a dev docker-compose stack at. **Confirmed the office network can
reach `ghcr.io` itself**, even though it can't reach Docker Hub directly
- the same path already proven for `backend`/`frontend` (see the GHCR
publish work earlier in this file) turns out to generalize to any
third-party image, not just the ones this repo builds itself.

**`scripts/mirror-image-to-ghcr.sh`** does the generic version of that:
pull a public image at home, retag it under this repo's GHCR namespace,
push it - a straight retag/push, not a rebuild, so nothing about how
these images are configured changes (env vars/volumes in
`docker-compose.yml`, same as always - mirroring an image is not the
same thing as baking config into one, a distinction worth being explicit
about since it came up as a real question this session). Both
`docker-compose.yml`'s `camunda` and `postgres` services now reference
`ghcr.io/mail2yee/...` instead of the public Docker Hub names.

**Camunda**: self-hosting via this mirrored image is the actual
long-term plan, not a stand-in - the company has no Camunda service to
prefer instead.

**Postgres is different, and deliberately scoped as a dev-environment
choice, not a production one**: the company already has a managed HA
Postgres service. Self-hosting a plain `postgres:16-alpine` container
(mirrored the same way) is fine for a personal/team dev environment -
raised and specifically confirmed with the user that this is what's
being set up here, not a shared/production system, so the usual
"don't route around the company's managed DB service" concern doesn't
apply yet. **Revisit before any shared or production deployment**
(including the eventual K8s move - `k8s/` is still just a placeholder):
point `DATABASE_URL` at the company's real Postgres instead (no code
change needed, this app's config already supports that swap) rather
than trying to run a self-hosted Postgres Pod in K8s. On that specific
K8s question, raised and answered directly: mirroring the image to GHCR
has no bearing on Kubernetes storage handling either way (a Postgres
container's data was already separated from the image via a volume
mount, both in `docker-compose.yml` today and in whatever K8s manifest
would eventually exist - `StatefulSet` + `PersistentVolumeClaim` is the
correct K8s pattern for a self-hosted Postgres, regardless of which
registry the image comes from) - but the *operational* burden of
running your own HA/backups/patching in K8s is real and is itself
another reason to prefer the company's managed service once this goes
beyond a personal dev environment. Camunda doesn't have the same
concern in the same way - its durable state lives in whatever database
it's pointed at, not on local Pod disk, so it doesn't need its own PVC
the way Postgres does.

## Self-hosted images with a config fallback (2026-08-05)

User-directed architecture change: Camunda, DataHub, and Postgres should
all be "self-hosted by default via image; if the image can't be pulled,
fall back to whatever CAMUNDA_BASE_URL/DATAHUB_API_URL is already set to
in `backend/.env`" (Postgres excepted - no fallback, self-hosting it is
mandatory, see the section above). `deploy.sh` (new, repo root) is the
single entry point that implements this decision.

**DataHub moved into this repo's own docker-compose stack**, reversing
the earlier design (a separate, host-level `datahub docker quickstart`
shared with the sibling `agent_mem0_poc` repo - see this file's git
history). The user explicitly chose this over keeping it separate, aware
of the consequence: DataHub isn't one image, it's **7** -
`datahub-gms`, `datahub-frontend-react`, `datahub-actions`,
`datahub-upgrade` (all `acryldata/*:v1.5.0.6`), `mysql:8.2`,
`opensearchproject/opensearch:2.19.3`, `confluentinc/cp-kafka:8.0.0` -
all now mirrored to `ghcr.io/mail2yee/...` the same way Camunda/Postgres
already were. `datahub/docker-compose.datahub.yml` is adapted from
DataHub's own official quickstart compose file (fetched via `datahub
docker quickstart`, pinned to v1.5.0.6 - not hand-written), with
`profiles:` stripped (upstream gates most services behind a `quickstart`
profile; this repo wants `docker compose up` alone to always bring them
up) and host ports shifted (18080/19002/19092/13306/19200) to avoid
clashing with the old shared instance if it's still running during the
transition. Two consequences worth remembering:
- This repo no longer shares a DataHub instance with `agent_mem0_poc` -
  each now runs its own. Running both simultaneously on one dev machine
  is genuinely heavy (OpenSearch + Kafka + MySQL + GMS, twice over).
- `datahub/seed_catalog.py` / `scripts/setup-datahub.sh` (the old
  separate-stack tooling) still work as documented, just now point at
  this repo's own DataHub instance (`localhost:18080`) rather than the
  shared one at `localhost:8080`.

**`docker-compose.yml` was split** so Camunda/DataHub can be cleanly
absent: the `camunda` service and its `backend: depends_on: camunda`
moved to `docker-compose.camunda.yml`; DataHub's 7 services plus an
additive `backend` override (`DATAHUB_API_URL`, `depends_on:
datahub-gms-quickstart`) live in `datahub/docker-compose.datahub.yml`.
Neither is referenced by the base `docker-compose.yml` at all anymore -
confirmed via `docker compose config` that omitting both overlay files
leaves `backend`'s `CAMUNDA_BASE_URL`/`DATAHUB_API_URL` exactly as set in
`backend/.env` (env_file), with no override fighting it. This is the
actual mechanism behind "falls back to config" - `deploy.sh` doesn't
need to know anything about company endpoints, it just decides whether
to hand Compose an extra `-f` file or not.

**`deploy.sh`** (repo root): copies `.env`/`backend/.env` from the
`.example` files if missing, then for each of Camunda and DataHub tries
`docker compose pull` for just that service (or all 7, for DataHub) -
success includes the overlay file and self-hosts it, failure skips the
overlay and prints a reminder to point `backend/.env` at the company's
real instance. Postgres is a hard failure if unpullable, no skip option.
Brings everything up with one `docker compose -f ... up -d` at the end.

**Two real bugs found building and testing this, neither hypothetical:**
1. **Pull-before-build silently clobbered fresh local work.** The first
   `deploy.sh` draft tried `docker compose pull backend frontend` before
   falling back to `docker compose build` - this is backwards from the
   already-established office/home workflow (README's Step 2/3 always
   tries build first). Caught it empirically: after a first full
   `deploy.sh` run, a test ticket came back with a **Zeebe/Camunda-8 gRPC
   connection error** - `camunda_client.py` was rewritten for Camunda 7
   REST weeks ago, so this could only mean the pull had silently
   overwritten the fresh local backend image with a stale one already
   sitting on `ghcr.io` from before that rewrite, with no error at all
   (the pull just succeeds against whatever's already published). Fixed
   by reversing the order: build first (fails cleanly without PyPI/npm
   access, e.g. at the office), pull only as the fallback.
2. **GHCR auth expired silently across a whole batch push.** Mirroring
   all 7 DataHub images ran as one background job; the completion
   summary reported success, but reading the actual log showed **every
   one of the 7 pushes failed with 403 Forbidden** (logged out of
   `ghcr.io` from earlier anonymous-pull testing, never logged back in
   before starting this batch). The pulls all succeeded first (each
   verified `amd64/linux`), so nothing was lost - re-ran just the pushes
   after logging in again. Consistent with this session's established
   habit of reading full command output rather than trusting a reported
   exit code, especially for a multi-step shell loop where one failing
   step doesn't necessarily fail the whole batch's own exit code.

**LLM default switched to `qwen3:14b`** (from `qwen2.5:latest`) in
`backend/.env` per user request - confirmed already pulled locally via
`ollama list`, and confirmed both the greeting fast-path (unaffected,
keyword-only) and a real AI-mode search still work correctly with it
(no stray `<think>`-style reasoning tokens leaking into the parsed
reply - a real risk with newer "thinking" models, checked rather than
assumed).

## Vulnerability remediation round (2026-08-06)

User took the mirrored images to the office; the company's scanner
flagged all of them and refused to run them. Installed `trivy` (Docker
Scout needs a Docker Hub login, not viable) and scanned every mirrored
image for real (`trivy image --image-src remote <image>` - scanning the
local Docker daemon's cache fails for these multi-platform pulls with
"unable to get uncompressed layer"). **Mirroring itself introduces zero
CVEs** - it's a byte-for-byte retag/push, no rebuild - these are all
upstream's own baked-in vulnerabilities.

Baseline (CRITICAL/HIGH counts):

| Image | Critical | High |
|---|---|---|
| postgres:16-alpine | 1 | 14 |
| camunda-bpm-platform:7.22.0 | 5 | 32 |
| mysql:8.2 | 4 | 134 |
| opensearch:2.19.3 | 6 | 286 |
| cp-kafka:8.0.0 | 1 | 92 |
| datahub-gms/frontend/upgrade:v1.5.0.6 | 0 each | 77/73/81 |
| datahub-actions:v1.5.0.6-slim | 2 | 51 |

User's direction: check for newer patch versions before anything else
(not "ask IT for an exception", not "drop self-hosting"). Then, after
seeing patch-level results, explicitly pushed for trying **higher**
(not just patch) versions too. Findings, all from real `trivy` scans of
the actual candidate tags (not guessed):

- **mysql: `8.2` -> `8.4.9` (adopted).** `8.2` is a MySQL "Innovation"
  release (short support window, already has zero further patch tags -
  confirmed via the Docker Hub API) - this is *why* it was stuck at 4
  critical/134 high, not bad luck. `8.4` is the current LTS track:
  1 critical/40 high. Went further and scanned `9.7.2` (1 critical/**20**
  high, better still) - but **live-tested it and it fails to boot**:
  `--default-authentication-plugin=caching_sha2_password` (used in
  `datahub/docker-compose.datahub.yml`'s mysql `command:`) was removed
  as of MySQL 8.4 (`unknown variable` error, container aborts). Fixed by
  dropping the flag entirely - it's been the default auth plugin since
  8.0, so removing it changes nothing. Went with **`8.4.9`** over `9.7.2`
  per user's choice: 9.x is itself another Innovation track (same
  short-lifespan problem `8.2` had), 8.4 LTS trades a few more CVEs for
  not having to repeat this whole exercise in a few months.
- **cp-kafka: `8.0.0` -> `8.3.0` (adopted, latest available).**
  0 critical/17 high, down from 1 critical/92 high. Live-tested: Kafka
  itself works fine, but the healthcheck (`nc -z broker 9092`) started
  failing - the `8.3.0` base image dropped `netcat` entirely (confirmed:
  `nc: command not found`, exit 127, even though the broker was actually
  up and answering on its real port). Fixed by switching the healthcheck
  to `kafka-broker-api-versions --bootstrap-server broker:29092`.
- **opensearch: `2.19.3` -> `2.19.6` (adopted, NOT `3.x`).**
  1 critical/81 high, down from 6 critical/286 high. `3.8.0` scanned even
  better (0 critical/24 high) but **live-tested against DataHub
  v1.5.0.6's actual GMS and it hard-fails at startup** -
  `SearchClientShimFactory` throws `Unable to detect search engine
  type... OpenSearch: connected but version='3.8.0' (expected 2.x)`.
  This isn't caution, it's a confirmed incompatibility: v1.5.0.6 only
  speaks OpenSearch 2.x. Staying on `2.19.6` (the latest available patch
  in the 2.19.x line) until/unless DataHub itself is upgraded past what
  supports OpenSearch 3.
- **camunda: `7.22.0` stays.** No patch tags exist for `7.22.0` itself;
  the only newer options are different minor versions (`7.23.0`,
  `7.24.0`), and `7.24.0` scanned *worse* (6 critical/39 high vs the
  current 5/32) - not just unhelpful but a regression. Also out of scope
  to change unilaterally: the company specifically confirmed running
  7.22. No version-based remediation available for Camunda.
- **postgres: `16-alpine` stays.** Already resolves to the latest
  available 16.x/alpine patch combination - no newer tag to move to.
- **DataHub's 4 images: `v1.5.0.6` stays.** `v1.6.0` exists and is
  pullable, but scanned nearly identical (gms/frontend/upgrade: exactly
  the same counts; actions: 51->47 high, marginal) for real compatibility
  risk against a compose file that's been hand-adapted and verified
  against `v1.5.0.6` specifically. Not worth it.

**Net effect after adopting mysql:8.4.9 / opensearch:2.19.6 /
cp-kafka:8.3.0**: a real, meaningful drop in CVE counts across the
board, confirmed by live-testing every substituted image against the
actual compose stack (not just scanned in isolation) - but **not
zero**. Camunda alone still carries 5 critical/32 high with no
available fix, and DataHub's 4 images still total roughly 280 high
between them. If the office's scanner is a hard gate (any
critical/high blocks the image outright, not just a warning), version
selection alone will not get this stack under that bar - the
unresolved question is whether the user pursues an IT/security
exception process next, since "reconsider which services need
self-hosting" was explicitly not the direction chosen.

The three new images were re-mirrored to `ghcr.io/mail2yee/...`
(`mysql:8.4.9`, `opensearch:2.19.6`, `cp-kafka:8.3.0`) the same way as
before - confirmed `amd64/linux`, confirmed anonymous pull works (all
already public since they're new tags under already-public
repositories, no visibility flip needed this time).

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
- **Bug + coverage review (2026-07-29):** ran `pytest --cov=app` (new
  `pytest-cov` dev dependency) to actually check test completeness
  instead of relying on impression. Found and fixed one real bug:
  `wrenai_client.py`'s `sync_catalog()`/`_search_text()` used
  `item.get(field, "")`, whose default only applies when a key is
  *missing* - a key present with value `None` (plausible for a real,
  unset DataHub customProperty) produced the literal string `"None"` via
  `str(None)`, silently polluting `search_text` and the stored field.
  Fixed with a `_field()` helper (`item.get(field) or ""`); regression
  test added. Also closed several real coverage gaps: `_extract_sql()`'s
  markdown-fence stripping was never tested despite real LLMs actually
  triggering it; two `run_chat()` double-failure edge cases (no LLM +
  no local keyword match; semantic-layer failure + text-fallback also
  says no match) weren't verified to still report zero-hallucination
  correctly; `/api/catalog` and `/api/chat` had zero direct HTTP-level
  test coverage (every test either called `run_chat()` directly or hit
  `/api/catalog` only as a ticket-creation side effect); `llm_client.py`
  was 18% covered - its real SSE-parsing logic had never been exercised,
  only ever mocked out by callers, now covered via `httpx.MockTransport`
  (no new dependency). Coverage went 78% → 86% overall,
  `chat.py`/`llm_client.py` now 100%. Remaining gaps are documented in
  `backend/README.md`'s testing section as either genuinely hard to
  close without live infra (Camunda OAuth, DataHub's real GraphQL
  parsing, WrenAI's real engine execution) or a `coverage.py`
  measurement artifact with async SQLAlchemy/FastAPI's `lifespan`, not
  real gaps.
- Backend: a real pytest suite exists now (`backend/tests/`, 60 tests as
  of the coverage review above, see `backend/README.md` for how to run it)
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
- **Backend: added a DeepEval-based eval suite** (`backend/evals/`,
  separate from `backend/tests/` - see `backend/README.md`'s "Evals"
  section for how to run it) to replace the ad-hoc "run the same query a
  few times and eyeball it" testing this session was otherwise doing
  manually. Confirmed DeepEval (still the dominant pytest-native LLM eval
  framework as of 2026) supports a local Ollama model as the LLM judge
  directly - no OpenAI key needed, consistent with everything else in
  this repo being built for an air-gapped network. Metrics: a hard,
  non-judged structural assertion (matched products must be real catalog
  ids - regression guard on WrenAI's governance), plus judge-scored
  Faithfulness, Answer Relevancy, and a custom `GEval` "recommendation
  precision" metric against a small golden-query set (in-catalog zh/en +
  out-of-catalog zero-hallucination cases). **Ran it for real** against
  the actual Docker Compose stack + local Ollama: results varied
  0.50-1.00 pass rate across the 6 golden queries, consistent with (not
  contradicting) the keyword-precision limitation already documented
  above - this is meant as a repeatable signal to catch regressions, not
  a claim that today's reliability is good enough; see the deliberately
  low `PASS_RATE_FLOOR` in `evals/test_chat_eval.py` and its comment.

**Not done yet (next up):**
- CI - intentionally NOT GitHub Actions. Company uses internal CI/CD
  (Azure DevOps) - pipeline should be built there when that's next up,
  not `.github/workflows/`.
- **Point both the app and the eval suite at the company's real on-prem
  LLM gateway, at the office.** Everything LLM-related so far (the
  OpenAI-compatible shape confirmation, the `search_text`/keyword-
  precision fixes, the DeepEval eval suite) was tested against a local
  Ollama - useful for proving the mechanisms work, but the actual
  numbers (matching reliability, eval pass rates) are expected to
  change against the real gateway, which is the actual point of doing
  this. Two separate places to point, not one:
  1. The app itself: `backend/.env`'s `LLM_BASE_URL`/`LLM_MODEL`/
     `LLM_API_KEY` (and optionally `LLM_SQL_MODEL`) - see that file's
     comments in `.env.example`.
  2. The eval judge: `DGO_EVAL_JUDGE_MODEL`/`DGO_EVAL_JUDGE_BASE_URL`/
     `DGO_EVAL_JUDGE_API_KEY` when running `pytest evals/` - see
     `backend/README.md`'s "Evals" section. Uses DeepEval's `LocalModel`
     (generic OpenAI-compatible client, confirmed working
     2026-07-28 against local Ollama with no Ollama-specific package
     needed) so the same three env vars work for either a local model or
     the real gateway - only the values change.
  Record whatever the eval suite finds in `backend/evals/EVAL_LOG.md`
  once run against the real thing - that's the actually useful number,
  more than anything measured against a local Ollama stand-in.

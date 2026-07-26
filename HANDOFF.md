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
| Semantic layer (NL -> structured query) | N/A | Not in scope for v1. WrenAI was mentioned as a possible future addition if DataHub metadata alone isn't enough for this — don't build anything for it yet |
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
Google Material-inspired design — the user explicitly approved this
direction; don't relitigate it, port it:

- **Layout:** top app bar + collapsible left nav rail (groups toggle via
  a chevron) + main content area. Not a single split-screen layout.
- **Color:** light theme by default **regardless of OS
  `prefers-color-scheme`** (explicit user requirement) with a manual
  toggle to dark. Google Blue accent (`#1a73e8` light / `#8ab4f8` dark),
  neutral backgrounds tinted toward the accent (not pure grey), semantic
  colors (success/warning/critical) kept separate from the accent hue.
- **Type:** "Google Sans"/Roboto-first font stack with system fallbacks,
  monospace for IDs/data values/timestamps.
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

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
| Workflow engine | Camunda SaaS (`login.cloud.camunda.io`), fire-and-forget, not really wired to approval state | Camunda **self-managed** (on-prem) — intent is to actually drive the approval BPMN process this time, not simulate it (see `backend/app/integrations/camunda_client.py`) |
| Data catalog | Dataplex (GCP) | DataHub API (see `backend/app/integrations/datahub_client.py`) — until this is wired, the app falls back to the same hardcoded `LOCAL_CATALOG` mock data as the GCP PoC |
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
this in plain HTML/CSS/JS (`app/main.py`'s `index()` route) — read it for
exact copy, exact CSS values, and exact interaction behavior when
building the React version, rather than re-deriving the design from this
summary alone.

## What's actually in this repo right now

Scaffolding only — a skeleton that's structured correctly and (once
`.env` is filled in and `docker compose up` is run) should boot, but the
integrations are stubs and the frontend is not yet a port of the PoC's
UI. See each side's own README for what's implemented vs. TODO.

# Frontend

React + Vite. See `../HANDOFF.md` for the UI/UX direction this should be
built out to match (the GCP PoC repo has a full working reference
implementation of the design in plain HTML/CSS/JS to read from).

## Local dev (without Docker)

```bash
cd frontend
npm install
npm run dev
```

Needs the backend running separately on `:8000` (see `../backend/README.md`)
— `vite.config.js` proxies `/api` and `/health` to it, so no CORS setup is
needed for local dev.

## What's actually here right now

A full port of the PoC's UI, verified working end-to-end against the
real backend (see the root README's status section):

- `src/index.css` — design tokens (light-by-default theme, Google Blue
  accent, dark variant).
- `src/App.css` — everything else, ported class-for-class from the PoC's
  `<style>` block, so diffing against it stays easy.
- `src/i18n.js` — zh/en translation dictionary (ported verbatim).
- `src/api.js` — backend calls, including `streamChat()`, the SSE
  consumer for `/api/chat` (reads `step`/`token`/`final` events and
  renders progressively rather than waiting for one response).
- `src/components/` — one file per UI piece: `TopBar`, `NavRail`
  (collapsible groups), `DiscoverView` (search + live streaming +
  reasoning-steps disclosure), `ProductCard`, `ApprovalsView` (SLA strip
  + ticket list), `TicketRow` (expandable, approve/reject), `CartBar`,
  `SubmitDialog`, `ConnectionCodeDialog`, `CopilotDock`, `Toast`.
- `src/App.jsx` — top-level state (lang, theme, cart, catalog, tickets,
  dialogs) and wiring between components.

Not built: the "目錄維護"/Catalog Admin screen (was a disabled
placeholder in the PoC too, no design exists for it yet).

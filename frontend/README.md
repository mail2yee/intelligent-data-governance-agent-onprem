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

A connectivity-proving skeleton (`src/App.jsx`), not a port of the PoC's
Discover / Approvals / Copilot screens yet:

- Design tokens (`src/index.css`) ported from the PoC (light-by-default
  theme, Google Blue accent, etc.)
- A minimal shell that fetches `/health` and `/api/catalog` and renders
  the catalog as cards, to prove the whole pipeline (React -> proxy ->
  FastAPI -> DataHub-stub) actually works.

Next real work: build out the Discover search (with the SSE streaming
consumption pattern - see the PoC's `streamChat()` for the exact event
shapes: `step`/`token`/`final`), the Approvals list, cart/submit flow,
and the Copilot dock, as React components using these same tokens.

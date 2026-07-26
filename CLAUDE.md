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
- The two repos are **intentionally separate, no shared code**.
- Stack: FastAPI + PostgreSQL backend, React + Vite frontend, real
  Camunda (pyzeebe/gRPC) and DataHub (GraphQL) integrations with
  graceful fallback to mocks on failure.
- Backend: `ruff` + `mypy` clean, 36 pytest tests. Frontend: `oxlint`
  clean, 29 vitest tests. Both suites pass.
- CI: intentionally NOT GitHub Actions — company uses internal Azure
  DevOps for CI/CD. Don't build `.github/workflows/`.
- Workflow: user develops with Claude Code at home, pulls via git at
  the (air-gapped) office to test — no Claude Code access there.

Full detail, open items, and the "not done yet" list live in
`HANDOFF.md` — don't duplicate them here; update that file instead.

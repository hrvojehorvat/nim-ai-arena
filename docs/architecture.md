# Architecture & Decisions

## Layout
```
backend/   FastAPI app (uv project, non-packaged; `app/` package)
frontend/  Vite + vanilla TS client (added in 1.5)
docs/      architecture decisions + roadmap
```

## Decisions log

### 0.1 Bootstrap (2026-11-07)
- **Monorepo, `backend/` as its own uv project.** Keeps Python and Node toolchains separate; all
  backend commands run from `backend/`.
- **Non-packaged uv app (`package = false`).** Simple `app/` import path for uvicorn
  (`app.main:app`), no build backend needed.
- **Tooling:** pytest + `httpx2` (Starlette's TestClient backend), ruff for lint/format.
- **Planned build order** (per CLAUDE.md): turn-based game loop → PostgreSQL → LangGraph agents.
  First agent is deterministic (nim-sum) LangGraph; Anthropic Claude LLM agent comes later.
- **Local DB:** docker-compose Postgres (from Phase 2); Azure only at deploy time.

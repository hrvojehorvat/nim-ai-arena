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

### 1.1 Pure Nim engine (2026-11-08)
- **`app/game/engine.py` is pure:** frozen dataclasses + functions, no I/O or async. Easy to test
  exhaustively and reuse for replay (Phase 2) and agent simulation (Phase 3).
- **Immutable state:** `apply_move` returns a new `GameState`; each `Move` stores `piles_after`,
  so history is self-describing and replayable from the initial config.
- **Stable error codes:** `IllegalMoveError.reason` (`game_over`, `not_your_turn`,
  `invalid_pile`, `invalid_count`) so WS/HTTP clients and agents can react programmatically.
- **Limits:** 1–20 piles, 0–100 stones each, ≥1 non-empty pile, ≥2 players with unique ids.
- **Turn order:** round-robin by seat index; supports N players already (strategy optimality for
  N>2 is an agent concern, not an engine one).
- **Domain vs API models:** engine uses dataclasses; Pydantic models will live at the API layer
  (1.2) and convert at the boundary.

### 1.2 Match manager + HTTP API (2026-11-08)
- **`MatchManager` (in-memory dict)** owns match lifecycle; the engine still owns the rules. A
  `Match` wraps an immutable `GameState` that is swapped only after a successful `apply_move`.
- **Lifecycle:** `waiting` (until every seat has joined) → `active` → `finished` (derived from
  state, not stored separately, so it can't drift).
- **`submit_move` is the single entry point for moves** (HTTP now, WS in 1.3, agents in 3.2),
  guarded by a per-match `asyncio.Lock` to serialize concurrent submissions.
- **No auth yet:** `player_id` in the body identifies the player. Fine for local dev; seat tokens
  are a later concern.
- **Errors:** uniform `{reason, message}` body. 404 not found, 409 for state conflicts
  (`not_your_turn`, `game_over`, `not_started`, `already_joined`), 422 for bad input
  (`invalid_config`, `invalid_pile`, `invalid_count`), 403 `unknown_player`.
- **`create_app()` factory** with the manager on `app.state` → each test gets a fresh app.

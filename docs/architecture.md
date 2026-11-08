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

### 1.3 WebSocket game loop (2026-11-08)
- **`WS /ws/matches/{id}?player=<id>`**; connecting = join (or reconnect, seat is kept on
  disconnect). No `player` param = spectator (read-only), useful for watching agent matches later.
- **Protocol:** client sends `{"type":"move","pile","count"}`; server sends full `state` snapshots
  (not diffs; small payloads, idempotent clients), `game_over` after the final state, and
  `error {reason, message}` to the sender only. Rejections close with 4404 / 4403.
- **Broadcast via `MatchManager(on_change=...)`**, invoked *inside* the per-match lock, so
  broadcasts are strictly ordered and HTTP moves reach WS clients too. Manager stays I/O-free
  (it only knows a callback); `ws.Hub` owns sockets.
- **Tradeoff:** a slow socket delays the broadcast (and holds the match lock) because sends are
  awaited sequentially. Fine at current scale; revisit with per-socket send queues if needed.
- **Tests** use `with TestClient(app)` so all HTTP/WS calls share one event loop.

### 1.3b Board limits + `max_take` variant (2026-11-08)
- **Limits lowered to 10 piles × 30 stones** so the whole board is displayable and countable in
  the UI (stones rendered in groups of 5; 10 per line on narrow screens).
- **`GameConfig.max_take`** (optional, ≥1): max stones removable per move. `None` = standard Nim.
  No upper bound: a value above a pile's size just allows taking the whole pile. Part of the
  config, so it is stored with the match and replays honor it.
- **Strategy impact:** this is a subtraction game; optimal play uses Grundy values
  `pile % (max_take + 1)` XOR-ed together, which equals nim-sum when unlimited.
- **Frontend direction:** 1.5 uses DOM elements (CSS-styled stone buttons) for the board; Canvas
  remains the Phase 6 target for animation. Pending user confirmation vs. Canvas-first.

### 1.4 Turn timeouts (2026-11-08)
- **Per-match `turn_timeout` (seconds, optional, ≤3600)** lives on `Match`, not `GameConfig`:
  it's a match/runtime setting, not a rule of Nim. Default `None` = no limit.
- **Policy: auto-move only.** On expiry the server plays `engine.default_move` (1 stone from the
  first non-empty pile) for the current player through the normal `apply_move` path and
  broadcasts it. Games always terminate (stones strictly decrease).
- **Forfeit deferred to Phase 4:** with N>2 players it needs elimination rules (turn skipping,
  winner when one remains, history/replay representation). Not worth designing for 2 players only.
- **Timer mechanics:** one `asyncio.Task` per active match, (re)started under the match lock after
  join-to-active and after every move; cancelled on game end and on app shutdown (lifespan).
  The task re-checks `len(moves)` under the lock so a move landing right at expiry can't trigger
  a double move.
- **Auto moves are tracked** in `Match.auto_moves` (move indices) and exposed as `moves[].auto`;
  the engine's `Move` stays rule-only. Phase 2 must persist this flag.
- **Clients get `turn_time_left`** (seconds, computed at serialization) rather than an absolute
  deadline → no client/server clock-skew issues; client counts down from receipt.

### 1.5 Vite + TypeScript client (2026-11-08)
- **Vanilla TS, no framework.** A 20-line `h()` helper builds DOM nodes; all user text goes
  through `textContent` (no `innerHTML`). Each WS `state` message re-renders the view from
  scratch: the server snapshot is the only state, so there's nothing to reconcile.
- **Hash routing:** `#/` setup, `#/match/<id>/<player>` play a seat, `#/match/<id>` spectate.
  One tab per seat for local human-vs-human testing.
- **Vite dev proxy** forwards `/matches`, `/health`, `/ws` to `:8000` → single origin, no CORS.
- **Board = DOM buttons** (CSS circles) in groups of 5, exactly 10 per line (30 stones = 3 lines),
  on desktop and phone. Hover/focus a stone → highlights it and every stone to its right, capped
  at `max_take` (`selectionCount` in `board.ts`); click sends that move. Illegal selections are
  impossible in the UI, but the server still validates everything. Buttons give keyboard/focus
  support for free; Canvas stays the Phase 6 target for animation.
- **Countdown** uses `turn_time_left` + `performance.now()` at receipt (no clock skew).
- **Reconnect:** non-fatal WS close → retry every 1.5s (seat is kept server-side); 4403/4404 are
  shown as permanent errors.
- **Types are hand-mirrored** from `schemas.py` in `src/types.ts` (small surface; revisit with
  OpenAPI codegen if the API grows).

### 2.1 DB infrastructure (2026-11-08)
- **Postgres 16 via `docker-compose.yml`** (user/password/db all `nim`/`nim`/`nim_arena`, local dev
  only, named volume `pgdata`). Azure replaces it in Phase 7 by changing `DATABASE_URL` only.
- **DB is optional:** with `DATABASE_URL` unset the app runs in memory exactly as before. Keeps
  Phase 1 tests and quick local runs DB-free. Run with a DB via
  `uv run uvicorn app.main:app --reload --env-file backend/.env` (copy `.env.example`).
  Tradeoff: two modes to keep working; 2.2 must not assume a pool exists.
- **`app/db/pool.py`:** `create_pool` (asyncpg, 1–5 connections) opened/closed in the FastAPI
  lifespan, migrations run at startup. `create_app(database_url=...)` overrides the env var (tests).
- **Migrations: plain `backend/migrations/NNNN_name.sql`**, applied in filename order, each in its
  own transaction with its `schema_migrations` row (a failure leaves no partial change and is
  retried next start). A Postgres advisory lock serializes concurrent starts. No down-migrations,
  no checksums, no Alembic (per "no over-engineering"); revisit if the schema churns.
- **`/health` now reports `db`:** `disabled` | `ok` | `down` (status `degraded`).
- **Tests:** DB tests use a throwaway `nim_arena_test` database (dropped/recreated per test) and
  skip when Postgres is unreachable; a conftest fixture clears `DATABASE_URL` so a developer's
  shell can't leak into unrelated tests.

### 2.2 Match history schema + write-through (2026-11-08)
- **Three tables** (`migrations/0001_match_history.sql`):
  - `matches`: `config` JSONB = the rules needed to replay (`piles`, `max_take`), plus
    `turn_timeout`, `status`, `winner_id`, `created_at`, `finished_at`. `turn_timeout` is a column,
    not part of `config`, because it isn't a rule of Nim.
  - `match_players`: one row per seat (`seat` = turn order), so "games by player" queries (4.2
    stats) don't need to unpick JSON.
  - `moves`: `(match_id, turn_no)` key, `pile`, `count`, `piles_after int[]`, `auto` (timeout move).
  - Replay = `config` + `match_players` + ordered `moves`; `piles_after` lets the UI show any step
    without re-running the engine, and lets tests cross-check against it (2.3).
- **Persist before apply.** `MatchManager._apply` validates with the engine, saves the move
  (insert + match status/winner in one transaction), and only then swaps the in-memory state and
  broadcasts. If saving fails the move is rejected (`storage_error`, HTTP 503) and nothing changes,
  so memory never gets ahead of the DB. The same applies to creating a match and to the final join
  that activates it. Tradeoff: a DB outage stops play instead of silently losing history.
- **Timeout moves** go through the same `_apply`; if saving one fails it's logged and retried
  after another timeout period, so the game doesn't stall without a timer.
- **`MatchStore` protocol** in `game/match.py` (`NullMatchStore` for in-memory mode,
  `PgMatchStore` in `db/matches.py`). The manager never imports asyncpg.
  `MatchManager.create` became async because it now saves.
- **Restart = abandoned.** Live matches exist only in memory, so on startup any `waiting`/`active`
  rows are marked `abandoned`. Resuming in-progress matches after a restart is out of scope; the
  abandoned status keeps history honest and is easy to filter.
- **Joins are not persisted** (only the waiting→active status change): who has connected is live
  session state, not history.
- **Known gap:** match ids are 12 hex chars (48 bits). A collision would surface as a
  `storage_error` on create; negligible at this scale.
- **Tests:** DB fixtures moved to `conftest.py`; `FailingStore` tests need no database.

## 2.3 History & replay API

- **Two read-only routes:** `GET /matches?limit=&offset=` (summaries, newest first, limit 1–100,
  default 20) and `GET /matches/{id}/replay` (setup + players + ordered moves with `piles_after`).
  Replay also works for unfinished/abandoned matches.
- **Separate read side:** `db/history.py` (`PgMatchHistory`) is independent of `MatchStore`, which
  stays write-only. History reads come from the DB, never from live in-memory matches, so
  `GET /matches/{id}` (live state) and `/replay` (saved record) are deliberately different things.
- **No DB → 503 `history_unavailable`** (`app.state.history` is None). DB read failures map to
  503 `storage_error`.
- The replay is read in one `REPEATABLE READ` transaction so match, players and moves are consistent
  while a game is still being played.
- **Test:** a replay is rebuilt from the API output alone and re-run through the engine; every
  `piles_after` and the winner must match.
- **Known gap:** list has no filters (by status/player) and uses offset pagination; fine at this
  scale.

## 2.4 Replay viewer in the UI

- **Two new hash routes:** `#/history` (paged table, 20 per page, "Replay" link per row) and
  `#/replay/<id>` (step buttons, ←/→ keys, clickable move list). Header gets a History link.
- **Replay reuses `renderBoard` with `canMove: false`.** Each step just picks `initial_piles` or
  `moves[step-1].piles_after` from the API response; the browser never re-runs game rules.
- `api.ts` got a shared `request<T>()` helper so error handling ({reason,message} / Pydantic
  detail) is in one place. `MatchStatus` now includes `abandoned`.
- Replay and live views are separate on purpose; live matches are not auto-linked to replay yet.
- No automated frontend tests (consistent with 1.5); checked via typecheck/build and headless
  Chrome screenshots against a real DB.

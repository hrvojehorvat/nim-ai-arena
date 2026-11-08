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
- **Limits:** 1–20 piles, 0–100 stones each, ≥1 non-empty pile, exactly 2 players with unique ids.
- **Turn order:** seats alternate (implemented as round-robin by seat index, so N players is a
  small extension later; see "Two players only" below).
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

## Rule options: last stone loses and explicit "no time limit"

- **`GameConfig.last_stone_loses: bool = False`.** In last stone loses the player who takes the last stone loses. The
  engine still has a single `winner_id`, so the winner is the *next player in turn order* (i.e. the
  opponent). `current_player_index` stays on the winner, as before.
- Stored in `matches.config` JSONB (no migration needed); rows saved before this change read as
  `last_stone_loses=false` via `config.get("last_stone_loses", False)`. Exposed in match, list and replay responses.
- **Strategy impact for 3.1:** last stone loses Nim differs from normal play only near the end (when every
  pile is size ≤ 1 the parity flips). The agent must handle it; with `max_take` set, last stone loses
  needs its own brute-force/Grundy-based table. Tests will cover both.
- **No time limit** was already `turn_timeout = null` in the API; the setup form's seconds field now
  defaults to empty (placeholder "unlimited"); empty or 0 means no limit. The checkbox was dropped.

## 3.1 Deterministic LangGraph agent

- **Layout:** `agents/base.py` (the `Agent` protocol + `AgentMove(pile, count, reasoning)`),
  `agents/strategy.py` (pure maths, no LangGraph), `agents/nim_optimal.py` (the `StateGraph`).
  LLM agents (Phase 5) implement the same `choose_move(state, player_id)` protocol.
- **Graph:** `evaluate_state → compute_strategy → select_move → validate_move → END`, with
  `validate_move → fallback_move → END` when the move is illegal. `validate_move` dry-runs the
  engine's `apply_move`, so a maths bug can't produce an illegal move. No retry loop: the agent is
  deterministic, so retrying would repeat the same answer.
- **Strategy:**
  - standard rules: XOR of pile values; value = `pile % (max_take+1)` (just `pile` if unlimited).
  - last stone loses, unlimited: normal Nim, except near the end (all piles ≤1, or one big pile)
    where the parity of single stones decides. Brute force caught the naive version taking the whole
    of a lone pile.
  - last stone loses + `max_take`: exact memoised search capped at 50k positions
    (`SEARCH_BUDGET`); beyond that, falls back to normal-play maths and says so in the reasoning.
  - losing position: take 1 from the biggest pile to prolong the game.
- **Tests (`test_agent.py`):** an independent brute-force solver covers every board of ≤3 piles of
  0–5 stones for max_take ∈ {none,1,2,3} × both rule sets: the evaluation matches the solver and the
  agent always leaves a losing position when a winning move exists.
- **Known limitations:** the search is CPU
  work, so 3.2 must run agents off the event loop (thread) so a slow search can't stall the server.
- `pyproject.toml` ignores a Python 3.14 DeprecationWarning from langsmith (a langgraph dependency).
  Running pytest with `-W error` now fails at import because of it; use plain `uv run pytest`.

## 3.2 Agents in the match loop

- **Seats:** `PlayerSpec.kind` is `"human"` or a registered agent name (`nim_optimal`). Agent seats
  are pre-joined at create time, so an all-agent match starts at once. Unknown kinds → 422
  `unknown_agent`. `MatchManager(agents={...})` is the registry (wired in `main.py`).
- **One move path:** human, agent and timeout moves all go through `_apply` (validate → persist →
  apply → notify). Clients submitting for an agent seat get 403 `agent_seat`.
- **Agent task:** `_begin_turn` restarts the turn timer and starts `_run_agent` when the current seat
  is an agent. The agent thinks without the lock, then re-checks (still active, same turn) under the
  lock before applying. The turn timeout still applies, so a stuck agent gets an auto-move.
- **Failure handling:** crash or illegal proposal → server plays `default_move` with `auto=True` and
  a reasoning text saying so. Storage failure → retry the same turn after `AGENT_RETRY_DELAY` (1 s).
- **Reasoning:** migration `0002` adds `moves.reasoning`. Agent moves store the graph's text;
  timeout moves store "Timed out, so the server played…". Humans give none. Exposed in match state
  and replay, and shown under each move in the live log and replay viewer.

## 3.3 Seat selection in the UI

- Each setup seat has a Human / Agent dropdown (agent list hard-coded in `setup.ts` for now).
- One human + agents → the UI jumps straight to that seat; all agents → spectate; 2+ humans → one
  link per human seat. No auth yet: the seat is the URL, so a "player sees only their screen" model
  needs per-seat tokens later (Nim has no hidden info, so this is access control, not secrecy).

## Two players only (decision after 3.3)

- `GameConfig` now requires exactly 2 players (`NUM_PLAYERS`); the API returns 422 otherwise. The
  setup form has two fixed seats. Removed: the add/remove-player UI, the "not optimal with 3+
  players" note in agent reasoning, and the 3-player tests.
- Why: nim-sum strategy only means something for two players, and N-player needs elimination /
  forfeit rules that nothing requires yet. Idea parked for later (see roadmap).
- Kept deliberately: round-robin turn indexing and the seat-based data model, so lifting the limit
  later means new rules, not a rewrite.

## Agent move delay

- `MatchManager(agent_move_delay=...)` sleeps before each agent move is applied (after thinking,
  before the lock), so agent-vs-agent games are watchable. `main.py` reads `AGENT_MOVE_DELAY`
  (seconds, default 1.5; 0 = instant) as the default. Each match can override it with
  `agent_move_delay` in `POST /matches` (setup form field, empty = default), so you can switch
  between watching and fast runs without restarting. Tests force 0 via `conftest.py`. It also applies to the
  agent's reply in human-vs-agent games, which doubles as a natural "thinking" pause. The turn
  timeout clock keeps running during the pause.

## 4.3 Random baseline agent

- `agents/random_agent.py`: `pick_random_move → validate_move → (fallback_move)`, a LangGraph graph
  that reuses the optimal agent's `validate_move`/`fallback_move` nodes and `AgentState`. Picks a
  random non-empty pile, then a random legal count (respects `max_take`). Optional seed.
- Registered as `random` in `main.py` and the setup form's seat dropdown. Reasoning: "Random: took
  N from pile P."

## 4.2 Headless arena

- `app/arena.py` (`uv run python -m app.arena --a nim_optimal --b random --games 200 --piles 3,4,5
  [--max-take N] [--last-stone-loses] [--seed S]`). Plays the engine and agents directly: no server,
  DB or delay, ~200 games in a few seconds. Agents are validated by `apply_move`, so a cheating
  agent raises instead of silently winning.
- Seats alternate (A moves first in even games), and the table shows win rate overall and wins when
  moving first, since the first mover decides most Nim games.
- `agents/registry.py` (`build_agents(seed)`) is now the single list of agent kinds, used by the
  server and the arena. The frontend dropdown list is still hard-coded in `setup.ts`.
- Not done on purpose: storing arena results in the DB or an HTTP endpoint (nothing needs them yet).

## 5.1 Agent catalog

- `GET /agents` returns `[{name, description}]` for every agent registered in the `MatchManager`
  (sorted by name). Each agent has a one-line `description` (part of the `Agent` protocol).
- The setup form no longer hard-codes agent names: it fetches the list after first paint, fills each
  seat's dropdown (description as tooltip) and keeps the user's pick. If the fetch fails, only
  Human is offered and an error is shown. The Vite dev proxy forwards `/agents`.
- Later subphases register LLM agents only when their key/URL is configured, so the dropdown shows
  exactly what can really play.

## 5.2 First model call
- `app/agents/llm.py` holds `AgentDecision` (pydantic: reasoning, pile, count; piles 1-based like the UI)
  and the `LlmProvider` base class (`DEFAULT_MODEL`, `make()` -> `BaseChatModel`).
- `app/agents/anthropic_llm.py`: `AnthropicProvider` subclass (default `claude-haiku-5-5`, key from
  `ANTHROPIC_API_KEY`). A Modal/Ollama provider (5.6) is just another subclass with its own default model.
- Graph nodes will only depend on LangChain's `BaseChatModel`, so providers are swappable factories.
- Structured output goes through `with_structured_output(AgentDecision)`. Note: forced tool choice is
  rejected by some newer Claude models, so the method may need to switch to native JSON schema (check in 5.4).
- The notebook loads `backend/.env` with python-dotenv. Tests use no network.

## Modal-hosted open model (early 5.6)
- `deploy/modal_vllm.py` deploys Qwen2.5-7B-Instruct with vLLM on a Modal L4 (scales to zero, bearer key
  from a Modal secret). It needs the CUDA devel image (nvcc) or vLLM's FlashInfer sampler crashes.
- `app/agents/openai_compat_llm.py`: `OpenAICompatProvider(LlmProvider)` wraps `ChatOpenAI(base_url=...)`;
  URL/key from `MODAL_LLM_URL` / `MODAL_LLM_API_KEY`. Same class will serve Ollama/OpenRouter later.
- Gotcha (vLLM + `json_schema` structured output): if the prompt never mentions JSON, the model can emit
  endless whitespace under the guided decoder and hit the token limit (`LengthFinishReasonError`).
  The prompt must say "answer with a JSON object with keys ..." (5.3 prompt builder must include this).
  Small models also play Nim badly without help, which is the point of comparing them in the arena.

## LLM catalog and Ollama
- `app/agents/ollama_llm.py`: `OllamaProvider` = OpenAI-compatible provider with local defaults
  (`http://localhost:11434/v1`, override with `OLLAMA_URL`).
- `app/agents/llm_catalog.py`: named LLMs (`claude_haiku`, `modal_qwen7b`, `ollama_qwen2_1_5b`,
  `ollama_phi3_mini`), built lazily. Each name becomes a selectable agent in 5.4/5.5.
- Observed: tiny Ollama models ignore strict structured output. smollm2:135m adds chatter ("Here is the
  JSON object..."), qwen2:1.5b wraps the JSON in ```json fences, so `with_structured_output` raises a
  ValidationError. 5.3 therefore parses the plain-text reply tolerantly (strip fences, take the first
  `{...}`), validates it, and the 5.4 graph retries/falls back.

## 5.3 Prompt builder and reply parsing
- `app/agents/prompt.py` is pure (no network, no LangChain): `build_system_prompt` (rules, JSON-only
  instruction), `build_user_prompt` (1-based piles, per-pile limits, last 20 moves from the player's
  view), `build_retry_prompt` (feeds an error back), `parse_decision` (first JSON object in the reply,
  tolerates fences/chatter/string numbers, raises `ReplyParseError` with a message fit for the model),
  `to_agent_move` (1-based -> 0-based). Legality is NOT checked here: the graph/engine validates.

## 5.4 LLM agent graph
- `app/agents/llm_agent.py`: `build_prompt -> llm_reason -> validate_move -> (retry_prompt -> llm_reason | fallback_move)`.
  Wrong answers (unparsable or illegal) go back to the model with the error, `MAX_RETRIES = 2`, then a safe
  legal move is played and the reasoning says so. Works with any `BaseChatModel`; tests use scripted fakes.
- Structured vs text: `LlmProvider.STRUCTURED_OUTPUT` is a *declared* capability (Anthropic and OpenAI-compatible/vLLM
  yes, Ollama no, since schema enforcement needs Ollama >= 0.5). Structured providers use `with_structured_output`
  and, if the server ignored the schema, rescue the raw text with `parse_decision`. Others use plain text +
  `parse_decision`. A capability can't be probed cheaply, so it is declared per provider and overridable
  (`structured=True`).
- Availability: `LlmProvider.unavailable_reason()` does cheap checks only (API key set, env URL set, Ollama reachable and
  model pulled). `build_agents(llms=True)` registers only available LLMs (others logged), so `GET /agents` and the
  dropdown list only agents that can run. Checked once at startup: start Ollama / set keys before the server.
  Tests set `NIM_LLMS=0` so they never probe localhost or need keys; the arena still uses non-LLM agents only (5.7).
- Observed live (Ollama, CPU): qwen2:1.5b answers in ~18 s with a legal move; phi3:mini (3.8B) in ~35 s with a
  legal (not optimal) move. smollm2:135m and tinyllama never produced usable JSON (always hit the fallback), so
  they were dropped from the catalog. Modal cold start can exceed 60 s.

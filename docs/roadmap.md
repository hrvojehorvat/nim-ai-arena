# Roadmap

Each subphase = one commit. Status: ✅ done · 🚧 in progress · ⬜ todo

## Phase 0 — Bootstrap
- ✅ 0.1 Repo scaffold: uv backend, `/health`, docs

## Phase 1 — Core game & turn-based loop (no DB, no AI)
- ✅ 1.1 Pure Nim engine (config, state, move validation, winner) + tests
- ✅ 1.2 In-memory MatchManager + HTTP API (create/get/move)
- ✅ 1.3 WebSocket game loop (broadcast state, turn enforcement)
- ✅ 1.3b Board limits 10 piles × 30 stones + `max_take` rule variant
- ✅ 1.4 Turn timeouts (auto-move policy; forfeit moved to 4.1)
- ✅ 1.5 Vite/TS client with DOM board (stones as buttons, groups of 5, hover-to-select capped
  at `max_take`, wraps at 10/line on narrow screens) — human vs human

## Phase 2 — Persistence (PostgreSQL)
- ✅ 2.1 docker-compose Postgres, asyncpg pool, SQL migration runner
- ⬜ 2.2 Schema (matches, match_players, moves) + write-through
- ⬜ 2.3 History & replay API
- ⬜ 2.4 Replay viewer in UI

## Phase 3 — LangGraph AI → Milestone 1: human vs agent
- ⬜ 3.1 Agent interface + deterministic StateGraph: Grundy values `pile % (max_take+1)`
  XOR-ed (reduces to plain nim-sum when unlimited); brute-force tests for both modes
- ⬜ 3.2 Agent runner in match loop (same validation path as humans)
- ⬜ 3.3 UI seat selection (human/agent) + agent move display

## Phase 4 — Multi-agent arena
- ⬜ 4.1 N-player matches + forfeit-on-timeout policy (elimination rules, recorded in history)
- ⬜ 4.2 Headless agent-vs-agent runs + win-rate stats
- ⬜ 4.3 Random baseline agent

## Phase 5 — LLM agent (Anthropic Claude)
- ⬜ 5.1 LLM StateGraph (prompt → reason → validate → retry → fallback)
- ⬜ 5.2 Hybrid tool-calling agent (nim_sum tool)
- ⬜ 5.3 Reasoning traces stored and shown in replay

## Phase 6 — Canvas renderer
- ⬜ 6.1 Canvas board with click-to-move
- ⬜ 6.2 Animations, turn highlight

## Phase 7 — Deployment (Azure)
- ⬜ 7.1 Dockerfile, static frontend
- ⬜ 7.2 Azure Postgres config + deploy README

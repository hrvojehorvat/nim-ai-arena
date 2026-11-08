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
- ✅ 2.2 Schema (matches, match_players, moves) + write-through
- ✅ 2.3 History & replay API
- ✅ 2.4 Replay viewer in UI

## Phase 3 — LangGraph AI → Milestone 1: human vs agent
- ✅ 3.1 Agent interface + deterministic StateGraph: Grundy values `pile % (max_take+1)`
  XOR-ed (reduces to plain nim-sum when unlimited); brute-force tests for both modes
- ✅ 3.2 Agent runner in match loop (same validation path as humans). Every agent move carries a
  human-readable `reasoning` string, stored in a new nullable `moves.reasoning` column (migration
  0002), returned in replay and shown live in the UI. Humans have none.
- ✅ 3.3 UI seat selection (human/agent per seat); one human vs agents opens that seat directly

## Phase 4 — Multi-agent arena
- ➖ 4.1 N-player matches + forfeit-on-timeout: dropped for now (two players only). Parked idea.
- ✅ 4.2 Headless agent-vs-agent runs + win-rate stats (CLI + notebook cell; no DB/HTTP yet)
- ✅ 4.3 Random baseline agent (done before 4.2 so the arena has a weak opponent)

## Phase 5 — LLM agents (LangChain chat models + LangGraph)
Decision: use LangChain chat models (`langchain-anthropic`, `langchain-openai`) behind one common
interface, so graph nodes don't care which provider answers. Each model is a named agent that any
seat can select (Claude vs GPT-OSS vs `nim_optimal`, ...). Keys/URLs live in `backend/.env`.
- ✅ 5.1 Agent catalog: `GET /agents` lists available agents; setup dropdown loads it (no LLM yet)
- ✅ 5.2 First model call: `langchain-anthropic` + `ANTHROPIC_API_KEY`; notebook cell gets structured
  `{pile, count, reasoning}` from a raw prompt (no graph)
- ✅ 5.3 Prompt builder + reply parsing: pure, tested functions (state + history → prompt)
- ✅ 5.4 LLM agent graph: `build_prompt → llm_reason → validate_move`, retries feed the error back,
  then the safe fallback. Fake chat models in tests. Playable in the UI.
- ⬜ 5.5 Model configuration: config file defines several named agents (Haiku, Sonnet, Opus) shown in
  the dropdown and usable in the arena
- ⬜ 5.6 OpenAI-compatible provider: `langchain-openai` `ChatOpenAI(base_url=...)` covers OpenAI,
  Modal (vLLM), Ollama, OpenRouter via config entries
- ⬜ 5.7 LLM arena runs: illegal-move/retry rates, latency, token use next to win rates
- ⬜ 5.8 Hybrid tool agent: LLM calls a `nim_sum` tool via a LangGraph tool node
- ⬜ 5.9 Richer traces: `moves.meta` JSON (model, tokens, latency, retries, tool calls) shown in replay

## Phase 6 — Canvas renderer
- ⬜ 6.1 Canvas board with click-to-move
- ⬜ 6.2 Animations, turn highlight

## Phase 7 — Deployment (Azure)
- ⬜ 7.1 Dockerfile, static frontend
- ⬜ 7.2 Azure Postgres config + deploy README

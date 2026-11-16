# Nim AI Arena

A turn-based multiplayer **Nim** platform where humans and **LangGraph-powered AI agents** play against
each other. It's a sandbox for comparing how different kinds of agents reason and pick moves: a
mathematically perfect strategy, a random baseline, and LLM agents with and without tools.

> **Nim in one line:** players take turns removing one or more stones from a single pile. In the
> standard game, whoever takes the last stone wins.

---

## Highlights

- **Configurable games:** any number of piles, any number of stones per pile, a max-take limit,
  "last stone wins" or "last stone loses" (misère), and an optional per-turn timeout.
- **Authoritative server:** clients only send *intent* (`pile`, `count`). The server validates every
  move, applies it, and broadcasts the new state over WebSocket. Humans and agents go through the
  **same validation path**, so agents get no shortcuts.
- **Pluggable AI agents:** each agent is an isolated LangGraph `StateGraph`.
  - `nim_optimal`: a deterministic nim-sum strategy. It never loses from a winning position.
  - `random`: a baseline.
  - **LLM agents:** Groq, Ollama (local), any OpenAI-compatible endpoint (e.g. vLLM on Modal), and
    Anthropic. You add them in a config file, with no code changes.
  - **Tool-using LLM agents:** the model calls a `nim_sum` tool before it decides.
  - Every LLM move has validation, retries, and a deterministic fallback, so an agent can't stall a
    game.
- **Canvas game board:** click a stone to take it and the ones above it. Moves are animated in each
  player's seat colour, and the agent's reasoning is shown next to its move.
- **History and replay:** every match (initial config, every move, the agents' reasoning) is stored in
  PostgreSQL and can be stepped through move by move.
- **Headless arena:** a CLI pits agents against each other over hundreds of games and reports win
  rates, with no server or DB needed.

## Architecture

```
 Browser (Vite + TypeScript, HTML5 Canvas)
        │  REST: create / join / history          WebSocket: live state, moves
        ▼
 FastAPI ──► MatchManager (turn order, timeouts) ──► Nim engine (pure, no I/O)
        │                    │
        │                    └──► Agent runner ──► LangGraph agents
        │                                          (optimal · random · LLM · LLM + tools)
        ▼
 PostgreSQL (asyncpg): matches, players, moves, reasoning traces
```

- **Engine** (`backend/app/game/engine.py`): immutable game config and state, move validation, and
  the win rules. Pure functions, fully unit-tested.
- **Match manager** (`backend/app/game/match.py`): seats, turn order, timeouts, and triggering agent
  turns. Live matches are held in memory, so one server instance owns its matches.
- **Agents** (`backend/app/agents/`): one LangGraph graph per agent type. LLM agents follow
  *build prompt → reason → validate → retry → fall back*.
- **Persistence** (`backend/app/db/`, `backend/migrations/`): plain SQL migrations, applied
  automatically on startup. If no database is configured, the app still runs with history disabled.

You can find design decisions and tradeoffs in [docs/architecture.md](docs/architecture.md).

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI (HTTP + WebSockets), asyncpg |
| AI | LangGraph, LangChain chat models (Groq, Ollama, OpenAI-compatible, Anthropic) |
| Database | PostgreSQL |
| Frontend | Vanilla TypeScript, HTML5 Canvas, Vite |
| Tooling | uv (Python), npm, pytest, vitest, ruff, Docker |

## Getting started

### Prerequisites
- [uv](https://docs.astral.sh/uv/), Node.js 20+, and Docker (for the local Postgres)

### 1. Database (optional, but you need it for history and replay)
```bash
docker compose up -d          # Postgres 16 on localhost:5432 (user/password/db: nim/nim/nim_arena)
```

### 2. Backend
```bash
cd backend
cp .env.example .env          # set DATABASE_URL; add LLM provider keys if you want LLM agents
uv sync
uv run uvicorn app.main:app --reload       # http://localhost:8000
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

Open the frontend, pick the piles and a rule, and set each seat to *human* or an agent. Then play.

### Or: everything in one container
```bash
docker build -t nim-arena .
docker run --rm -p 8000:8000 --env-file backend/.env nim-arena   # http://localhost:8000
```
The image builds the frontend and serves it from the backend, so it runs as a single origin.

## Configuration

Settings come from environment variables in `backend/.env`. That file is never committed; use
`.env.example` as the template.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string. Leave it empty to run without history. |
| `AGENT_MOVE_DELAY` | Seconds an agent waits before moving, so humans can follow the game. |
| `GROQ_API_KEY` | Enables the Groq-hosted LLM agents. |
| `MODAL_LLM_URL`, `MODAL_LLM_API_KEY` | Enables agents on an OpenAI-compatible endpoint (e.g. vLLM). |
| `ANTHROPIC_API_KEY` | Enables Claude agents. |

**LLM agents** are listed in [`backend/llm_agents.toml`](backend/llm_agents.toml). Each section is one
selectable agent: provider, model, and whether it uses tools. An agent only shows up when its provider
is reachable and configured. If you add a section and restart, the new agent is available.

## Using the API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness and DB status |
| `GET` | `/agents` | Available agent types |
| `GET` | `/defaults` | Server defaults (e.g. agent move delay) |
| `POST` | `/matches` | Create a match (piles, seats, rules, timeout) |
| `GET` | `/matches/{id}` | Current match state |
| `POST` | `/matches/{id}/join` | Take a human seat |
| `POST` | `/matches/{id}/moves` | Submit a move `{player_id, pile, count}` |
| `WS` | `/ws/matches/{id}` | Live state updates, plus submitting moves |
| `GET` | `/matches` | Match history |
| `GET` | `/matches/{id}/replay` | Initial config + ordered moves for replay |

Interactive API docs are at `http://localhost:8000/docs` while the server is running.

## Agent vs agent: the arena CLI

```bash
cd backend
uv run python -m app.arena --a nim_optimal --b random --games 200 --piles 3,4,5
uv run python -m app.arena --a groq_gpt_oss_120b_tools --b nim_optimal --games 20 --last-stone-loses
```
Options: `--a`, `--b` (agent types), `--games`, `--piles`, `--max-take`, `--last-stone-loses`, and
`--seed` (makes random agents repeatable).

## Tests

```bash
cd backend && uv run pytest -q          # engine, match loop, WebSocket, DB, agents, arena
cd frontend && npm test                 # board geometry (vitest)
```
Database tests use the local Postgres from `docker compose` and are skipped if it isn't running.

## Project structure

```
backend/
  app/
    game/        engine.py (rules), match.py (turns, timeouts, agent turns)
    agents/      LangGraph agents, LLM providers, nim_sum tool, registry
    db/          asyncpg pool, match and history repositories
    api.py       REST routes
    ws.py        WebSocket protocol
    arena.py     headless agent-vs-agent runner
    main.py      app factory (also serves the built frontend in Docker)
  migrations/    numbered SQL migrations
  llm_agents.toml
  tests/
frontend/
  src/           setup form, canvas board, match view, history/replay
deploy/          cloud deploy script
docs/            architecture, roadmap, deployment guide
Dockerfile       one image: built frontend + backend
docker-compose.yml   local Postgres
```

## Deployment

The app ships as **one Docker image**: the backend serves the built frontend. It runs as a **single
replica**, because live matches are kept in memory. Match history can use any managed PostgreSQL
(currently a free-tier Neon database). See [docs/deploy.md](docs/deploy.md).

## Roadmap

Phases 0–6 are done: game loop, persistence, LangGraph agents, LLM agents, and the canvas UI.
Deployment is in progress. Next up:

- **Accounts and user-defined agents:** sign-in, plus uploading or writing your own agent in the app
- **Responsive, full-screen UI**
- **MCP server:** let MCP clients (e.g. Claude) list agents, start matches, and play
- **N-player Nim**, persisted arena statistics
- **Tournaments and leagues:** knockout brackets and round-robin leagues with best-of-N matches

The full plan is in [docs/roadmap.md](docs/roadmap.md).

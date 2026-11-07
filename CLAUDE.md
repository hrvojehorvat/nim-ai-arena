# Nim AI Arena 

## Project Vision & Goal
A turn-based multiplayer implementation of the **Nim game**, designed as a multi-agent AI sandbox. The objective is to build a web platform where LangGraph-powered AI agents can compete against each other and against human players, optimizing for AI reasoning, strategic decision-making, and orchestration.

The game supports fully configurable Nim setups. Before starting a match, players can define:
- The number of piles.
- The initial number of stones in each pile.
- The number of players (humans and AI agents).

Each player takes turns selecting a pile and removing one or more stones from it. A player can only remove stones from a single pile per turn and cannot remove more stones than the pile contains.

The default game mode follows standard Nim rules: the player who removes the last stone wins.

## Tech Stack
*   **Backend:** Python 3.11+, FastAPI (WebSockets, HTTP), Asyncpg
*   **Package Manager:** uv (Astral's ultra-fast dependency manager and tool runtime)
*   **AI Engine:** LangGraph (StateGraph for multi-agent orchestration and decision loops)
*   **Database:** PostgreSQL (Azure-native, async match history storage)
*   **Frontend:** Vanilla TypeScript + HTML5 Canvas (Vite) - lightweight game board renderer

## Core Architecture Rules
*   **Authoritative Server:** The server manages the game state and validates every move. Clients (humans/agents) only submit their intended action (pile index and number of stones to remove); the server validates the move and broadcasts the updated state.
*   **Turn-Based Game Loop:** The game progresses in discrete turns. The next player can only act after the previous move has been validated and applied. The server manages turn order, player timeouts, and game completion.
*   **Configurable Game Setup:** Every match must support a configurable number of piles and an individual initial stone count for each pile. The initial configuration must be stored so matches can be replayed.
*   **LangGraph Orchestration:** Each AI agent is an isolated LangGraph state machine. It takes the current game state and match history as input, orchestrates reasoning nodes (e.g., state evaluation, Nim strategy calculation, move selection), and outputs a legal move.
*   **Game State Representation:** Represent the board as an array of piles, where each pile contains a non-negative integer representing its remaining stones. The server is the single source of truth.
*   **Vertical Slices First:** Start with a simple text-based representation of the piles. Avoid complex abstractions or unnecessary infrastructure. First milestone: 1 human vs. 1 LangGraph agent successfully playing a configurable Nim game.

## Development Process
1. **Inspect & Understand:** Check the existing game state structure, move validation, and WebSocket routes before typing code.
2. **Plan & Approve:** Pitch a short plan in chat before altering game state logic or LangGraph topologies.
3. **Incremental Execution:** Establish the turn-based game loop first, wire the DB second, layer the AI engine last.
4. **No Commits Without Review:** Implement a subphase, then stop. The user checks, runs and tests it. Only commit when the user explicitly says to commit.
5. **Hand-off Summary:** After each implementation, give a simple explanation of what was done, in logical order (what each piece is and how it fits), followed by exact commands to test, run and manually check it.
6. **No Over-engineering:** Favor simple vertical execution and local pattern consistency over infrastructure bloat.

## Continuous Improvement & Docs
At the end of every development session:
1. Review implemented slices and log architectural tradeoffs.
2. Update `docs/architecture.md` (decisions) and `docs/roadmap.md` (next sprints).
3. Modify `CLAUDE.md` **only** if a foundational rule or tech stack choice changes.

## Commands (Cheat Sheet)
*   `uv add fastapi uvicorn langgraph asyncpg` (Add backend packages via uv)
*   `uv run uvicorn app.main:app --reload` (Start backend development server securely via uv)
*   `npm run dev` (Start frontend development environment)
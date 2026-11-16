# Nim AI Arena

A web platform for playing **Nim** in which humans and **LangGraph-powered AI agents** compete against each other.

**Nim:** players take turns removing one or more stones from a single pile. Whoever takes the last stone wins.

## What it's for

It's a sandbox for comparing how different AI agents reason and decide:

- a perfect mathematical strategy (nim-sum)
- a random baseline
- LLM agents (Groq, Ollama, OpenAI-compatible endpoints, Claude), with or without a `nim_sum` tool

The server is authoritative and validates every move, whether a human or an agent makes it. You can configure each game's piles, stones and rules. Every match is stored, so you can replay it move by move along with the agents' reasoning. A CLI arena plays agents against each other over many games and compares their win rates.

**Stack:** Python, FastAPI (REST and WebSocket), LangGraph, PostgreSQL, TypeScript, Canvas and Vite.

## How to run

```bash
docker compose up -d                                 # local Postgres (optional, for history)

cd backend && cp .env.example .env                   # add LLM API keys if you want LLM agents
uv run uvicorn app.main:app --reload                 # http://localhost:8000

cd frontend && npm install && npm run dev            # http://localhost:5173
```

Or run everything as one container:

```bash
docker build -t nim-arena . && docker run --rm -p 8000:8000 --env-file backend/.env nim-arena
```

You'll find more detail in [docs/](docs/): architecture, roadmap and deployment.

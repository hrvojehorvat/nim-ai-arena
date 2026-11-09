import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import ws
from app.agents.registry import build_agents
from app.api import HistoryUnavailableError, error_response
from app.api import router as api_router
from app.db.history import PgMatchHistory
from app.db.matches import PgMatchStore
from app.db.pool import create_pool, database_url_from_env, run_migrations
from app.game.match import MatchManager

log = logging.getLogger(__name__)


def create_app(database_url: str | None = None) -> FastAPI:
    """`database_url` defaults to $DATABASE_URL; with neither set the app runs without a DB."""
    url = database_url or database_url_from_env()
    hub = ws.Hub()
    matches = MatchManager(
        on_change=hub.broadcast,
        agents=build_agents(llms=os.environ.get("NIM_LLMS", "1") != "0"),
        agent_move_delay=float(os.environ.get("AGENT_MOVE_DELAY", "1.5")),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool: asyncpg.Pool | None = None
        if url:
            pool = await create_pool(url)
            await run_migrations(pool)
            store = PgMatchStore(pool)
            abandoned = await store.abandon_unfinished()
            if abandoned:
                log.warning(
                    "marked %d unfinished match(es) from a previous run as abandoned", abandoned
                )
            matches.store = store
            app.state.history = PgMatchHistory(pool)
        app.state.db = pool
        try:
            yield
        finally:
            await matches.close()
            if pool is not None:
                await pool.close()

    app = FastAPI(title="Nim AI Arena", lifespan=lifespan)
    app.state.hub = hub
    app.state.matches = matches
    app.state.db = None
    app.state.history = None

    @app.exception_handler(HistoryUnavailableError)
    async def _history_unavailable(request: Request, exc: HistoryUnavailableError):
        return error_response(
            "history_unavailable", "match history needs a database (set DATABASE_URL)"
        )

    app.include_router(api_router)
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        pool: asyncpg.Pool | None = app.state.db
        if pool is None:
            return {"status": "ok", "db": "disabled"}
        try:
            await pool.fetchval("SELECT 1")
        except Exception:
            return {"status": "degraded", "db": "down"}
        return {"status": "ok", "db": "ok"}

    # Deployed (Docker image): serve the built frontend from the same origin. Mounted last, so
    # every API/WebSocket route above wins; the SPA uses hash routes, so "/" -> index.html is all.
    # Unset in development: Vite serves the frontend and proxies to us.
    frontend_dist = os.environ.get("FRONTEND_DIST")
    if frontend_dist:
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


# Server entry point (`uvicorn app.main:app`): read backend/.env (LLM keys/URLs, DATABASE_URL)
# the same way the arena CLI does. Variables already set in the shell win over the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
app = create_app()

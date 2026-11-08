import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request

from app import ws
from app.agents.nim_optimal import NimOptimalAgent
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
    matches = MatchManager(on_change=hub.broadcast, agents={"nim_optimal": NimOptimalAgent()})

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

    return app


app = create_app()

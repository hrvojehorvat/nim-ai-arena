from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import ws
from app.api import router as api_router
from app.game.match import MatchManager


def create_app() -> FastAPI:
    hub = ws.Hub()
    matches = MatchManager(on_change=hub.broadcast)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await matches.close()

    app = FastAPI(title="Nim AI Arena", lifespan=lifespan)
    app.state.hub = hub
    app.state.matches = matches
    app.include_router(api_router)
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

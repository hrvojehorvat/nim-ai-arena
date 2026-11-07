from fastapi import FastAPI

from app import ws
from app.api import router as api_router
from app.game.match import MatchManager


def create_app() -> FastAPI:
    app = FastAPI(title="Nim AI Arena")
    app.state.hub = ws.Hub()
    app.state.matches = MatchManager(on_change=app.state.hub.broadcast)
    app.include_router(api_router)
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

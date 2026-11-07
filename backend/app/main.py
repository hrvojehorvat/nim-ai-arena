from fastapi import FastAPI

from app.api import router
from app.game.match import MatchManager


def create_app() -> FastAPI:
    app = FastAPI(title="Nim AI Arena")
    app.state.matches = MatchManager()
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

"""HTTP routes for matches. All game logic lives in the engine / MatchManager."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.game.engine import IllegalMoveError, InvalidConfigError
from app.game.match import MatchError, MatchManager
from app.schemas import CreateMatchRequest, JoinRequest, MatchOut, MoveRequest

router = APIRouter()

STATUS_BY_REASON = {
    "match_not_found": 404,
    "invalid_config": 422,
    "unknown_player": 403,
    "already_joined": 409,
    "not_started": 409,
    "game_over": 409,
    "not_your_turn": 409,
    "invalid_pile": 422,
    "invalid_count": 422,
}


def error_response(reason: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS_BY_REASON.get(reason, 400),
        content={"reason": reason, "message": message},
    )


def get_manager(request: Request) -> MatchManager:
    return request.app.state.matches


Manager = Annotated[MatchManager, Depends(get_manager)]


@router.post("/matches", status_code=201, response_model=MatchOut)
async def create_match(body: CreateMatchRequest, manager: Manager):
    try:
        config = body.to_config()
    except InvalidConfigError as e:
        return error_response("invalid_config", str(e))
    return MatchOut.from_match(manager.create(config))


@router.get("/matches/{match_id}", response_model=MatchOut)
async def get_match(match_id: str, manager: Manager):
    try:
        return MatchOut.from_match(manager.get(match_id))
    except MatchError as e:
        return error_response(e.reason, str(e))


@router.post("/matches/{match_id}/join", response_model=MatchOut)
async def join_match(match_id: str, body: JoinRequest, manager: Manager):
    try:
        return MatchOut.from_match(await manager.join(match_id, body.player_id))
    except MatchError as e:
        return error_response(e.reason, str(e))


@router.post("/matches/{match_id}/moves", response_model=MatchOut)
async def submit_move(match_id: str, body: MoveRequest, manager: Manager):
    try:
        match = await manager.submit_move(match_id, body.player_id, body.pile, body.count)
    except (MatchError, IllegalMoveError) as e:
        return error_response(e.reason, str(e))
    return MatchOut.from_match(match)

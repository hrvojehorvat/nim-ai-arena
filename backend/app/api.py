"""HTTP routes for matches. All game logic lives in the engine / MatchManager."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.db.history import PgMatchHistory
from app.game.engine import IllegalMoveError, InvalidConfigError
from app.game.match import MatchError, MatchManager, StorageError
from app.schemas import (
    AgentOut,
    CreateMatchRequest,
    JoinRequest,
    MatchOut,
    MatchSummaryOut,
    MoveRequest,
    ReplayOut,
)

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
    "storage_error": 503,
    "history_unavailable": 503,
    "unknown_agent": 422,
    "agent_seat": 403,
}


def error_response(reason: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS_BY_REASON.get(reason, 400),
        content={"reason": reason, "message": message},
    )


def get_manager(request: Request) -> MatchManager:
    return request.app.state.matches


Manager = Annotated[MatchManager, Depends(get_manager)]


class HistoryUnavailableError(Exception):
    pass


def get_history(request: Request) -> PgMatchHistory:
    history: PgMatchHistory | None = request.app.state.history
    if history is None:
        raise HistoryUnavailableError
    return history


History = Annotated[PgMatchHistory, Depends(get_history)]


@router.post("/matches", status_code=201, response_model=MatchOut)
async def create_match(body: CreateMatchRequest, manager: Manager):
    try:
        config = body.to_config()
    except InvalidConfigError as e:
        return error_response("invalid_config", str(e))
    try:
        match = await manager.create(
            config, turn_timeout=body.turn_timeout, agent_move_delay=body.agent_move_delay
        )
    except MatchError as e:
        return error_response(e.reason, str(e))
    return MatchOut.from_match(match)


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(manager: Manager) -> list[AgentOut]:
    """Agents a seat can be assigned to (besides "human")."""
    return [
        AgentOut(name=name, description=agent.description)
        for name, agent in sorted(manager.agents.items())
    ]


@router.get("/matches", response_model=list[MatchSummaryOut])
async def list_matches(
    history: History,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Saved matches, newest first (requires the database)."""
    try:
        return await history.list_matches(limit, offset)
    except StorageError:
        return error_response("storage_error", "could not read from the database")


@router.get("/matches/{match_id}/replay", response_model=ReplayOut)
async def get_replay(match_id: str, history: History):
    """A saved match as setup + ordered moves. Also works for unfinished/abandoned matches."""
    try:
        replay = await history.get_replay(match_id)
    except StorageError:
        return error_response("storage_error", "could not read from the database")
    if replay is None:
        return error_response("match_not_found", f"match {match_id} not found")
    return replay


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

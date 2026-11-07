"""WebSocket game loop.

Protocol (JSON text frames):
  client -> server: {"type": "move", "pile": int, "count": int}
  server -> client: {"type": "state", "match": MatchOut}
                    {"type": "game_over", "winner_id": str}   (after the final state)
                    {"type": "error", "reason": str, "message": str}   (sender only)

Connect with `?player=<id>` to take (or reconnect to) a seat; without it you are a spectator.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, StrictInt, ValidationError

from app.game.engine import IllegalMoveError
from app.game.match import Match, MatchError, MatchManager
from app.schemas import MatchOut

router = APIRouter()

CLOSE_NOT_FOUND = 4404
CLOSE_FORBIDDEN = 4403


class MoveMessage(BaseModel):
    type: Literal["move"]
    pile: StrictInt
    count: StrictInt


def state_message(match: Match) -> dict:
    return {"type": "state", "match": MatchOut.from_match(match).model_dump(mode="json")}


def error_message(reason: str, message: str) -> dict:
    return {"type": "error", "reason": reason, "message": message}


class Hub:
    """Tracks open sockets per match and broadcasts state changes to them."""

    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)

    def add(self, match_id: str, ws: WebSocket) -> None:
        self._sockets[match_id].add(ws)

    def remove(self, match_id: str, ws: WebSocket) -> None:
        sockets = self._sockets.get(match_id)
        if sockets is not None:
            sockets.discard(ws)
            if not sockets:
                del self._sockets[match_id]

    async def broadcast(self, match: Match) -> None:
        messages = [state_message(match)]
        if match.state.is_over:
            messages.append({"type": "game_over", "winner_id": match.state.winner_id})
        for ws in list(self._sockets.get(match.id, ())):
            try:
                for msg in messages:
                    await ws.send_json(msg)
            except Exception:
                # Dead connection; its handler will clean up on disconnect too.
                self.remove(match.id, ws)


async def reject(ws: WebSocket, reason: str, message: str, code: int) -> None:
    await ws.accept()
    await ws.send_json(error_message(reason, message))
    await ws.close(code=code)


@router.websocket("/ws/matches/{match_id}")
async def match_socket(ws: WebSocket, match_id: str, player: str | None = None) -> None:
    manager: MatchManager = ws.app.state.matches
    hub: Hub = ws.app.state.hub

    try:
        match = manager.get(match_id)
    except MatchError as e:
        await reject(ws, e.reason, str(e), CLOSE_NOT_FOUND)
        return
    if player is not None and player not in {p.id for p in match.state.config.players}:
        await reject(ws, "unknown_player", f"{player} has no seat in this match", CLOSE_FORBIDDEN)
        return

    await ws.accept()
    hub.add(match_id, ws)
    try:
        await _greet(ws, manager, match, player)
        while True:
            await _handle_frame(ws, manager, match_id, player, await ws.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(match_id, ws)


async def _greet(ws: WebSocket, manager: MatchManager, match: Match, player: str | None) -> None:
    if player is not None:
        try:
            await manager.join(match.id, player)  # broadcasts new state to everyone, incl. us
            return
        except MatchError as e:
            if e.reason != "already_joined":  # reconnect is fine
                raise
    await ws.send_json(state_message(match))


async def _handle_frame(
    ws: WebSocket, manager: MatchManager, match_id: str, player: str | None, raw: str
) -> None:
    try:
        msg = MoveMessage.model_validate_json(raw)
    except ValidationError:
        await ws.send_json(
            error_message("bad_message", 'expected {"type":"move","pile":int,"count":int}')
        )
        return
    if player is None:
        await ws.send_json(error_message("spectator", "spectators cannot move"))
        return
    try:
        await manager.submit_move(match_id, player, msg.pile, msg.count)  # success broadcasts
    except (MatchError, IllegalMoveError) as e:
        await ws.send_json(error_message(e.reason, str(e)))

"""In-memory match management: lifecycle (waiting -> active -> finished) around the pure engine."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.game.engine import GameConfig, GameState, apply_move, new_game

MatchStatus = Literal["waiting", "active", "finished"]

MatchErrorReason = Literal["match_not_found", "unknown_player", "already_joined", "not_started"]


class MatchError(Exception):
    """Lifecycle error outside the game rules. `reason` is a stable machine-readable code."""

    def __init__(self, reason: MatchErrorReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class Match:
    id: str
    state: GameState
    joined: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def status(self) -> MatchStatus:
        if self.state.is_over:
            return "finished"
        all_joined = len(self.joined) == len(self.state.config.players)
        return "active" if all_joined else "waiting"


class MatchManager:
    def __init__(self) -> None:
        self._matches: dict[str, Match] = {}

    def create(self, config: GameConfig) -> Match:
        match = Match(id=uuid.uuid4().hex[:12], state=new_game(config))
        self._matches[match.id] = match
        return match

    def get(self, match_id: str) -> Match:
        try:
            return self._matches[match_id]
        except KeyError:
            raise MatchError("match_not_found", f"match {match_id} not found") from None

    async def join(self, match_id: str, player_id: str) -> Match:
        match = self.get(match_id)
        async with match.lock:
            if player_id not in {p.id for p in match.state.config.players}:
                raise MatchError("unknown_player", f"{player_id} has no seat in this match")
            if player_id in match.joined:
                raise MatchError("already_joined", f"{player_id} already joined")
            match.joined.add(player_id)
        return match

    async def submit_move(self, match_id: str, player_id: str, pile: int, count: int) -> Match:
        """Single entry point for every move (human now, agents later)."""
        match = self.get(match_id)
        async with match.lock:
            if match.status == "waiting":
                raise MatchError("not_started", "waiting for all players to join")
            # Engine raises IllegalMoveError (incl. game_over); state only changes on success.
            match.state = apply_move(match.state, player_id, pile, count)
        return match


"""API (Pydantic) models and conversion from engine/match domain objects."""

from __future__ import annotations

from pydantic import BaseModel, Field, StrictInt

from app.game.engine import GameConfig, PlayerSpec
from app.game.match import Match, MatchStatus


class PlayerIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=60)


class CreateMatchRequest(BaseModel):
    piles: list[StrictInt]
    players: list[PlayerIn]

    def to_config(self) -> GameConfig:
        return GameConfig(
            piles=self.piles,
            players=[PlayerSpec(id=p.id, name=p.name or p.id) for p in self.players],
        )


class JoinRequest(BaseModel):
    player_id: str


class MoveRequest(BaseModel):
    player_id: str
    pile: StrictInt
    count: StrictInt


class PlayerOut(BaseModel):
    id: str
    name: str
    kind: str
    joined: bool


class MoveOut(BaseModel):
    player_id: str
    pile: int
    count: int
    piles_after: list[int]


class MatchOut(BaseModel):
    id: str
    status: MatchStatus
    initial_piles: list[int]
    piles: list[int]
    players: list[PlayerOut]
    current_player_id: str | None
    winner_id: str | None
    moves: list[MoveOut]

    @classmethod
    def from_match(cls, match: Match) -> MatchOut:
        state = match.state
        return cls(
            id=match.id,
            status=match.status,
            initial_piles=list(state.config.piles),
            piles=list(state.piles),
            players=[
                PlayerOut(id=p.id, name=p.name, kind=p.kind, joined=p.id in match.joined)
                for p in state.config.players
            ],
            current_player_id=None if state.is_over else state.current_player.id,
            winner_id=state.winner_id,
            moves=[
                MoveOut(
                    player_id=m.player_id,
                    pile=m.pile,
                    count=m.count,
                    piles_after=list(m.piles_after),
                )
                for m in state.moves
            ],
        )


class ErrorOut(BaseModel):
    reason: str
    message: str

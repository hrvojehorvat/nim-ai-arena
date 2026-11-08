"""API (Pydantic) models and conversion from engine/match domain objects."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, StrictInt

from app.game.engine import GameConfig, PlayerSpec
from app.game.match import Match, MatchStatus


class PlayerIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=60)


class CreateMatchRequest(BaseModel):
    piles: list[StrictInt]
    players: list[PlayerIn]
    max_take: StrictInt | None = None
    # Seconds per turn; None = no limit. On expiry the server plays 1 stone from the first
    # non-empty pile for the current player.
    turn_timeout: float | None = Field(default=None, gt=0, le=3600)

    def to_config(self) -> GameConfig:
        return GameConfig(
            piles=self.piles,
            players=[PlayerSpec(id=p.id, name=p.name or p.id) for p in self.players],
            max_take=self.max_take,
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
    auto: bool


class MatchOut(BaseModel):
    id: str
    status: MatchStatus
    max_take: int | None
    turn_timeout: float | None
    turn_time_left: float | None
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
            max_take=state.config.max_take,
            turn_timeout=match.turn_timeout,
            turn_time_left=match.turn_time_left(),
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
                    auto=i in match.auto_moves,
                )
                for i, m in enumerate(state.moves)
            ],
        )


class ErrorOut(BaseModel):
    reason: str
    message: str


# --- history / replay (read from the database) ---


class MatchSummaryOut(BaseModel):
    id: str
    status: MatchStatus
    winner_id: str | None
    created_at: datetime
    finished_at: datetime | None
    initial_piles: list[int]
    max_take: int | None
    player_ids: list[str]  # in turn order
    move_count: int


class ReplayPlayerOut(BaseModel):
    id: str
    name: str
    kind: str
    seat: int


class ReplayMoveOut(BaseModel):
    turn_no: int
    player_id: str
    pile: int
    count: int
    piles_after: list[int]
    auto: bool


class ReplayOut(BaseModel):
    """A saved match: `initial_piles` + ordered `moves` is enough to step through the game."""

    id: str
    status: MatchStatus
    winner_id: str | None
    created_at: datetime
    finished_at: datetime | None
    turn_timeout: float | None
    initial_piles: list[int]
    max_take: int | None
    players: list[ReplayPlayerOut]
    moves: list[ReplayMoveOut]

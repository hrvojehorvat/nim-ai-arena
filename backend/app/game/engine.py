"""Pure Nim game engine: no I/O, no async. The server's single source of truth for rules."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

MAX_PILES = 20
MAX_STONES_PER_PILE = 100
MIN_PLAYERS = 2

PlayerKind = Literal["human"]

IllegalMoveReason = Literal["game_over", "not_your_turn", "invalid_pile", "invalid_count"]


class InvalidConfigError(ValueError):
    """Raised when a GameConfig violates setup rules."""


class IllegalMoveError(ValueError):
    """Raised when a move violates game rules. `reason` is a stable machine-readable code."""

    def __init__(self, reason: IllegalMoveReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PlayerSpec:
    id: str
    name: str
    kind: PlayerKind = "human"


@dataclass(frozen=True)
class GameConfig:
    piles: tuple[int, ...]
    players: tuple[PlayerSpec, ...]

    def __post_init__(self) -> None:
        # Normalize lists to tuples so configs stay immutable and hashable.
        object.__setattr__(self, "piles", tuple(self.piles))
        object.__setattr__(self, "players", tuple(self.players))
        self._validate()

    def _validate(self) -> None:
        if not 1 <= len(self.piles) <= MAX_PILES:
            raise InvalidConfigError(f"number of piles must be between 1 and {MAX_PILES}")
        for i, stones in enumerate(self.piles):
            if not isinstance(stones, int) or isinstance(stones, bool):
                raise InvalidConfigError(f"pile {i} must be an integer")
            if not 0 <= stones <= MAX_STONES_PER_PILE:
                raise InvalidConfigError(
                    f"pile {i} must have between 0 and {MAX_STONES_PER_PILE} stones"
                )
        if sum(self.piles) == 0:
            raise InvalidConfigError("at least one pile must be non-empty")
        if len(self.players) < MIN_PLAYERS:
            raise InvalidConfigError(f"at least {MIN_PLAYERS} players are required")
        ids = [p.id for p in self.players]
        if len(set(ids)) != len(ids):
            raise InvalidConfigError("player ids must be unique")


@dataclass(frozen=True)
class Move:
    player_id: str
    pile: int
    count: int
    piles_after: tuple[int, ...]


@dataclass(frozen=True)
class GameState:
    config: GameConfig
    piles: tuple[int, ...]
    current_player_index: int = 0
    moves: tuple[Move, ...] = field(default_factory=tuple)
    winner_id: str | None = None

    @property
    def is_over(self) -> bool:
        return self.winner_id is not None

    @property
    def current_player(self) -> PlayerSpec:
        return self.config.players[self.current_player_index]


def new_game(config: GameConfig) -> GameState:
    return GameState(config=config, piles=config.piles)


def apply_move(state: GameState, player_id: str, pile: int, count: int) -> GameState:
    """Validate and apply a move, returning a new state. The input state is never mutated."""
    if state.is_over:
        raise IllegalMoveError("game_over", "the game is already over")
    if player_id != state.current_player.id:
        raise IllegalMoveError(
            "not_your_turn", f"it is {state.current_player.id}'s turn, not {player_id}'s"
        )
    if not 0 <= pile < len(state.piles):
        raise IllegalMoveError("invalid_pile", f"pile {pile} does not exist")
    available = state.piles[pile]
    if not 1 <= count <= available:
        raise IllegalMoveError(
            "invalid_count", f"must remove between 1 and {available} stones from pile {pile}"
        )

    piles_after = tuple(s - count if i == pile else s for i, s in enumerate(state.piles))
    move = Move(player_id=player_id, pile=pile, count=count, piles_after=piles_after)
    winner_id = player_id if sum(piles_after) == 0 else None
    next_index = (
        state.current_player_index
        if winner_id
        else (state.current_player_index + 1) % len(state.config.players)
    )
    return replace(
        state,
        piles=piles_after,
        current_player_index=next_index,
        moves=(*state.moves, move),
        winner_id=winner_id,
    )

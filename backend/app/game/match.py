"""Match management: lifecycle (waiting -> active -> finished) around the pure engine.

Matches live in memory. Persistence is delegated to a MatchStore, which is written *before* the
in-memory state changes, so memory never gets ahead of what was saved.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.game.engine import GameConfig, GameState, Move, apply_move, default_move, new_game

log = logging.getLogger(__name__)

MatchStatus = Literal["waiting", "active", "finished", "abandoned"]

MatchErrorReason = Literal[
    "match_not_found", "unknown_player", "already_joined", "not_started", "storage_error"
]


class MatchError(Exception):
    """Lifecycle error outside the game rules. `reason` is a stable machine-readable code."""

    def __init__(self, reason: MatchErrorReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class StorageError(Exception):
    """A MatchStore could not save. Raised by store implementations."""


@dataclass
class Match:
    id: str
    state: GameState
    # Seconds a player has per turn; None = no limit. On expiry the server plays default_move.
    turn_timeout: float | None = None
    joined: set[str] = field(default_factory=set)
    # Indices into state.moves that the server played on a player's behalf (timeout).
    auto_moves: set[int] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    turn_deadline: float | None = field(default=None, repr=False)  # loop.time() based
    _timer: asyncio.Task | None = field(default=None, repr=False)

    @property
    def status(self) -> MatchStatus:
        if self.state.is_over:
            return "finished"
        all_joined = len(self.joined) == len(self.state.config.players)
        return "active" if all_joined else "waiting"

    def turn_time_left(self) -> float | None:
        if self.turn_deadline is None:
            return None
        return max(0.0, self.turn_deadline - asyncio.get_running_loop().time())


class MatchStore(Protocol):
    """Where match history is saved. Implementations raise StorageError on failure."""

    async def create(self, match: Match) -> None: ...

    async def set_status(self, match_id: str, status: MatchStatus) -> None: ...

    async def record_move(
        self,
        match_id: str,
        turn_no: int,
        move: Move,
        auto: bool,
        status: MatchStatus,
        winner_id: str | None,
    ) -> None: ...


class NullMatchStore:
    """In-memory mode: nothing is saved."""

    async def create(self, match: Match) -> None:
        pass

    async def set_status(self, match_id: str, status: MatchStatus) -> None:
        pass

    async def record_move(
        self,
        match_id: str,
        turn_no: int,
        move: Move,
        auto: bool,
        status: MatchStatus,
        winner_id: str | None,
    ) -> None:
        pass


@contextmanager
def _storage_guard() -> Iterator[None]:
    try:
        yield
    except StorageError as e:
        log.error("match storage failed: %s", e)
        raise MatchError("storage_error", "could not save to the database, try again") from e


OnChange = Callable[["Match"], Awaitable[None]]


class MatchManager:
    def __init__(self, on_change: OnChange | None = None, store: MatchStore | None = None) -> None:
        self._matches: dict[str, Match] = {}
        # Called while holding the match lock after every state change, so observers
        # (e.g. WebSocket broadcast) see changes in order. Must not call back into the manager.
        self._on_change = on_change
        self.store: MatchStore = store or NullMatchStore()

    async def _changed(self, match: Match) -> None:
        if self._on_change is not None:
            await self._on_change(match)

    async def create(self, config: GameConfig, turn_timeout: float | None = None) -> Match:
        match = Match(id=uuid.uuid4().hex[:12], state=new_game(config), turn_timeout=turn_timeout)
        with _storage_guard():
            await self.store.create(match)
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
            if len(match.joined) + 1 == len(match.state.config.players):
                with _storage_guard():
                    await self.store.set_status(match.id, "active")
            match.joined.add(player_id)
            self._restart_turn_timer(match)
            await self._changed(match)
        return match

    async def submit_move(self, match_id: str, player_id: str, pile: int, count: int) -> Match:
        """Single entry point for every move (human now, agents later)."""
        match = self.get(match_id)
        async with match.lock:
            if match.status == "waiting":
                raise MatchError("not_started", "waiting for all players to join")
            await self._apply(match, player_id, pile, count, auto=False)
        return match

    async def close(self) -> None:
        """Cancel all running turn timers (app shutdown)."""
        for match in self._matches.values():
            self._cancel_timer(match)

    # --- internals (call only while holding match.lock) ---

    async def _apply(self, match: Match, player_id: str, pile: int, count: int, auto: bool) -> None:
        # Engine raises IllegalMoveError (incl. game_over); nothing changes unless all steps pass.
        new_state = apply_move(match.state, player_id, pile, count)
        turn_no = len(match.state.moves)
        with _storage_guard():
            await self.store.record_move(
                match.id,
                turn_no,
                new_state.moves[-1],
                auto,
                "finished" if new_state.is_over else "active",
                new_state.winner_id,
            )
        match.state = new_state
        if auto:
            match.auto_moves.add(turn_no)
        self._restart_turn_timer(match)
        await self._changed(match)

    def _cancel_timer(self, match: Match) -> None:
        timer = match._timer
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        match._timer = None
        match.turn_deadline = None

    def _restart_turn_timer(self, match: Match) -> None:
        self._cancel_timer(match)
        if match.turn_timeout is None or match.status != "active":
            return
        loop = asyncio.get_running_loop()
        match.turn_deadline = loop.time() + match.turn_timeout
        turn_no = len(match.state.moves)
        match._timer = loop.create_task(self._expire_turn(match, turn_no))

    async def _expire_turn(self, match: Match, turn_no: int) -> None:
        await asyncio.sleep(match.turn_timeout)
        async with match.lock:
            # Guard against a move that landed just as the timer fired.
            if match.status != "active" or len(match.state.moves) != turn_no:
                return
            pile, count = default_move(match.state)
            try:
                await self._apply(match, match.state.current_player.id, pile, count, auto=True)
            except MatchError:
                # Couldn't save the auto move (already logged): give the player a fresh period
                # and try again, rather than letting the game stall with no timer.
                self._restart_turn_timer(match)
                await self._changed(match)

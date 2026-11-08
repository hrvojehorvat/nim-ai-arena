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

from app.agents.base import Agent
from app.game.engine import (
    GameConfig,
    GameState,
    IllegalMoveError,
    Move,
    apply_move,
    default_move,
    new_game,
)

log = logging.getLogger(__name__)

MatchStatus = Literal["waiting", "active", "finished", "abandoned"]

MatchErrorReason = Literal[
    "match_not_found",
    "unknown_player",
    "already_joined",
    "not_started",
    "storage_error",
    "unknown_agent",
    "agent_seat",
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
    agent_move_delay: float | None = None  # None = use the manager's default
    joined: set[str] = field(default_factory=set)
    # Indices into state.moves that the server played on a player's behalf (timeout).
    auto_moves: set[int] = field(default_factory=set)
    # Why a move was made (agents, and timeout moves), keyed by index into state.moves.
    reasons: dict[int, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    turn_deadline: float | None = field(default=None, repr=False)  # loop.time() based
    _timer: asyncio.Task | None = field(default=None, repr=False)
    _agent_task: asyncio.Task | None = field(default=None, repr=False)

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
        reasoning: str | None = None,
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
        reasoning: str | None = None,
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

AGENT_RETRY_DELAY = 1.0  # seconds before retrying an agent move that couldn't be saved


class MatchManager:
    def __init__(
        self,
        on_change: OnChange | None = None,
        store: MatchStore | None = None,
        agents: dict[str, Agent] | None = None,
        agent_move_delay: float = 0.0,
    ) -> None:
        self._matches: dict[str, Match] = {}
        # Seat kind -> agent. Any kind that isn't "human" must be registered here.
        self._agents: dict[str, Agent] = agents or {}
        # Pause before each agent move so a human can follow agent-vs-agent games.
        self._agent_move_delay = agent_move_delay
        # Called while holding the match lock after every state change, so observers
        # (e.g. WebSocket broadcast) see changes in order. Must not call back into the manager.
        self._on_change = on_change
        self.store: MatchStore = store or NullMatchStore()

    @property
    def agents(self) -> dict[str, Agent]:
        return self._agents

    async def _changed(self, match: Match) -> None:
        if self._on_change is not None:
            await self._on_change(match)

    async def create(
        self,
        config: GameConfig,
        turn_timeout: float | None = None,
        agent_move_delay: float | None = None,
    ) -> Match:
        state = new_game(config)
        for p in config.players:
            if p.kind != "human" and p.kind not in self._agents:
                known = ", ".join(["human", *sorted(self._agents)])
                raise MatchError("unknown_agent", f"unknown player kind {p.kind!r} (use {known})")
        match = Match(
            id=uuid.uuid4().hex[:12],
            state=state,
            turn_timeout=turn_timeout,
            agent_move_delay=agent_move_delay,
        )
        # Agents don't "connect": their seats are taken from the start.
        match.joined = {p.id for p in config.players if p.kind != "human"}
        with _storage_guard():
            await self.store.create(match)
        self._matches[match.id] = match
        async with match.lock:
            self._begin_turn(match)  # an all-agent match starts playing right away
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
            self._begin_turn(match)
            await self._changed(match)
        return match

    async def submit_move(self, match_id: str, player_id: str, pile: int, count: int) -> Match:
        """Entry point for moves from clients. Agent seats are played by the server only."""
        match = self.get(match_id)
        async with match.lock:
            seat = next((p for p in match.state.config.players if p.id == player_id), None)
            if seat is not None and seat.kind != "human":
                raise MatchError("agent_seat", f"{player_id} is played by an agent")
            if match.status == "waiting":
                raise MatchError("not_started", "waiting for all players to join")
            await self._apply(match, player_id, pile, count, auto=False)
        return match

    async def close(self) -> None:
        """Cancel all running turn timers (app shutdown)."""
        for match in self._matches.values():
            self._cancel_timer(match)
            if match._agent_task is not None:
                match._agent_task.cancel()

    # --- internals (call only while holding match.lock) ---

    async def _apply(
        self,
        match: Match,
        player_id: str,
        pile: int,
        count: int,
        auto: bool,
        reasoning: str | None = None,
    ) -> None:
        """The one path every move takes (human, agent, timeout): validate, save, apply, notify."""
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
                reasoning,
            )
        match.state = new_state
        if auto:
            match.auto_moves.add(turn_no)
        if reasoning:
            match.reasons[turn_no] = reasoning
        self._begin_turn(match)
        await self._changed(match)

    def _cancel_timer(self, match: Match) -> None:
        timer = match._timer
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        match._timer = None
        match.turn_deadline = None

    def _begin_turn(self, match: Match) -> None:
        """Start the clock for the current turn and, if an agent is up, start it thinking."""
        self._restart_turn_timer(match)
        self._start_agent_if_due(match)

    def _start_agent_if_due(self, match: Match) -> None:
        if match.status != "active":
            return
        player = match.state.current_player
        agent = self._agents.get(player.kind)
        if agent is None:
            return
        turn_no = len(match.state.moves)
        match._agent_task = asyncio.get_running_loop().create_task(
            self._run_agent(match, agent, player.id, turn_no)
        )

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
            why = f"Timed out, so the server played {count} stone from pile {pile + 1}."
            try:
                await self._apply(
                    match, match.state.current_player.id, pile, count, auto=True, reasoning=why
                )
            except MatchError:
                # Couldn't save the auto move (already logged): give the player a fresh period
                # and try again, rather than letting the game stall with no timer.
                self._begin_turn(match)
                await self._changed(match)

    async def _run_agent(self, match: Match, agent: Agent, player_id: str, turn_no: int) -> None:
        # Think without holding the lock; the state is immutable so this snapshot is safe.
        snapshot = match.state
        proposal = None
        try:
            proposal = await agent.choose_move(snapshot, player_id)
        except Exception:
            log.exception("agent for %s failed in match %s", player_id, match.id)
        delay = self._agent_move_delay if match.agent_move_delay is None else match.agent_move_delay
        if delay > 0:
            await asyncio.sleep(delay)
        async with match.lock:
            # A timeout move (or anything else) may have taken this turn while we were thinking.
            if match.status != "active" or len(match.state.moves) != turn_no:
                return
            try:
                if proposal is None:
                    raise IllegalMoveError("invalid_pile", "agent produced no move")
                await self._apply(
                    match,
                    player_id,
                    proposal.pile,
                    proposal.count,
                    auto=False,
                    reasoning=proposal.reasoning,
                )
                return
            except IllegalMoveError:
                log.warning("agent %s proposed an illegal move in match %s", player_id, match.id)
                pile, count = default_move(match.state)
                why = (
                    "The agent failed to produce a legal move, so the server played "
                    f"{count} stone from pile {pile + 1}."
                )
                try:
                    await self._apply(match, player_id, pile, count, auto=True, reasoning=why)
                    return
                except MatchError:
                    pass
            except MatchError:
                pass  # couldn't save (logged by the storage guard)
        # Saving failed: try this turn again shortly instead of stalling the game.
        await asyncio.sleep(AGENT_RETRY_DELAY)
        async with match.lock:
            if match.status == "active" and len(match.state.moves) == turn_no:
                self._start_agent_if_due(match)

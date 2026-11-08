"""What every agent (deterministic or LLM) looks like to the match loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.game.engine import GameState


@dataclass(frozen=True)
class AgentMove:
    pile: int
    count: int
    reasoning: str  # free text: why this move (stored with the move and shown in the UI)


class Agent(Protocol):
    """Reads the full game state (board, rules, move history) and proposes a move.

    The proposal is NOT trusted: the server validates it exactly like a human move.
    `description` is a one-line summary shown in the agent catalog (`GET /agents`).
    """

    description: str

    async def choose_move(self, state: GameState, player_id: str) -> AgentMove: ...

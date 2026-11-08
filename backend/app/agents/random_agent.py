"""Random baseline agent as a LangGraph state machine.

    pick_random_move -> validate_move --ok--> END
                            |
                            +--illegal--> fallback_move -> END

Plays any legal move with equal chance of each non-empty pile. It exists to give the arena a weak
opponent to compare the other agents against. `validate_move` and `fallback_move` are shared
with the optimal agent.
"""

from __future__ import annotations

import random

from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentMove
from app.agents.nim_optimal import AgentState, fallback_move, validate_move
from app.game.engine import GameState


def make_pick_random_move(rng: random.Random):
    def pick_random_move(s: AgentState) -> AgentState:
        state = s["state"]
        max_take = state.config.max_take
        pile = rng.choice([i for i, n in enumerate(state.piles) if n > 0])
        limit = state.piles[pile] if max_take is None else min(state.piles[pile], max_take)
        count = rng.randint(1, limit)
        return {
            "pile": pile,
            "count": count,
            "reasoning": f"Random: took {count} from pile {pile + 1}.",
        }

    return pick_random_move


def build_graph(rng: random.Random):
    g = StateGraph(AgentState)
    g.add_node("pick_random_move", make_pick_random_move(rng))
    g.add_node("validate_move", validate_move)
    g.add_node("fallback_move", fallback_move)
    g.add_edge(START, "pick_random_move")
    g.add_edge("pick_random_move", "validate_move")
    g.add_conditional_edges(
        "validate_move", lambda s: END if s["legal"] else "fallback_move", ["fallback_move", END]
    )
    g.add_edge("fallback_move", END)
    return g.compile()


class RandomAgent:
    """Implements the `Agent` protocol. Pass a seed for repeatable play (tests, arena)."""

    def __init__(self, seed: int | None = None) -> None:
        self._graph = build_graph(random.Random(seed))

    async def choose_move(self, state: GameState, player_id: str) -> AgentMove:
        out = await self._graph.ainvoke({"state": state, "player_id": player_id})
        return AgentMove(pile=out["pile"], count=out["count"], reasoning=out["reasoning"])

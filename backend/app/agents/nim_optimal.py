"""Deterministic Nim agent as a LangGraph state machine.

    evaluate_state -> compute_strategy -> select_move -> validate_move --ok--> END
                                                              |
                                                              +--illegal--> fallback_move -> END

Each node adds one piece to the shared state; `select_move` turns the numbers into a
human-readable reasoning string. The maths lives in `strategy.py`.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import strategy
from app.agents.base import AgentMove
from app.game.engine import GameState, IllegalMoveError, apply_move, default_move


class AgentState(TypedDict, total=False):
    # inputs
    state: GameState
    player_id: str
    # filled in by the nodes
    evaluation: strategy.Evaluation
    candidate: tuple[int, int] | None  # winning move, or None = stall
    pile: int
    count: int
    reasoning: str
    legal: bool


def _config(s: AgentState):
    config = s["state"].config
    return config.max_take, config.last_stone_loses


def evaluate_state(s: AgentState) -> AgentState:
    max_take, lsl = _config(s)
    return {"evaluation": strategy.evaluate(s["state"].piles, max_take, lsl)}


def compute_strategy(s: AgentState) -> AgentState:
    max_take, lsl = _config(s)
    piles = s["state"].piles
    return {"candidate": strategy.find_winning_move(piles, max_take, lsl, s["evaluation"])}


def _explain_position(s: AgentState) -> str:
    state, ev = s["state"], s["evaluation"]
    piles = list(state.piles)
    max_take = state.config.max_take
    lsl = state.config.last_stone_loses
    prefix = "Last stone loses. " if lsl else ""
    match ev.method:
        case "nim_sum":
            return f"{prefix}Nim-sum of {piles} is {ev.nim_sum}."
        case "grundy":
            return (
                f"{prefix}With max {max_take} per move each pile counts as size mod "
                f"{max_take + 1}: {list(ev.values)}; their XOR is {ev.nim_sum}."
            )
        case "endgame_parity":
            ones = sum(state.piles)
            return f"Last stone loses and only single stones are left ({ones}): even is winning."
        case "search":
            verdict = "winning" if ev.winning else "losing"
            return (
                f"Last stone loses with max {max_take} per move: I searched every continuation "
                f"and this position is {verdict} for the player to move."
            )
        case _:
            return (
                f"Last stone loses with max {max_take} per move: the board is too big to solve "
                f"exactly, so I fall back to normal-play maths (not guaranteed)."
            )


def select_move(s: AgentState) -> AgentState:
    state, ev, candidate = s["state"], s["evaluation"], s["candidate"]
    where = _explain_position(s)
    players = len(state.config.players)
    note = f" (With {players} players this strategy is not optimal.)" if players > 2 else ""
    if candidate is not None:
        pile, count = candidate
        after = state.piles[pile] - count
        if ev.winning is None:
            verdict = "Best guess"
        else:
            verdict = "I'm winning"
        reasoning = (
            f"{where} {verdict}: take {count} from pile {pile + 1} "
            f"({state.piles[pile]}→{after}).{note}"
        )
        if state.config.last_stone_loses and state.config.max_take is None:
            rest = [after if i == pile else p for i, p in enumerate(state.piles)]
            if all(p <= 1 for p in rest):
                reasoning += (
                    f" That leaves {sum(rest)} single stone(s), an odd number, so the "
                    f"opponent is forced to take the last one."
                )
    else:
        pile, count = strategy.stalling_move(state.piles)
        reasoning = (
            f"{where} That is a losing position against best play, so I take {count} from the "
            f"biggest pile (pile {pile + 1}) to keep the game going and hope for a mistake.{note}"
        )
    return {"pile": pile, "count": count, "reasoning": reasoning}


def validate_move(s: AgentState) -> AgentState:
    """Dry-run through the engine, so a bug in the maths can never produce an illegal move."""
    try:
        apply_move(s["state"], s["player_id"], s["pile"], s["count"])
    except IllegalMoveError:
        return {"legal": False}
    return {"legal": True}


def fallback_move(s: AgentState) -> AgentState:
    pile, count = default_move(s["state"])
    return {
        "pile": pile,
        "count": count,
        "reasoning": (
            f"My calculated move was illegal, so I fell back to taking {count} from pile "
            f"{pile + 1}."
        ),
    }


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("evaluate_state", evaluate_state)
    g.add_node("compute_strategy", compute_strategy)
    g.add_node("select_move", select_move)
    g.add_node("validate_move", validate_move)
    g.add_node("fallback_move", fallback_move)
    g.add_edge(START, "evaluate_state")
    g.add_edge("evaluate_state", "compute_strategy")
    g.add_edge("compute_strategy", "select_move")
    g.add_edge("select_move", "validate_move")
    g.add_conditional_edges(
        "validate_move", lambda s: END if s["legal"] else "fallback_move", ["fallback_move", END]
    )
    g.add_edge("fallback_move", END)
    return g.compile()


class NimOptimalAgent:
    """Implements the `Agent` protocol."""

    def __init__(self) -> None:
        self._graph = build_graph()

    async def choose_move(self, state: GameState, player_id: str) -> AgentMove:
        out = await self._graph.ainvoke({"state": state, "player_id": player_id})
        return AgentMove(pile=out["pile"], count=out["count"], reasoning=out["reasoning"])

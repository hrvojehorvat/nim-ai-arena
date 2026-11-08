"""The `nim_sum` tool an LLM can call: exact analysis of a position, computed by `strategy.py`.

Pure and synchronous. The rules (max_take, last-stone-loses) come from the match, not from the
model, so the model only has to copy the piles. Piles are numbered from 1 in the answer, like in
the prompt.
"""

from __future__ import annotations

from typing import Any

from app.agents import strategy

MAX_PILES, MAX_STONES = 10, 30  # the board limits; also keeps the exact search cheap

TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "nim_sum",
        "description": (
            "Exact Nim analysis of a position: the nim-sum, whether the player to move is "
            "winning, and the best move (pile numbered from 1). Call it with the current piles."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "piles": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Stones in each pile, in order, e.g. [3, 4, 5].",
                }
            },
            "required": ["piles"],
        },
    },
}


def analyze(piles: Any, max_take: int | None, last_stone_loses: bool) -> dict[str, Any]:
    """Raises ValueError for piles the model got wrong, so the message can go back to it."""
    if (
        not isinstance(piles, list)
        or not piles
        or len(piles) > MAX_PILES
        or not all(isinstance(p, int) and not isinstance(p, bool) for p in piles)
    ):
        raise ValueError(f"piles must be a list of 1-{MAX_PILES} integers")
    if any(p < 0 or p > MAX_STONES for p in piles):
        raise ValueError(f"each pile must be between 0 and {MAX_STONES}")
    if not any(piles):
        raise ValueError("all piles are empty: the game is over")
    position = tuple(piles)
    ev = strategy.evaluate(position, max_take, last_stone_loses)
    move = strategy.find_winning_move(position, max_take, last_stone_loses, ev)
    result: dict[str, Any] = {
        "nim_sum": ev.nim_sum,
        "position": "unknown" if ev.winning is None else "winning" if ev.winning else "losing",
    }
    if move is None:
        move = strategy.stalling_move(position)
        result["note"] = "losing against perfect play: this move only prolongs the game"
    result["best_move"] = {"pile": move[0] + 1, "count": move[1]}
    return result

"""Pure helpers for LLM agents: game state -> prompt text, and model reply -> AgentMove.

No network and no LangChain here, so everything is easy to test. Piles are numbered from 1 in
the prompt and in the reply (like the UI); `to_agent_move` converts back to the engine's
0-based index.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.agents.base import AgentMove
from app.agents.llm import AgentDecision
from app.game.engine import GameState

HISTORY_LIMIT = 20  # only the last moves are shown, to keep the prompt short


class ReplyParseError(ValueError):
    """The model's reply held no usable decision. The message can be fed back to the model."""


def build_system_prompt(state: GameState) -> str:
    cfg = state.config
    rules = [
        "You are playing the game of Nim against one opponent. Players alternate turns.",
        "On your turn you pick ONE pile and remove one or more stones from it.",
        "You cannot remove more stones than the pile holds.",
    ]
    if cfg.max_take is not None:
        rules.append(f"You may remove at most {cfg.max_take} stone(s) per turn.")
    if cfg.last_stone_loses:
        rules.append("Whoever takes the LAST stone LOSES.")
    else:
        rules.append("Whoever takes the LAST stone WINS.")
    rules.append("Piles are numbered starting at 1.")
    rules.append(
        "Answer ONLY with a JSON object with keys reasoning (string, 1-3 sentences), "
        "pile (integer) and count (integer). No other text, no code fences."
    )
    return "\n".join(rules)


def build_user_prompt(state: GameState, player_id: str) -> str:
    cfg = state.config
    names = {p.id: p.name for p in cfg.players}
    lines = [f"You are {names.get(player_id, player_id)}.", "Current piles:"]
    for i, stones in enumerate(state.piles, start=1):
        limit = stones if cfg.max_take is None else min(stones, cfg.max_take)
        lines.append(
            f"  Pile {i}: {stones} stones"
            + (f" (you may take 1-{limit})" if stones else " (empty)")
        )
    moves = state.moves[-HISTORY_LIMIT:]
    if moves:
        lines.append("Moves so far:")
        skipped = len(state.moves) - len(moves)
        if skipped:
            lines.append(f"  ... {skipped} earlier moves omitted")
        for mv in moves:
            who = "you" if mv.player_id == player_id else "opponent"
            lines.append(
                f"  {who} took {mv.count} from pile {mv.pile + 1} -> {list(mv.piles_after)}"
            )
    lines.append("Choose your move.")
    return "\n".join(lines)


def build_retry_prompt(error: str) -> str:
    """Sent back to the model after a bad reply or an illegal move."""
    return (
        f"That answer was not accepted: {error}\n"
        "Look at the current piles again and answer ONLY with the JSON object."
    )


def parse_decision(text: str) -> AgentDecision:
    """Find the first JSON object in the reply (tolerating fences and chatter) and validate it."""
    decoder = json.JSONDecoder()
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        try:
            return AgentDecision.model_validate(obj)
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
            )
            raise ReplyParseError(f"the JSON had invalid fields ({problems})") from e
    raise ReplyParseError("the reply contained no JSON object")


def to_agent_move(decision: AgentDecision) -> AgentMove:
    """Convert the model's 1-based pile to the engine's 0-based index. Not validated here."""
    return AgentMove(pile=decision.pile - 1, count=decision.count, reasoning=decision.reasoning)

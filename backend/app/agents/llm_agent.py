"""LLM agent as a LangGraph state machine.

    build_prompt -> llm_reason -> validate_move --ok--> END
                        ^              |
                        |              +--illegal/unparsable, retries left--> retry_prompt
                        +------------------------------------------------------+
                                       +--no retries left--> fallback_move -> END

The model sees the rules, the board and the move history (prompt.py). Its answer is parsed
(structured output when the provider supports it, otherwise plain text + parse_decision) and
checked against the engine. A bad answer is sent back with the error, up to MAX_RETRIES times;
after that a safe legal move is played so a weak model can never stall or break a match.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentMove
from app.agents.llm import AgentDecision, LlmProvider
from app.agents.nim_optimal import AgentState
from app.agents.prompt import (
    ReplyParseError,
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
    parse_decision,
    to_agent_move,
)
from app.game.engine import GameState, IllegalMoveError, apply_move, default_move

MAX_RETRIES = 2  # extra attempts after the first bad answer


class LlmState(AgentState, total=False):
    messages: list[tuple[str, str]]  # (role, text) conversation with the model
    attempts: int
    error: str | None  # why the last answer was rejected


def _text_of(content: Any) -> str:
    """Chat models return a string, or a list of content blocks (Anthropic)."""
    if isinstance(content, str):
        return content
    return "".join(
        b if isinstance(b, str) else b.get("text", "")
        for b in content
        if isinstance(b, (str, dict))
    )


def make_nodes(model: BaseChatModel, structured: bool):
    structured_model = (
        model.with_structured_output(AgentDecision, include_raw=True) if structured else None
    )

    def build_prompt(s: LlmState) -> LlmState:
        state, pid = s["state"], s["player_id"]
        return {
            "messages": [
                ("system", build_system_prompt(state)),
                ("user", build_user_prompt(state, pid)),
            ],
            "attempts": 0,
            "error": None,
        }

    async def llm_reason(s: LlmState) -> LlmState:
        attempts = s["attempts"] + 1
        messages = list(s["messages"])
        try:
            if structured_model is not None:
                out = await structured_model.ainvoke(messages)
                raw_text = _text_of(out["raw"].content)
                decision = out["parsed"]
                if decision is None:  # server ignored the schema: try to rescue the raw text
                    decision = parse_decision(raw_text)
            else:
                raw_text = _text_of((await model.ainvoke(messages)).content)
                decision = parse_decision(raw_text)
        except ReplyParseError as e:
            return {"attempts": attempts, "error": str(e), "messages": messages}
        messages.append(("assistant", raw_text))
        move = to_agent_move(decision)
        return {
            "attempts": attempts,
            "error": None,
            "messages": messages,
            "pile": move.pile,
            "count": move.count,
            "reasoning": move.reasoning,
        }

    def validate_move(s: LlmState) -> LlmState:
        if s.get("error"):  # unparsable answer, already explained
            return {"legal": False}
        try:
            apply_move(s["state"], s["player_id"], s["pile"], s["count"])
        except IllegalMoveError as e:
            return {"legal": False, "error": str(e)}
        return {"legal": True}

    def retry_prompt(s: LlmState) -> LlmState:
        return {"messages": [*s["messages"], ("user", build_retry_prompt(s["error"] or ""))]}

    def fallback_move(s: LlmState) -> LlmState:
        pile, count = default_move(s["state"])
        return {
            "pile": pile,
            "count": count,
            "reasoning": (
                f"The model gave no legal move after {s['attempts']} tries ({s['error']}), "
                f"so a safe move was played: {count} from pile {pile + 1}."
            ),
        }

    return build_prompt, llm_reason, validate_move, retry_prompt, fallback_move


def build_graph(model: BaseChatModel, structured: bool):
    build_prompt, llm_reason, validate_move, retry_prompt, fallback_move = make_nodes(
        model, structured
    )
    g = StateGraph(LlmState)
    g.add_node("build_prompt", build_prompt)
    g.add_node("llm_reason", llm_reason)
    g.add_node("validate_move", validate_move)
    g.add_node("retry_prompt", retry_prompt)
    g.add_node("fallback_move", fallback_move)
    g.add_edge(START, "build_prompt")
    g.add_edge("build_prompt", "llm_reason")
    g.add_edge("llm_reason", "validate_move")

    def route(s: LlmState) -> str:
        if s["legal"]:
            return END
        return "retry_prompt" if s["attempts"] <= MAX_RETRIES else "fallback_move"

    g.add_conditional_edges("validate_move", route, ["retry_prompt", "fallback_move", END])
    g.add_edge("retry_prompt", "llm_reason")
    g.add_edge("fallback_move", END)
    return g.compile()


class LlmAgent:
    """Implements the `Agent` protocol on top of any chat model."""

    def __init__(self, provider: LlmProvider, model: BaseChatModel | None = None) -> None:
        mode = "structured output" if provider.structured else "text + parsing"
        self.description = (
            f"LLM {provider.model} ({mode}). Bad answers are retried, then a safe move is played."
        )
        self._graph = build_graph(model or provider.make(), provider.structured)

    async def choose_move(self, state: GameState, player_id: str) -> AgentMove:
        out = await self._graph.ainvoke({"state": state, "player_id": player_id})
        return AgentMove(pile=out["pile"], count=out["count"], reasoning=out["reasoning"])

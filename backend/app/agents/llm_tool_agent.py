"""LLM agent that can use the `nim_sum` tool (5.8). A second graph next to llm_agent.py.

    native mode (the model decides to call the tool; needs a server with tool calling):

    build_prompt -> llm_reason --tool call--> run_tools --> llm_reason (max MAX_TOOL_ROUNDS times)
                        |
                        +--final answer--> validate_move --ok--> END
                                              +--bad--> retry_prompt -> llm_reason
                                              +--out of retries--> fallback_move -> END

    precompute mode:  build_prompt -> precompute -> llm_reason -> ... (no tool calling at all)

!!! precompute is a WORKAROUND, not real tool use. !!!
Our local Ollama (0.1.48) cannot do tool calling, so the graph itself runs the tool and pastes
the answer into the prompt; the model only has to copy it. It exists so the small local models
can be compared with and without help. Roadmap 5.10 upgrades Ollama and replaces it with native
tools. Do not read arena numbers for "precompute" agents as tool-use ability.

The final answer is always plain text parsed by `parse_decision` (tool calling and enforced JSON
schemas don't combine reliably across servers). The tool is run by our own node instead of
LangGraph's prebuilt ToolNode because it needs the match rules, which the model must not supply.
"""

from __future__ import annotations

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from openai import BadRequestError

from app.agents.llm import LlmProvider
from app.agents.llm_agent import MAX_RETRIES, LlmAgent, _text_of, _usage
from app.agents.nim_optimal import AgentState
from app.agents.nim_tool import TOOL_SPEC, analyze
from app.agents.prompt import (
    ReplyParseError,
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
    parse_decision,
    to_agent_move,
)
from app.game.engine import IllegalMoveError, apply_move, default_move

MAX_TOOL_ROUNDS = 2  # after this the model is called without tools and must answer

NATIVE_HINT = (
    "You have a tool `nim_sum(piles)`. Call it first with the current piles, then use its "
    "best_move in your JSON answer."
)


class ToolState(AgentState, total=False):
    messages: list[BaseMessage]
    attempts: int  # every model call (tool rounds included)
    answers: int  # final answers tried: this is what the retry limit counts
    tool_rounds: int
    tool_calls: int
    pending_tools: bool
    error: str | None
    tokens_in: int
    tokens_out: int
    fell_back: bool


def build_graph(model: BaseChatModel, mode: str):
    bound = model.bind_tools([TOOL_SPEC]) if mode == "native" else model

    def build_prompt(s: ToolState) -> ToolState:
        state, pid = s["state"], s["player_id"]
        system = build_system_prompt(state) + ("\n" + NATIVE_HINT if mode == "native" else "")
        return {
            "messages": [SystemMessage(system), HumanMessage(build_user_prompt(state, pid))],
            "attempts": 0,
            "answers": 0,
            "tool_rounds": 0,
            "tool_calls": 0,
            "pending_tools": False,
            "error": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "fell_back": False,
        }

    def precompute(s: ToolState) -> ToolState:  # WORKAROUND node, see module docstring
        cfg = s["state"].config
        result = analyze(list(s["state"].piles), cfg.max_take, cfg.last_stone_loses)
        *rest, last = s["messages"]
        note = (
            f"{last.content}\n\nAn exact solver already analysed this position: "
            f"{json.dumps(result)}\nUse its best_move unless you have a better reason."
        )
        return {"messages": [*rest, HumanMessage(note)], "tool_calls": 1}

    async def llm_reason(s: ToolState) -> ToolState:
        use_tools = mode == "native" and s["tool_rounds"] < MAX_TOOL_ROUNDS
        try:
            reply = await (bound if use_tools else model).ainvoke(s["messages"])
        except BadRequestError:
            # e.g. gpt-oss on Groq sometimes "calls" a tool named `json` for its final answer and
            # the server rejects it. Treat it as a bad answer: the retry prompt explains.
            return {
                "attempts": s["attempts"] + 1,
                "answers": s["answers"] + 1,
                "pending_tools": False,
                "error": (
                    "the server rejected your reply as an invalid tool call. The only tool is "
                    "nim_sum; give your final answer as plain JSON text, not as a tool call"
                ),
            }
        t_in, t_out = _usage(reply)
        out: ToolState = {
            "attempts": s["attempts"] + 1,
            "messages": [*s["messages"], reply],
            "tokens_in": s["tokens_in"] + t_in,
            "tokens_out": s["tokens_out"] + t_out,
            "pending_tools": False,
        }
        if use_tools and getattr(reply, "tool_calls", None):
            return {**out, "pending_tools": True}
        out["answers"] = s["answers"] + 1
        try:
            move = to_agent_move(parse_decision(_text_of(reply.content)))
        except ReplyParseError as e:
            return {**out, "error": str(e)}
        return {
            **out,
            "error": None,
            "pile": move.pile,
            "count": move.count,
            "reasoning": move.reasoning,
        }

    def run_tools(s: ToolState) -> ToolState:
        cfg = s["state"].config
        *_, ai = s["messages"]
        replies: list[BaseMessage] = []
        for call in ai.tool_calls:  # type: ignore[attr-defined]
            if call["name"] != "nim_sum":
                content = f"error: unknown tool {call['name']!r}"
            else:
                try:
                    piles = call["args"].get("piles")
                    content = json.dumps(analyze(piles, cfg.max_take, cfg.last_stone_loses))
                except ValueError as e:
                    content = f"error: {e}"
            replies.append(ToolMessage(content, tool_call_id=call["id"], name=call["name"]))
        return {
            "messages": [*s["messages"], *replies],
            "tool_rounds": s["tool_rounds"] + 1,
            "tool_calls": s["tool_calls"] + len(replies),
            "pending_tools": False,
        }

    def validate_move(s: ToolState) -> ToolState:
        if s.get("error"):
            return {"legal": False}
        try:
            apply_move(s["state"], s["player_id"], s["pile"], s["count"])
        except IllegalMoveError as e:
            return {"legal": False, "error": str(e)}
        return {"legal": True}

    def retry_prompt(s: ToolState) -> ToolState:
        retry = HumanMessage(build_retry_prompt(s["error"] or ""))
        return {"messages": [*s["messages"], retry]}

    def fallback_move(s: ToolState) -> ToolState:
        pile, count = default_move(s["state"])
        return {
            "fell_back": True,
            "pile": pile,
            "count": count,
            "reasoning": (
                f"The model gave no legal move after {s['answers']} tries ({s['error']}), "
                f"so a safe move was played: {count} from pile {pile + 1}."
            ),
        }

    g = StateGraph(ToolState)
    for name, fn in [
        ("build_prompt", build_prompt),
        ("llm_reason", llm_reason),
        ("run_tools", run_tools),
        ("validate_move", validate_move),
        ("retry_prompt", retry_prompt),
        ("fallback_move", fallback_move),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "build_prompt")
    if mode == "precompute":
        g.add_node("precompute", precompute)
        g.add_edge("build_prompt", "precompute")
        g.add_edge("precompute", "llm_reason")
    else:
        g.add_edge("build_prompt", "llm_reason")
    g.add_conditional_edges(
        "llm_reason",
        lambda s: "run_tools" if s["pending_tools"] else "validate_move",
        ["run_tools", "validate_move"],
    )
    g.add_edge("run_tools", "llm_reason")

    def route(s: ToolState) -> str:
        if s["legal"]:
            return END
        return "retry_prompt" if s["answers"] <= MAX_RETRIES else "fallback_move"

    g.add_conditional_edges("validate_move", route, ["retry_prompt", "fallback_move", END])
    g.add_edge("retry_prompt", "llm_reason")
    g.add_edge("fallback_move", END)
    return g.compile()


class ToolLlmAgent(LlmAgent):
    """Same `Agent` protocol and stats as LlmAgent, with the nim_sum tool in the graph."""

    def _describe(self, provider: LlmProvider) -> str:
        if provider.tools == "precompute":
            return (
                f"LLM {provider.model} + nim_sum analysis. WORKAROUND: this server has no tool "
                "calling, so the graph precomputes the analysis and pastes it into the prompt."
            )
        return (
            f"LLM {provider.model} with a nim_sum tool it can call (native tool calling). "
            "Bad answers are retried, then a safe move is played."
        )

    def _make_graph(self, provider: LlmProvider, model: BaseChatModel):
        return build_graph(model, provider.tools or "native")


def make_llm_agent(provider: LlmProvider) -> LlmAgent:
    return ToolLlmAgent(provider) if provider.tools else LlmAgent(provider)

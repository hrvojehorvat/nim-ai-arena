"""The LLM agent graph with scripted fake models: no network, no keys."""

import pytest
from langchain_core.messages import AIMessage

from app.agents.llm import AgentDecision, LlmProvider
from app.agents.llm_agent import MAX_RETRIES, LlmAgent
from app.agents.registry import build_agents
from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game

pytestmark = pytest.mark.anyio

A = PlayerSpec("a", "A")
B = PlayerSpec("b", "B")
GOOD = '{"reasoning": "because", "pile": 3, "count": 4}'  # piles (3, 4, 5): legal


class FakeModel:
    """Replies with the scripted texts in order and records every conversation it was sent."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[tuple[str, str]]] = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(content=self.replies.pop(0))

    def with_structured_output(self, schema, include_raw=False):
        parent = self

        class Structured:
            async def ainvoke(self, messages):
                raw = await parent.ainvoke(messages)
                try:
                    parsed = AgentDecision.model_validate_json(raw.content)
                except ValueError:
                    parsed = None
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return Structured()


class Provider(LlmProvider):
    DEFAULT_MODEL = "fake"


def agent(replies, structured=False):
    model = FakeModel(replies)
    return LlmAgent(Provider(structured=structured), model=model), model


def state():
    return new_game(GameConfig(piles=(3, 4, 5), players=(A, B)))


async def test_good_reply_becomes_a_zero_based_move() -> None:
    a, model = agent([GOOD])
    move = await a.choose_move(state(), "a")
    assert (move.pile, move.count, move.reasoning) == (2, 4, "because")
    assert len(model.calls) == 1
    roles = [r for r, _ in model.calls[0]]
    assert roles == ["system", "user"]


async def test_fenced_reply_is_parsed_in_text_mode() -> None:
    a, _ = agent([f"```json\n{GOOD}\n```"])
    assert (await a.choose_move(state(), "a")).count == 4


async def test_unparsable_reply_is_retried_with_the_error() -> None:
    a, model = agent(["I would take some stones.", GOOD])
    move = await a.choose_move(state(), "a")
    assert move.count == 4 and len(model.calls) == 2
    last_user = model.calls[1][-1]
    assert last_user[0] == "user" and "no JSON object" in last_user[1]


async def test_illegal_move_is_retried_and_the_engine_error_is_fed_back() -> None:
    a, model = agent(['{"reasoning": "x", "pile": 9, "count": 1}', GOOD])
    move = await a.choose_move(state(), "a")
    assert (move.pile, move.count) == (2, 4) and len(model.calls) == 2
    assert "pile" in model.calls[1][-1][1]
    assert ("assistant", '{"reasoning": "x", "pile": 9, "count": 1}') in model.calls[1]


async def test_gives_up_after_the_retries_and_plays_a_legal_fallback() -> None:
    a, model = agent(["nope"] * (MAX_RETRIES + 1))
    s = state()
    move = await a.choose_move(s, "a")
    assert len(model.calls) == MAX_RETRIES + 1
    apply_move(s, "a", move.pile, move.count)  # must be legal
    assert "safe move" in move.reasoning and "no JSON object" in move.reasoning


async def test_structured_mode_uses_the_parsed_decision() -> None:
    a, _ = agent([GOOD], structured=True)
    assert (await a.choose_move(state(), "a")).count == 4


async def test_structured_mode_rescues_a_reply_the_server_did_not_enforce() -> None:
    a, _ = agent([f"Sure! {GOOD}"], structured=True)  # structured parse fails, text parse works
    assert (await a.choose_move(state(), "a")).count == 4


def test_description_names_the_model_and_mode() -> None:
    a, _ = agent([])
    assert "fake" in a.description and "text" in a.description


# --- registry: only LLMs that can run are offered ---


def test_unconfigured_llms_are_hidden(monkeypatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "MODAL_LLM_URL", "MODAL_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    assert set(build_agents(llms=True)) == {"nim_optimal", "random"}


def test_configured_llms_are_offered(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODAL_LLM_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MODAL_LLM_API_KEY", "k")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9/v1")
    assert set(build_agents(llms=True)) == {"nim_optimal", "random", "claude_haiku", "modal_qwen7b"}


def test_llms_are_off_by_default() -> None:
    assert set(build_agents()) == {"nim_optimal", "random"}

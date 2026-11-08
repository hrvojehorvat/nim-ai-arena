"""Arena with an LLM side: stats are collected and printed. Fake model, no network."""

import re

import pytest
from langchain_core.messages import AIMessage

import app.arena as arena
from app.agents.llm import LlmProvider
from app.agents.llm_agent import LlmAgent
from app.agents.nim_optimal import NimOptimalAgent
from app.agents.random_agent import RandomAgent

pytestmark = pytest.mark.anyio


class TakeOneModel:
    """Always takes 1 stone from the first non-empty pile it sees in the prompt."""

    async def ainvoke(self, messages):
        prompt = messages[1][1]
        pile = next(int(m[0]) for m in re.findall(r"Pile (\d+): ([1-9]\d*) stones", prompt))
        reply = f'{{"reasoning": "easy", "pile": {pile}, "count": 1}}'
        usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
        return AIMessage(content=reply, usage_metadata=usage)


class FakeProvider(LlmProvider):
    DEFAULT_MODEL = "take-one"


def fake_registry(seed=None, llms=False):
    agents = {"nim_optimal": NimOptimalAgent(), "random": RandomAgent(seed)}
    agents["fake_llm"] = LlmAgent(FakeProvider(), model=TakeOneModel())
    return agents


async def test_llm_stats_are_collected_and_reported(monkeypatch) -> None:
    monkeypatch.setattr(arena, "build_agents", fake_registry)
    result = await arena.run_arena("fake_llm", "nim_optimal", games=4, piles=[3, 4, 5])
    stats = result.llm_stats["A"]
    assert "B" not in result.llm_stats  # nim_optimal is not an LLM
    assert stats.moves > 0 and stats.fallbacks == 0 and stats.retried_moves == 0
    assert stats.tokens_in == 100 * stats.moves
    text = arena.format_result(result)
    assert "A: fake_llm (LLM)" in text and "fell back to a safe move: 0.0%" in text
    assert f"tokens: {stats.tokens_in} in / {stats.tokens_out} out" in text

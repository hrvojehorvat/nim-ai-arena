"""The tool agent graph with scripted fake models, plus the nim_sum tool itself."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.llm import LlmProvider
from app.agents.llm_agent import LlmAgent
from app.agents.llm_catalog import LlmConfigError, load_llm_catalog
from app.agents.llm_tool_agent import MAX_TOOL_ROUNDS, ToolLlmAgent, make_llm_agent
from app.agents.nim_tool import analyze
from app.game.engine import GameConfig, PlayerSpec, new_game

pytestmark = pytest.mark.anyio

A, B = PlayerSpec("a", "A"), PlayerSpec("b", "B")
GOOD = '{"reasoning": "solver said so", "pile": 1, "count": 2}'  # piles (3, 4, 5)? see state()


def state():
    return new_game(GameConfig(piles=(3, 4, 5), players=(A, B)))


def call(piles, id="c1"):
    return AIMessage("", tool_calls=[{"name": "nim_sum", "args": {"piles": piles}, "id": id}])


class ToolModel:
    """Replies with scripted messages; records conversations and whether tools were bound."""

    def __init__(self, replies, tools_bound=False):
        self.replies, self.calls, self.tools_bound = list(replies), [], tools_bound

    def bind_tools(self, tools):
        bound = ToolModel(self.replies, tools_bound=True)
        bound.calls = self.calls
        bound.replies = self.replies  # share the script
        return bound

    async def ainvoke(self, messages):
        self.calls.append((self.tools_bound, list(messages)))
        return self.replies.pop(0)


class Provider(LlmProvider):
    DEFAULT_MODEL = "fake"

    def _build(self):
        return ToolModel([])


def agent(replies, mode="native"):
    model = ToolModel(replies)
    return ToolLlmAgent(Provider(tools=mode), model=model), model


async def test_native_calls_the_tool_then_answers() -> None:
    a, model = agent([call([3, 4, 5]), AIMessage(GOOD)])
    move = await a.choose_move(state(), "a")
    assert (move.pile, move.count) == (0, 2)
    assert a.stats.tool_calls == 1 and a.stats.attempts == 2 and a.stats.fallbacks == 0
    assert a.stats.retried_moves == 0  # a tool round is not a retry
    tool_msgs = [m for m in model.calls[1][1] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1 and '"best_move"' in tool_msgs[0].content


async def test_tool_errors_go_back_to_the_model() -> None:
    a, model = agent([call([99]), AIMessage(GOOD)])
    await a.choose_move(state(), "a")
    tool_msg = next(m for m in model.calls[1][1] if isinstance(m, ToolMessage))
    assert tool_msg.content.startswith("error:")


async def test_tool_rounds_are_capped_and_the_model_then_runs_unbound() -> None:
    script = [call([3, 4, 5], f"c{i}") for i in range(MAX_TOOL_ROUNDS)] + [AIMessage(GOOD)]
    a, model = agent(script)
    await a.choose_move(state(), "a")
    assert [bound for bound, _ in model.calls] == [True] * MAX_TOOL_ROUNDS + [False]


async def test_a_server_side_tool_call_rejection_is_retried() -> None:
    import httpx
    from openai import BadRequestError

    class Rejecting:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise BadRequestError(
                "bad tool call",
                response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
                body=None,
            )

    a = ToolLlmAgent(Provider(tools="native"), model=Rejecting())
    first = await a.choose_move(state(), "a")  # every try rejected -> safe move
    assert a.stats.fallbacks == 1 and "safe move" in first.reasoning


async def test_bad_final_answers_still_retry_then_fall_back() -> None:
    a, _ = agent([AIMessage("no idea")] * 3)
    move = await a.choose_move(state(), "a")
    assert a.stats.fallbacks == 1 and "safe move" in move.reasoning


async def test_precompute_pastes_the_analysis_and_never_binds_tools() -> None:
    a, model = agent([AIMessage(GOOD)], mode="precompute")
    await a.choose_move(state(), "a")
    bound, messages = model.calls[0]
    assert not bound and "exact solver" in messages[-1].content
    assert a.stats.tool_calls == 1
    assert "WORKAROUND" in a.description


def test_analyze_gives_the_winning_move_one_based() -> None:
    r = analyze([3, 4, 5], None, False)
    assert r["position"] == "winning" and r["nim_sum"] == 2
    assert r["best_move"] == {"pile": 1, "count": 2}  # 3 -> 1 makes the nim-sum 0


def test_analyze_losing_position_stalls() -> None:
    r = analyze([1, 2, 3], None, False)
    assert r["position"] == "losing" and "note" in r


@pytest.mark.parametrize("piles", [[], [0, 0], [-1, 2], [31], ["a"], [True], "3,4", [1] * 11])
def test_analyze_rejects_bad_piles(piles) -> None:
    with pytest.raises(ValueError):
        analyze(piles, None, False)


def test_make_llm_agent_picks_the_class() -> None:
    assert type(make_llm_agent(Provider(tools="native"))) is ToolLlmAgent
    assert type(make_llm_agent(Provider())) is LlmAgent


def test_ollama_native_tools_are_rejected(tmp_path) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text('[x]\nprovider = "ollama"\nmodel = "m"\ntools = "native"\n')
    with pytest.raises(LlmConfigError, match="too old"):
        load_llm_catalog(cfg)


def test_groq_never_uses_another_providers_key(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("MODAL_LLM_API_KEY", "modal-secret")
    p = load_llm_catalog()["groq_gpt_oss_120b"]()
    assert p.api_key is None and "GROQ_API_KEY" in (p.unavailable_reason() or "")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert load_llm_catalog()["groq_gpt_oss_120b_tools"]().unavailable_reason() is None

"""LLM plumbing that needs no network or API key."""

import pytest
from pydantic import ValidationError

from app.agents.anthropic_llm import AnthropicProvider
from app.agents.llm import AgentDecision, LlmProvider


def test_decision_schema_parses_a_model_answer() -> None:
    d = AgentDecision.model_validate({"reasoning": "nim-sum is 2", "pile": 2, "count": 1})
    assert (d.pile, d.count) == (2, 1)


def test_decision_schema_rejects_missing_fields() -> None:
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"pile": 1})


def test_factory_builds_a_chat_model_without_calling_the_api(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    model = AnthropicProvider().make()
    assert model.model == AnthropicProvider.DEFAULT_MODEL  # type: ignore[attr-defined]
    assert model.with_structured_output(AgentDecision) is not None


def test_subclass_only_changes_the_default_model() -> None:
    class Other(LlmProvider):
        DEFAULT_MODEL = "other-model"

    assert Other().model == "other-model"
    assert Other(model="x").model == "x"


def test_openai_compatible_provider_uses_env_and_default_model(monkeypatch) -> None:
    from app.agents.openai_compat_llm import OpenAICompatProvider

    monkeypatch.setenv("MODAL_LLM_URL", "http://localhost:9/v1")
    monkeypatch.setenv("MODAL_LLM_API_KEY", "k")
    model = OpenAICompatProvider().make()
    assert model.model_name == OpenAICompatProvider.DEFAULT_MODEL  # type: ignore[attr-defined]
    assert model.with_structured_output(AgentDecision) is not None


def test_openai_compatible_provider_needs_configuration(monkeypatch) -> None:
    from app.agents.openai_compat_llm import OpenAICompatProvider

    monkeypatch.delenv("MODAL_LLM_URL", raising=False)
    monkeypatch.delenv("MODAL_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        OpenAICompatProvider().make()


def test_catalog_builds_every_provider_without_network(monkeypatch) -> None:
    from app.agents.llm_catalog import LLM_CATALOG, get_provider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODAL_LLM_URL", "http://localhost:9/v1")
    monkeypatch.setenv("MODAL_LLM_API_KEY", "k")
    for name in LLM_CATALOG:
        assert get_provider(name).make() is not None
    assert get_provider("ollama_smollm2_135m").model == "smollm2:135m"
    with pytest.raises(KeyError):
        get_provider("nope")

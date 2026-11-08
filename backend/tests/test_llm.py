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


def test_default_config_builds_every_provider_without_network(monkeypatch) -> None:
    from app.agents.llm_catalog import get_provider, load_llm_catalog

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODAL_LLM_URL", "http://localhost:9/v1")
    monkeypatch.setenv("MODAL_LLM_API_KEY", "k")
    catalog = load_llm_catalog()
    assert {"modal_qwen7b", "ollama_qwen2_1_5b", "ollama_phi3_mini"} <= set(catalog)
    for make in catalog.values():
        assert make().make() is not None
    assert get_provider("ollama_phi3_mini").model == "phi3:mini"
    with pytest.raises(KeyError):
        get_provider("nope")


def test_anthropic_provider_can_be_configured(tmp_path, monkeypatch) -> None:
    from app.agents.llm_catalog import load_llm_catalog

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    path = write_config(tmp_path, '[claude]\nprovider = "anthropic"\nmodel = "claude-haiku-5-5"')
    provider = load_llm_catalog(path)["claude"]()
    assert provider.unavailable_reason() is None and provider.make() is not None
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "ANTHROPIC_API_KEY" in provider.unavailable_reason()  # type: ignore[operator]


def write_config(tmp_path, text):
    path = tmp_path / "llms.toml"
    path.write_text(text)
    return path


def test_config_options_and_env_indirection(tmp_path, monkeypatch) -> None:
    from app.agents.llm_catalog import load_llm_catalog

    monkeypatch.setenv("OR_URL", "http://example.test/v1")
    monkeypatch.setenv("OR_KEY", "secret")
    path = write_config(
        tmp_path,
        """
[or_llama]
provider = "openai_compat"
model = "llama"
base_url_env = "OR_URL"
api_key_env = "OR_KEY"
max_tokens = 50
structured = false

[local]
provider = "ollama"
model = "x:1b"
structured = true
""",
    )
    catalog = load_llm_catalog(path)
    p = catalog["or_llama"]()
    assert (p.base_url, p.api_key, p.max_tokens, p.structured) == (  # type: ignore[attr-defined]
        "http://example.test/v1",
        "secret",
        50,
        False,
    )
    assert catalog["local"]().structured is True  # overrides Ollama's declared default


@pytest.mark.parametrize(
    "body, fragment",
    [
        ('[a]\nprovider = "wizard"\nmodel = "m"', "provider must be"),
        ('[a]\nprovider = "ollama"', "model is required"),
        ('[a]\nprovider = "ollama"\nmodel = "m"\nbase_url_env = "X"', "unknown keys"),
        ("x = 1", r"must be a \[section\]"),
    ],
)
def test_config_mistakes_are_reported_by_entry(tmp_path, body, fragment) -> None:
    from app.agents.llm_catalog import LlmConfigError, load_llm_catalog

    with pytest.raises(LlmConfigError, match=fragment):
        load_llm_catalog(write_config(tmp_path, body))

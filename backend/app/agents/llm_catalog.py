"""The LLMs we can compare, by name. Each entry builds a provider; nothing is called until used.

Later (5.4/5.5) every name here becomes a selectable agent in the match dropdown and the arena.
"""

from __future__ import annotations

from collections.abc import Callable

from app.agents.anthropic_llm import AnthropicProvider
from app.agents.llm import LlmProvider
from app.agents.ollama_llm import OllamaProvider
from app.agents.openai_compat_llm import OpenAICompatProvider

LLM_CATALOG: dict[str, Callable[[], LlmProvider]] = {
    "claude_haiku": lambda: AnthropicProvider("claude-haiku-5-5"),  # paid (needs credit)
    "modal_qwen7b": lambda: OpenAICompatProvider("Qwen/Qwen2.5-7B-Instruct"),  # Modal credits
    "ollama_qwen2_1_5b": lambda: OllamaProvider("qwen2:1.5b"),  # local, free
    "ollama_smollm2_135m": lambda: OllamaProvider("smollm2:135m"),  # local, free, tiny
}


def get_provider(name: str) -> LlmProvider:
    try:
        return LLM_CATALOG[name]()
    except KeyError:
        raise KeyError(f"unknown llm {name!r} (use {', '.join(sorted(LLM_CATALOG))})") from None

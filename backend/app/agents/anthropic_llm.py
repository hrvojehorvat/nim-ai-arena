"""Anthropic (Claude) provider. Reads ANTHROPIC_API_KEY from the environment."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm import LlmProvider


class AnthropicProvider(LlmProvider):
    DEFAULT_MODEL = "claude-haiku-5-5"  # cheapest Claude

    def _build(self) -> BaseChatModel:
        return ChatAnthropic(model=self.model, max_tokens=self.max_tokens)  # type: ignore[call-arg]

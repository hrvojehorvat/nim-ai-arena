"""Anthropic (Claude) provider. Reads ANTHROPIC_API_KEY from the environment."""

from __future__ import annotations

import os

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm import LlmProvider


class AnthropicProvider(LlmProvider):
    DEFAULT_MODEL = "claude-haiku-5-5"  # cheapest Claude
    STRUCTURED_OUTPUT = True

    def unavailable_reason(self) -> str | None:
        return None if os.environ.get("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY is not set"

    def _build(self) -> BaseChatModel:
        return ChatAnthropic(model=self.model, max_tokens=self.max_tokens)  # type: ignore[call-arg]

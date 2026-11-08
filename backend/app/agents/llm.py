"""Shared pieces for LLM agents: the structured answer we ask for, and a provider base class.

Graph nodes only know LangChain's common chat-model interface (`BaseChatModel`). A provider is a
small subclass of `LlmProvider` that says which default model it uses and how to build the chat
model. Anthropic lives in `anthropic_llm.py`; OpenAI-compatible endpoints (Modal, Ollama, ...)
will be another subclass in 5.6.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field


class AgentDecision(BaseModel):
    """What the model must answer with. Piles are numbered from 1, like in the UI."""

    reasoning: str = Field(description="One to three sentences: why this is the move.")
    pile: int = Field(description="Pile number to take stones from, starting at 1.")
    count: int = Field(description="How many stones to remove from that pile (at least 1).")


class LlmProvider:
    """Base for providers. Subclasses set DEFAULT_MODEL and implement `_build`."""

    DEFAULT_MODEL: str = ""

    def __init__(self, model: str | None = None, max_tokens: int = 1024) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens

    def make(self) -> BaseChatModel:
        return self._build()

    def _build(self) -> BaseChatModel:
        raise NotImplementedError

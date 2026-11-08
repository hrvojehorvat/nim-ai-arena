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
    # Declared (not probed): does the server enforce `with_structured_output` reliably? If not, the
    # agent asks for plain text and parses it with `parse_decision`.
    STRUCTURED_OUTPUT: bool = False

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 1024,
        structured: bool | None = None,
        tools: str | None = None,
    ) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.structured = self.STRUCTURED_OUTPUT if structured is None else structured
        # None = plain LLM agent. "native" = the model calls the nim_sum tool itself.
        # "precompute" = WORKAROUND for servers without tool calling (see llm_tool_agent.py).
        self.tools = tools

    def unavailable_reason(self) -> str | None:
        """None if this provider can be used right now, else why not (missing key, server down...).

        Cheap checks only: never sends a billed request.
        """
        return None

    def make(self) -> BaseChatModel:
        return self._build()

    def _build(self) -> BaseChatModel:
        raise NotImplementedError

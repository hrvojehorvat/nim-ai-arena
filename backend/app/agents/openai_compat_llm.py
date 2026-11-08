"""Provider for any OpenAI-compatible endpoint: Modal (vLLM), Ollama, OpenRouter, OpenAI itself.

Defaults point at the Modal deployment from `deploy/modal_vllm.py`, configured through env vars:
MODAL_LLM_URL (ending in /v1) and MODAL_LLM_API_KEY. Pass base_url/api_key to use another server.
"""

from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.agents.llm import LlmProvider


class OpenAICompatProvider(LlmProvider):
    DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # what deploy/modal_vllm.py serves

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 1024,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, max_tokens)
        self.base_url = base_url or os.environ.get("MODAL_LLM_URL")
        self.api_key = api_key or os.environ.get("MODAL_LLM_API_KEY")

    def _build(self) -> BaseChatModel:
        if not self.base_url or not self.api_key:
            raise RuntimeError("set MODAL_LLM_URL and MODAL_LLM_API_KEY (or pass base_url/api_key)")
        return ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,  # type: ignore[arg-type]
            max_completion_tokens=self.max_tokens,
            timeout=300,  # first call after idle is a cold start (minutes)
        )

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
    STRUCTURED_OUTPUT = True  # vLLM enforces the JSON schema

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 1024,
        base_url: str | None = None,
        api_key: str | None = None,
        structured: bool | None = None,
        tools: str | None = None,
        url_env: str = "MODAL_LLM_URL",
        key_env: str = "MODAL_LLM_API_KEY",
    ) -> None:
        super().__init__(model, max_tokens, structured, tools)
        # Each entry names its own env vars, so a missing key can never fall back to another
        # provider's key (that would send it to the wrong server).
        self.url_env, self.key_env = url_env, key_env
        self.base_url = base_url or os.environ.get(url_env)
        self.api_key = api_key or os.environ.get(key_env)

    def _missing(self) -> str:
        names = [
            n for n, v in ((self.url_env, self.base_url), (self.key_env, self.api_key)) if not v
        ]
        return " / ".join(names)

    def unavailable_reason(self) -> str | None:
        return f"{self._missing()} not set" if self._missing() else None

    def _build(self) -> BaseChatModel:
        if not self.base_url or not self.api_key:
            raise RuntimeError(f"set {self._missing()} (or pass base_url/api_key)")
        return ChatOpenAI(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,  # type: ignore[arg-type]
            max_completion_tokens=self.max_tokens,
            timeout=300,  # first call after idle is a cold start (minutes)
        )

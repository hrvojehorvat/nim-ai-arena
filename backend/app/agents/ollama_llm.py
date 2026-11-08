"""Local models served by Ollama (`ollama pull <model>`; the server listens on :11434).

Ollama speaks the OpenAI protocol, so this is the OpenAI-compatible provider with local defaults.
"""

from __future__ import annotations

import os

from app.agents.openai_compat_llm import OpenAICompatProvider

OLLAMA_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAICompatProvider):
    DEFAULT_MODEL = "qwen2:1.5b"

    def __init__(self, model: str | None = None, max_tokens: int = 1024) -> None:
        super().__init__(
            model,
            max_tokens,
            base_url=os.environ.get("OLLAMA_URL", OLLAMA_URL),
            api_key="ollama",  # Ollama ignores the key, but the client requires one
        )

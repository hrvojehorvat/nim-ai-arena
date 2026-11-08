"""Local models served by Ollama (`ollama pull <model>`; the server listens on :11434).

Ollama speaks the OpenAI protocol, so this is the OpenAI-compatible provider with local defaults.
Structured output is declared off: Ollama only enforces JSON schemas from 0.5.0 (older servers
ignore them), and we can't tell the version from here. Pass structured=True on a new Ollama.
"""

from __future__ import annotations

import json
import os
import urllib.request

from app.agents.openai_compat_llm import OpenAICompatProvider

OLLAMA_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAICompatProvider):
    DEFAULT_MODEL = "qwen2:1.5b"
    STRUCTURED_OUTPUT = False

    def __init__(
        self, model: str | None = None, max_tokens: int = 1024, structured: bool | None = None
    ) -> None:
        super().__init__(
            model,
            max_tokens,
            base_url=os.environ.get("OLLAMA_URL", OLLAMA_URL),
            api_key="ollama",  # Ollama ignores the key, but the client requires one
            structured=structured,
        )

    def unavailable_reason(self) -> str | None:
        """Ollama must be running and the model pulled (`ollama pull <model>`)."""
        tags_url = self.base_url.removesuffix("/v1") + "/api/tags"  # type: ignore[union-attr]
        try:
            with urllib.request.urlopen(tags_url, timeout=1) as r:  # noqa: S310 (local URL)
                names = {m["name"] for m in json.load(r)["models"]}
        except Exception:
            return f"Ollama is not reachable at {tags_url}"
        wanted = {self.model, f"{self.model}:latest"}
        return None if names & wanted else f"model {self.model!r} is not pulled (ollama pull)"

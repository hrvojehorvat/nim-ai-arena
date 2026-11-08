"""Groq: fast hosted open models (gpt-oss, Qwen) with a free tier, over the OpenAI protocol.

Needs GROQ_API_KEY (console.groq.com). Structured output is declared off: Groq only enforces JSON
schemas on some models, so we ask for text and parse it. Native tool calling was verified on
gpt-oss and Qwen3.
"""

from __future__ import annotations

from app.agents.openai_compat_llm import OpenAICompatProvider

GROQ_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAICompatProvider):
    DEFAULT_MODEL = "openai/gpt-oss-120b"
    STRUCTURED_OUTPUT = False

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 1024,
        structured: bool | None = None,
        tools: str | None = None,
    ) -> None:
        super().__init__(
            model,
            max_tokens,
            base_url=GROQ_URL,
            structured=structured,
            tools=tools,
            key_env="GROQ_API_KEY",
        )

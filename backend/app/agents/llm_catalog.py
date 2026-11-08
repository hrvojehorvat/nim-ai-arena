"""The LLMs we can compare, by name, read from `backend/llm_agents.toml`.

Set $NIM_LLM_CONFIG to use another file.

Each entry builds a provider lazily; nothing is called until the agent is used. Only keys and
URLs come from the environment, so the file can be committed.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agents.anthropic_llm import AnthropicProvider
from app.agents.llm import LlmProvider
from app.agents.ollama_llm import OllamaProvider
from app.agents.openai_compat_llm import OpenAICompatProvider

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "llm_agents.toml"
COMMON_KEYS = {"provider", "model", "structured", "max_tokens"}
OPENAI_KEYS = COMMON_KEYS | {"base_url_env", "api_key_env"}
ALLOWED_KEYS = {"anthropic": COMMON_KEYS, "ollama": COMMON_KEYS, "openai_compat": OPENAI_KEYS}


class LlmConfigError(ValueError):
    """llm_agents.toml has a mistake. The message names the entry."""


def _build(name: str, cfg: dict[str, Any]) -> LlmProvider:
    provider = cfg.get("provider")
    if provider not in ALLOWED_KEYS:
        raise LlmConfigError(
            f"[{name}] provider must be one of {sorted(ALLOWED_KEYS)}, not {provider!r}"
        )
    unknown = set(cfg) - ALLOWED_KEYS[provider]
    if unknown:
        raise LlmConfigError(f"[{name}] unknown keys for {provider}: {sorted(unknown)}")
    if not cfg.get("model"):
        raise LlmConfigError(f"[{name}] model is required")
    common = {
        "model": cfg["model"],
        "max_tokens": cfg.get("max_tokens", 1024),
        "structured": cfg.get("structured"),
    }
    if provider == "anthropic":
        return AnthropicProvider(**common)
    if provider == "ollama":
        return OllamaProvider(**common)
    url_var = cfg.get("base_url_env", "MODAL_LLM_URL")
    key_var = cfg.get("api_key_env", "MODAL_LLM_API_KEY")
    return OpenAICompatProvider(
        **common, base_url=os.environ.get(url_var), api_key=os.environ.get(key_var)
    )


def load_llm_catalog(path: Path | str | None = None) -> dict[str, Callable[[], LlmProvider]]:
    """name -> factory. Env vars are read when the factory runs, so call it after loading .env."""
    config_path = Path(path or os.environ.get("NIM_LLM_CONFIG") or DEFAULT_CONFIG)
    with config_path.open("rb") as f:
        entries = tomllib.load(f)
    catalog: dict[str, Callable[[], LlmProvider]] = {}
    for name, cfg in entries.items():
        if not isinstance(cfg, dict):
            raise LlmConfigError(f"{name!r} must be a [section], not a value")
        _build(name, cfg)  # validate now: a typo should stop startup, not surface mid-game
        catalog[name] = lambda name=name, cfg=cfg: _build(name, cfg)
    return catalog


def get_provider(name: str, path: Path | str | None = None) -> LlmProvider:
    catalog = load_llm_catalog(path)
    try:
        return catalog[name]()
    except KeyError:
        raise KeyError(f"unknown llm {name!r} (use {', '.join(sorted(catalog))})") from None

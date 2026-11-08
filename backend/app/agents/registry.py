"""The agents the server (and the arena) know by name."""

from __future__ import annotations

import logging

from app.agents.base import Agent
from app.agents.llm_agent import LlmAgent
from app.agents.llm_catalog import LLM_CATALOG
from app.agents.nim_optimal import NimOptimalAgent
from app.agents.random_agent import RandomAgent

log = logging.getLogger(__name__)


def build_agents(seed: int | None = None, llms: bool = False) -> dict[str, Agent]:
    """One fresh instance per kind. `seed` makes the random agent repeatable (arena, tests).

    With `llms=True`, every catalog LLM that can run right now is added; the others are skipped
    (logged), so the dropdown only offers agents that work.
    """
    agents: dict[str, Agent] = {"nim_optimal": NimOptimalAgent(), "random": RandomAgent(seed)}
    if llms:
        for name, make_provider in LLM_CATALOG.items():
            provider = make_provider()
            reason = provider.unavailable_reason()
            if reason:
                log.info("LLM agent %s not offered: %s", name, reason)
                continue
            agents[name] = LlmAgent(provider)
    return agents

"""The agents the server (and the arena) know by name."""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.nim_optimal import NimOptimalAgent
from app.agents.random_agent import RandomAgent


def build_agents(seed: int | None = None) -> dict[str, Agent]:
    """One fresh instance per kind. `seed` makes the random agent repeatable (arena, tests)."""
    return {"nim_optimal": NimOptimalAgent(), "random": RandomAgent(seed)}

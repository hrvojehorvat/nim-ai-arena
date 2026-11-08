"""Headless arena: play agents against each other with no server, DB or delay.

    uv run python -m app.arena --a nim_optimal --b random --games 200 --piles 3,4,5

Seats alternate between games (A moves first in even games, B in odd ones), because who moves
first decides most Nim games.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field

from app.agents.base import Agent
from app.agents.registry import build_agents
from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game


@dataclass
class ArenaResult:
    a: str
    b: str
    games: int = 0
    wins: Counter = field(default_factory=Counter)  # "A" / "B"
    wins_moving_first: Counter = field(default_factory=Counter)  # "A" / "B"
    games_moving_first: Counter = field(default_factory=Counter)
    total_moves: int = 0


async def play_game(config: GameConfig, agents: dict[str, Agent]) -> tuple[str, int]:
    """Play one game to the end; returns (winner player id, number of moves)."""
    state = new_game(config)
    while not state.is_over:
        pid = state.current_player.id
        move = await agents[pid].choose_move(state, pid)
        state = apply_move(state, pid, move.pile, move.count)  # raises if an agent cheats
    assert state.winner_id is not None
    return state.winner_id, len(state.moves)


async def run_arena(
    kind_a: str,
    kind_b: str,
    games: int,
    piles: list[int],
    max_take: int | None = None,
    last_stone_loses: bool = False,
    seed: int | None = None,
) -> ArenaResult:
    # Separate instances per side so "random vs random" doesn't share one RNG.
    registry_a, registry_b = build_agents(seed), build_agents(None if seed is None else seed + 1)
    side_agent = {"A": registry_a[kind_a], "B": registry_b[kind_b]}
    result = ArenaResult(a=kind_a, b=kind_b)
    for i in range(games):
        order = ["A", "B"] if i % 2 == 0 else ["B", "A"]
        config = GameConfig(
            piles=piles,
            players=[PlayerSpec(side, side) for side in order],
            max_take=max_take,
            last_stone_loses=last_stone_loses,
        )
        winner, moves = await play_game(config, side_agent)
        result.games += 1
        result.total_moves += moves
        result.wins[winner] += 1
        result.games_moving_first[order[0]] += 1
        if winner == order[0]:
            result.wins_moving_first[winner] += 1
    return result


def format_result(r: ArenaResult) -> str:
    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:5.1f}%" if d else "    -"

    lines = [
        f"{r.games} games, average {r.total_moves / max(r.games, 1):.1f} moves",
        f"{'':20}{'wins':>6}{'win rate':>10}{'when first':>12}",
    ]
    for side, kind in (("A", r.a), ("B", r.b)):
        first = f"{r.wins_moving_first[side]}/{r.games_moving_first[side]}"
        lines.append(
            f"{side + ': ' + kind:20}{r.wins[side]:>6}{pct(r.wins[side], r.games):>10}{first:>12}"
        )
    return "\n".join(lines)


def main() -> None:
    kinds = sorted(build_agents())
    p = argparse.ArgumentParser(description="Play agents against each other and print win rates.")
    p.add_argument("--a", choices=kinds, default="nim_optimal")
    p.add_argument("--b", choices=kinds, default="random")
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--piles", default="3,4,5", help="comma-separated stones per pile")
    p.add_argument("--max-take", type=int, default=None)
    p.add_argument("--last-stone-loses", action="store_true")
    p.add_argument("--seed", type=int, default=None, help="makes random agents repeatable")
    args = p.parse_args()
    piles = [int(x) for x in args.piles.split(",")]
    result = asyncio.run(
        run_arena(
            args.a, args.b, args.games, piles, args.max_take, args.last_stone_loses, args.seed
        )
    )
    print(format_result(result))


if __name__ == "__main__":
    main()

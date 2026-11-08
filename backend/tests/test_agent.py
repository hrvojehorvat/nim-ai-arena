"""Deterministic agent: brute-force every small position and check it plays perfectly."""

import itertools
from functools import cache

import pytest

from app.agents import strategy
from app.agents.nim_optimal import NimOptimalAgent
from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game

pytestmark = pytest.mark.anyio

A, B = PlayerSpec("a", "A"), PlayerSpec("b", "B")


def moves(piles, k):
    for i, size in enumerate(piles):
        for c in range(1, (size if k is None else min(size, k)) + 1):
            yield i, c, piles[:i] + (size - c,) + piles[i + 1 :]


def solver(k, lsl):
    @cache
    def wins(piles: tuple[int, ...]) -> bool:
        """True if the player to move wins with perfect play (independent of strategy.py)."""
        if sum(piles) == 0:
            return lsl  # previous player took the last stone: they won, unless last stone loses
        return any(not wins(nxt) for _, _, nxt in moves(piles, k))

    return wins


BOARDS = [p for n in (1, 2, 3) for p in itertools.product(range(0, 6), repeat=n) if sum(p) > 0]
RULES = [(k, lsl) for k in (None, 1, 2, 3) for lsl in (False, True)]


@pytest.mark.parametrize(("k", "lsl"), RULES)
async def test_agent_plays_perfectly_on_all_small_boards(k, lsl) -> None:
    wins = solver(k, lsl)
    agent = NimOptimalAgent()
    for piles in BOARDS:
        state = new_game(GameConfig(piles=piles, players=[A, B], max_take=k, last_stone_loses=lsl))
        move = await agent.choose_move(state, "a")
        # always legal (apply_move raises otherwise) and always explains itself
        after = apply_move(state, "a", move.pile, move.count)
        assert move.reasoning
        if wins(piles):
            # a winning position must stay winning: opponent is left in a losing one
            assert after.is_over and after.winner_id == "a" or not wins(after.piles), (piles, move)
        # evaluation agrees with the brute-force verdict
        ev = strategy.evaluate(piles, k, lsl)
        assert ev.winning == wins(piles), (piles, k, lsl, ev)


async def test_reasoning_is_readable() -> None:
    state = new_game(GameConfig(piles=[3, 4, 5], players=[A, B]))
    move = await NimOptimalAgent().choose_move(state, "a")
    assert (move.pile, move.count) == (0, 2)
    assert "Nim-sum of [3, 4, 5] is 2" in move.reasoning and "pile 1" in move.reasoning


async def test_big_last_stone_loses_board_falls_back_without_crashing() -> None:
    state = new_game(GameConfig(piles=[30] * 10, players=[A, B], max_take=3, last_stone_loses=True))
    move = await NimOptimalAgent().choose_move(state, "a")
    apply_move(state, "a", move.pile, move.count)
    assert "too big to solve" in move.reasoning

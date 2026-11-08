"""Pure Nim maths for the deterministic agent (no LangGraph, no I/O).

Position = tuple of pile sizes. "Winning" means the player to move can force a win against
best play by the opponent (two-player Nim).

Rules covered:
  * standard (last stone wins), any `max_take`: Grundy value of a pile is `pile % (k+1)`
    (just `pile` when unlimited); XOR them. Non-zero = winning.
  * last stone loses, unlimited: standard Nim, except when every pile is 0/1 (parity flips).
  * last stone loses with `max_take`: no simple formula, so an exact memoised search, capped
    by SEARCH_BUDGET states. Beyond the cap we fall back to standard-rules play, unproven.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from operator import xor
from typing import Literal

Method = Literal["nim_sum", "grundy", "endgame_parity", "search", "approximate"]

SEARCH_BUDGET = 50_000  # max positions explored for last-stone-loses + max_take


class SearchBudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Evaluation:
    method: Method
    winning: bool | None  # None = unknown (approximate play)
    nim_sum: int | None  # XOR of pile values, when that is what the method uses
    values: tuple[int, ...]  # the per-pile values that were XOR-ed (sizes, or size mod k+1)


def pile_value(size: int, max_take: int | None) -> int:
    return size if max_take is None else size % (max_take + 1)


def _values(piles: tuple[int, ...], max_take: int | None) -> tuple[int, ...]:
    return tuple(pile_value(p, max_take) for p in piles)


def _xor_all(values: tuple[int, ...]) -> int:
    return reduce(xor, values, 0)


# ---- last stone loses + max_take: exact search ----


def _search_wins(pos: tuple[int, ...], k: int, memo: dict) -> bool:
    """True if the player to move wins (last stone loses). Empty board = mover wins,
    because the previous player took the last stone."""
    pos = tuple(sorted(p for p in pos if p))
    if not pos:
        return True
    hit = memo.get(pos)
    if hit is not None:
        return hit
    if len(memo) >= SEARCH_BUDGET:
        raise SearchBudgetExceeded
    result = False
    for i, size in enumerate(pos):
        if i and pos[i - 1] == size:
            continue  # identical pile already tried
        for c in range(1, min(size, k) + 1):
            nxt = pos[:i] + (size - c,) + pos[i + 1 :]
            if not _search_wins(nxt, k, memo):
                result = True
                break
        if result:
            break
    memo[pos] = result
    return result


def evaluate(piles: tuple[int, ...], max_take: int | None, last_stone_loses: bool) -> Evaluation:
    values = _values(piles, max_take)
    nim_sum = _xor_all(values)
    if not last_stone_loses:
        method: Method = "nim_sum" if max_take is None else "grundy"
        return Evaluation(method, nim_sum != 0, nim_sum, values)
    if max_take is None:
        if all(p <= 1 for p in piles):
            ones = sum(piles)
            return Evaluation("endgame_parity", ones % 2 == 0, None, values)
        return Evaluation("nim_sum", nim_sum != 0, nim_sum, values)
    try:
        wins = _search_wins(piles, max_take, {})
    except SearchBudgetExceeded:
        return Evaluation("approximate", None, nim_sum, values)
    return Evaluation("search", wins, None, values)


# ---- choosing a move ----


def _normal_winning_move(piles: tuple[int, ...], max_take: int | None) -> tuple[int, int] | None:
    """A move that makes the XOR of pile values zero, if one exists."""
    nim_sum = _xor_all(_values(piles, max_take))
    if nim_sum == 0:
        return None
    modulus = None if max_take is None else max_take + 1
    for i, size in enumerate(piles):
        value = pile_value(size, max_take)
        target = value ^ nim_sum
        if target < value:
            # Unlimited: take `size - target`. Limited: lower the residue by `value - target`
            # (<= max_take), which leaves residue `target`.
            count = size - target if modulus is None else value - target
            return i, count
    return None  # unreachable when nim_sum != 0


def _endgame_parity_move(piles: tuple[int, ...]) -> tuple[int, int] | None:
    """Last stone loses, unlimited. Winning move when the rest is 0/1 piles or one big pile."""
    big = [i for i, p in enumerate(piles) if p > 1]
    if not big:
        return (piles.index(1), 1) if sum(piles) % 2 == 0 and sum(piles) > 0 else None
    if len(big) == 1:
        i = big[0]
        ones = sum(1 for p in piles if p == 1)
        # Leave an ODD number of single stones: the opponent is then forced to take the last.
        return (i, piles[i] - 1) if ones % 2 == 0 else (i, piles[i])
    return _normal_winning_move(piles, None)


def _search_winning_move(piles: tuple[int, ...], k: int) -> tuple[int, int] | None:
    memo: dict = {}
    for i, size in enumerate(piles):
        for c in range(1, min(size, k) + 1):
            nxt = piles[:i] + (size - c,) + piles[i + 1 :]
            if not _search_wins(nxt, k, memo):
                return i, c
    return None


def find_winning_move(
    piles: tuple[int, ...], max_take: int | None, last_stone_loses: bool, evaluation: Evaluation
) -> tuple[int, int] | None:
    """The move to play when `evaluation` says we are winning (or unsure); else None."""
    if evaluation.winning is False:
        return None
    if last_stone_loses and max_take is None:
        return _endgame_parity_move(piles)
    match evaluation.method:
        case "nim_sum" | "grundy" | "approximate":
            return _normal_winning_move(piles, max_take)
        case "endgame_parity":
            return _endgame_parity_move(piles)
        case "search":
            assert max_take is not None
            return _search_winning_move(piles, max_take)
    return None


def stalling_move(piles: tuple[int, ...]) -> tuple[int, int]:
    """Losing (or unclear) position: take one stone from the biggest pile, prolong the game."""
    biggest = max(range(len(piles)), key=lambda i: piles[i])
    return biggest, 1

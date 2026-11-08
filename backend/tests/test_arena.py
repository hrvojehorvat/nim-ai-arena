import pytest

from app.arena import format_result, run_arena

pytestmark = pytest.mark.anyio


async def test_optimal_beats_random_and_seats_alternate() -> None:
    r = await run_arena("nim_optimal", "random", games=40, piles=[3, 4, 5], seed=1)
    assert r.games == 40
    assert r.wins["A"] + r.wins["B"] == 40
    assert r.games_moving_first["A"] == r.games_moving_first["B"] == 20
    # Nim-sum 2: whoever moves first wins against perfect play, and optimal also punishes
    # random mistakes when it moves second, so it should win most games.
    assert r.wins["A"] > r.wins["B"]
    assert r.wins_moving_first["A"] == 20  # optimal never loses from a winning start


async def test_same_seed_same_result() -> None:
    a = await run_arena("random", "random", games=20, piles=[5, 6], seed=7)
    b = await run_arena("random", "random", games=20, piles=[5, 6], seed=7)
    assert a.wins == b.wins and a.total_moves == b.total_moves


async def test_last_stone_loses_with_max_take_runs() -> None:
    r = await run_arena(
        "nim_optimal", "random", games=10, piles=[6, 7], max_take=3, last_stone_loses=True, seed=2
    )
    assert r.games == 10


def test_format_mentions_both_sides() -> None:
    import asyncio

    text = format_result(asyncio.run(run_arena("nim_optimal", "random", 4, [3, 4, 5], seed=0)))
    assert "A: nim_optimal" in text and "B: random" in text


async def test_progress_is_reported_per_game() -> None:
    lines: list[str] = []
    await run_arena("nim_optimal", "random", games=3, piles=[2, 3], seed=1, progress=lines.append)
    assert len(lines) == 3 and lines[0].startswith("game 1/3:")

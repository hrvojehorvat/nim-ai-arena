import pytest

from app.agents.nim_optimal import NimOptimalAgent
from app.agents.random_agent import RandomAgent
from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game

A = PlayerSpec("a", "A")
B = PlayerSpec("b", "B")

pytestmark = pytest.mark.anyio


async def play(agents, config: GameConfig):
    state = new_game(config)
    while not state.is_over:
        pid = state.current_player.id
        move = await agents[pid].choose_move(state, pid)
        state = apply_move(state, pid, move.pile, move.count)  # raises if illegal
    return state


@pytest.mark.parametrize("last_stone_loses", [False, True])
@pytest.mark.parametrize("max_take", [None, 1, 3])
async def test_random_games_are_always_legal(max_take, last_stone_loses) -> None:
    cfg = GameConfig(
        piles=[3, 0, 7, 5], players=[A, B], max_take=max_take, last_stone_loses=last_stone_loses
    )
    for seed in range(20):
        state = await play({"a": RandomAgent(seed), "b": RandomAgent(seed + 100)}, cfg)
        assert state.is_over


async def test_same_seed_same_moves() -> None:
    state = new_game(GameConfig(piles=[5, 6, 7], players=[A, B]))
    m1 = await RandomAgent(42).choose_move(state, "a")
    m2 = await RandomAgent(42).choose_move(state, "a")
    assert m1 == m2
    assert m1.reasoning.startswith("Random:")


async def test_optimal_beats_random_from_a_winning_position() -> None:
    cfg = GameConfig(piles=[3, 4, 5], players=[A, B])  # nim-sum 2, so "a" moving first wins
    for seed in range(30):
        state = await play({"a": NimOptimalAgent(), "b": RandomAgent(seed)}, cfg)
        assert state.winner_id == "a"

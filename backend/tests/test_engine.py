import pytest

from app.game.engine import (
    MAX_PILES,
    MAX_STONES_PER_PILE,
    GameConfig,
    IllegalMoveError,
    InvalidConfigError,
    PlayerSpec,
    apply_move,
    new_game,
)

ALICE = PlayerSpec(id="alice", name="Alice")
BOB = PlayerSpec(id="bob", name="Bob")
CAROL = PlayerSpec(id="carol", name="Carol")


def make_config(piles=(3, 4, 5), players=(ALICE, BOB)) -> GameConfig:
    return GameConfig(piles=list(piles), players=list(players))


# --- config validation ---


def test_valid_config_normalizes_to_tuples() -> None:
    config = make_config()
    assert config.piles == (3, 4, 5)
    assert config.players == (ALICE, BOB)


def test_zero_stone_pile_allowed_if_others_non_empty() -> None:
    assert make_config(piles=(0, 2)).piles == (0, 2)


@pytest.mark.parametrize(
    "piles",
    [
        (),
        (1,) * (MAX_PILES + 1),
        (-1, 3),
        (MAX_STONES_PER_PILE + 1,),
        (0, 0),
        (1.5,),
        (True,),
    ],
)
def test_invalid_piles(piles) -> None:
    with pytest.raises(InvalidConfigError):
        make_config(piles=piles)


def test_too_few_players() -> None:
    with pytest.raises(InvalidConfigError):
        make_config(players=(ALICE,))


def test_duplicate_player_ids() -> None:
    with pytest.raises(InvalidConfigError):
        make_config(players=(ALICE, PlayerSpec(id="alice", name="Other")))


# --- moves ---


def test_new_game_starts_with_first_player() -> None:
    state = new_game(make_config())
    assert state.piles == (3, 4, 5)
    assert state.current_player.id == "alice"
    assert not state.is_over
    assert state.moves == ()


def test_apply_move_updates_piles_and_turn() -> None:
    state = apply_move(new_game(make_config()), "alice", pile=1, count=2)
    assert state.piles == (3, 2, 5)
    assert state.current_player.id == "bob"
    assert state.moves[-1].piles_after == (3, 2, 5)
    assert state.moves[-1].player_id == "alice"


def test_apply_move_does_not_mutate_input() -> None:
    original = new_game(make_config())
    apply_move(original, "alice", pile=0, count=3)
    assert original.piles == (3, 4, 5)
    assert original.moves == ()
    assert original.current_player.id == "alice"


def test_three_player_rotation() -> None:
    state = new_game(make_config(piles=(10,), players=(ALICE, BOB, CAROL)))
    order = []
    for _ in range(4):
        order.append(state.current_player.id)
        state = apply_move(state, state.current_player.id, pile=0, count=1)
    assert order == ["alice", "bob", "carol", "alice"]


@pytest.mark.parametrize(
    ("player", "pile", "count", "reason"),
    [
        ("bob", 0, 1, "not_your_turn"),
        ("alice", 3, 1, "invalid_pile"),
        ("alice", -1, 1, "invalid_pile"),
        ("alice", 0, 0, "invalid_count"),
        ("alice", 0, 4, "invalid_count"),
    ],
)
def test_illegal_moves(player, pile, count, reason) -> None:
    with pytest.raises(IllegalMoveError) as exc:
        apply_move(new_game(make_config()), player, pile, count)
    assert exc.value.reason == reason


def test_cannot_take_from_empty_pile() -> None:
    state = new_game(make_config(piles=(0, 2)))
    with pytest.raises(IllegalMoveError) as exc:
        apply_move(state, "alice", pile=0, count=1)
    assert exc.value.reason == "invalid_count"


def test_last_stone_wins_and_ends_game() -> None:
    state = new_game(make_config(piles=(1, 2)))
    state = apply_move(state, "alice", pile=1, count=2)
    assert not state.is_over
    state = apply_move(state, "bob", pile=0, count=1)
    assert state.is_over
    assert state.winner_id == "bob"
    assert state.piles == (0, 0)


def test_no_moves_after_game_over() -> None:
    state = apply_move(new_game(make_config(piles=(2,))), "alice", pile=0, count=2)
    with pytest.raises(IllegalMoveError) as exc:
        apply_move(state, "bob", pile=0, count=1)
    assert exc.value.reason == "game_over"

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


@pytest.mark.parametrize("n", [0, 1, 3])
def test_exactly_two_players(n: int) -> None:
    players = tuple(PlayerSpec(id=f"p{i}", name=f"P{i}") for i in range(n))
    with pytest.raises(InvalidConfigError):
        make_config(players=players)


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


# --- max_take variant ---


def test_limits_are_10_piles_of_30() -> None:
    assert make_config(piles=(MAX_STONES_PER_PILE,) * MAX_PILES).piles == (30,) * 10
    assert (MAX_PILES, MAX_STONES_PER_PILE) == (10, 30)


def test_max_take_defaults_to_unlimited() -> None:
    state = new_game(make_config(piles=(30,)))
    assert state.config.max_take is None
    assert apply_move(state, "alice", pile=0, count=30).winner_id == "alice"


@pytest.mark.parametrize("max_take", [0, -1, 1.5, True, "3"])
def test_invalid_max_take(max_take) -> None:
    with pytest.raises(InvalidConfigError):
        GameConfig(piles=[3], players=[ALICE, BOB], max_take=max_take)


def test_max_take_limits_count() -> None:
    state = new_game(GameConfig(piles=[10], players=[ALICE, BOB], max_take=3))
    assert apply_move(state, "alice", pile=0, count=3).piles == (7,)
    with pytest.raises(IllegalMoveError) as exc:
        apply_move(state, "alice", pile=0, count=4)
    assert exc.value.reason == "invalid_count"
    assert "max 3 per move" in str(exc.value)


def test_max_take_larger_than_pile_allows_taking_all() -> None:
    state = new_game(GameConfig(piles=[4], players=[ALICE, BOB], max_take=1000))
    assert apply_move(state, "alice", pile=0, count=4).winner_id == "alice"
    with pytest.raises(IllegalMoveError):
        apply_move(state, "alice", pile=0, count=5)


# --- last stone loses (taking the last stone loses) ---


def test_last_stone_loses_last_stone_taker_loses() -> None:
    state = new_game(GameConfig(piles=[1, 1], players=[ALICE, BOB], last_stone_loses=True))
    state = apply_move(state, "alice", 0, 1)
    assert not state.is_over
    state = apply_move(state, "bob", 1, 1)  # bob takes the last stone -> bob loses
    assert state.is_over and state.winner_id == "alice"


def test_standard_game_unchanged_by_default() -> None:
    state = new_game(make_config(piles=(1,)))
    assert apply_move(state, "alice", 0, 1).winner_id == "alice"


def test_last_stone_loses_must_be_bool() -> None:
    with pytest.raises(InvalidConfigError):
        GameConfig(piles=[1], players=[ALICE, BOB], last_stone_loses="yes")  # type: ignore[arg-type]

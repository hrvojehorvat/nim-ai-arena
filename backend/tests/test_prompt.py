import pytest

from app.agents.llm import AgentDecision
from app.agents.prompt import (
    ReplyParseError,
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
    parse_decision,
    to_agent_move,
)
from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game

A = PlayerSpec("a", "Alice")
B = PlayerSpec("b", "Bot", kind="nim_optimal")


def state(**kw):
    return new_game(GameConfig(piles=(3, 0, 5), players=(A, B), **kw))


def test_system_prompt_states_the_rules() -> None:
    assert "LAST stone WINS" in build_system_prompt(state())
    assert "LOSES" in build_system_prompt(state(last_stone_loses=True))
    assert "at most 2" in build_system_prompt(state(max_take=2))
    assert "JSON" in build_system_prompt(
        state()
    )  # needed for guided decoding (see architecture.md)


def test_user_prompt_lists_piles_one_based_with_limits() -> None:
    text = build_user_prompt(state(max_take=2), "a")
    assert "You are Alice." in text
    assert "Pile 1: 3 stones (you may take 1-2)" in text
    assert "Pile 2: 0 stones (empty)" in text
    assert "Moves so far" not in text


def test_user_prompt_shows_history_from_the_players_view() -> None:
    s = apply_move(state(), "a", 2, 4)
    text = build_user_prompt(s, "b")
    assert "opponent took 4 from pile 3 -> [3, 0, 1]" in text
    assert "you took" in build_user_prompt(s, "a")


def test_long_history_is_truncated() -> None:
    s = new_game(GameConfig(piles=(30,), players=(A, B)))
    for _ in range(30):
        s = apply_move(s, s.current_player.id, 0, 1)
    text = build_user_prompt(s, "a")
    assert "10 earlier moves omitted" in text
    assert text.count("took 1 from pile 1") == 20


def test_retry_prompt_includes_the_error() -> None:
    assert "pile 9 does not exist" in build_retry_prompt("pile 9 does not exist")


@pytest.mark.parametrize(
    "reply",
    [
        '{"reasoning": "r", "pile": 2, "count": 3}',
        '```json\n{"reasoning": "r", "pile": 2, "count": 3}\n```',
        'Here is the JSON object: {"reasoning": "r", "pile": 2, "count": 3} Hope it helps!',
        '{"reasoning": "r", "pile": "2", "count": "3"}',  # numbers as strings
        'Note {braces} first. {"reasoning": "r", "pile": 2, "count": 3}',
    ],
)
def test_parse_tolerates_fences_chatter_and_string_numbers(reply) -> None:
    d = parse_decision(reply)
    assert (d.pile, d.count, d.reasoning) == (2, 3, "r")


@pytest.mark.parametrize(
    "reply, fragment",
    [
        ("I think you should take 2 from pile 1.", "no JSON"),
        ("", "no JSON"),
        ('{"reasoning": "r", "pile": 2}', "count"),
        ('{"reasoning": "r", "pile": "two", "count": 1}', "pile"),
        ('{"pile": 1, "count": 1', "no JSON"),  # truncated
    ],
)
def test_parse_errors_say_what_is_wrong(reply, fragment) -> None:
    with pytest.raises(ReplyParseError, match=fragment):
        parse_decision(reply)


def test_to_agent_move_converts_to_zero_based() -> None:
    m = to_agent_move(AgentDecision(reasoning="why", pile=1, count=2))
    assert (m.pile, m.count, m.reasoning) == (0, 2, "why")

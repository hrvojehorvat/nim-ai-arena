"""Agents sitting in matches: same move path as humans, reasoning saved, failures handled."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentMove
from app.agents.nim_optimal import NimOptimalAgent
from app.db.history import PgMatchHistory
from app.db.matches import PgMatchStore
from app.game.engine import GameConfig, PlayerSpec, new_game
from app.game.match import Match, MatchError, MatchManager
from app.main import create_app

pytestmark = pytest.mark.anyio

HUMAN = PlayerSpec("human", "Human")
BOT = PlayerSpec("bot", "Bot", kind="nim_optimal")
BOT2 = PlayerSpec("bot2", "Bot 2", kind="nim_optimal")


def manager(**kw) -> MatchManager:
    return MatchManager(agents={"nim_optimal": NimOptimalAgent()}, **kw)


async def until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting"
        await asyncio.sleep(0.01)


async def play_human_by_default(m: MatchManager, match: Match) -> None:
    """The human always takes 1 stone from the first non-empty pile; agents answer on their own."""
    while not match.state.is_over:
        await until(lambda: match.state.is_over or match.state.current_player.id == "human")
        if match.state.is_over:
            break
        pile = next(i for i, s in enumerate(match.state.piles) if s)
        await m.submit_move(match.id, "human", pile, 1)


async def test_agent_seat_is_joined_and_human_vs_agent_runs_to_the_end() -> None:
    m = manager()
    # nim-sum 0 with the human to move: the human is lost against a perfect agent.
    match = await m.create(GameConfig(piles=[1, 2, 3], players=[HUMAN, BOT]))
    assert match.status == "waiting" and match.joined == {"bot"}
    await m.join(match.id, "human")
    await play_human_by_default(m, match)

    assert match.state.winner_id == "bot"
    for i, mv in enumerate(match.state.moves):
        if mv.player_id == "bot":
            assert match.reasons[i] and i not in match.auto_moves
        else:
            assert i not in match.reasons


async def test_agent_moves_first_from_a_winning_position_and_wins() -> None:
    m = manager()
    match = await m.create(GameConfig(piles=[3, 4, 5], players=[BOT, HUMAN]))
    await m.join(match.id, "human")
    await until(lambda: len(match.state.moves) == 1)  # agent opened without being asked
    await play_human_by_default(m, match)
    assert match.state.winner_id == "bot"


async def test_agent_vs_agent_plays_by_itself() -> None:
    m = manager()
    match = await m.create(GameConfig(piles=[3, 4, 5], players=[BOT, BOT2]))
    assert match.status == "active"  # nobody needs to join
    await until(lambda: match.state.is_over)
    assert match.state.winner_id == "bot"  # first player wins a non-zero nim-sum
    assert len(match.reasons) == len(match.state.moves)


async def test_clients_cannot_move_for_an_agent_seat() -> None:
    m = manager()
    match = await m.create(GameConfig(piles=[3, 4, 5], players=[HUMAN, BOT]))
    await m.join(match.id, "human")
    with pytest.raises(MatchError) as exc:
        await m.submit_move(match.id, "bot", 0, 1)
    assert exc.value.reason == "agent_seat"


async def test_unknown_agent_kind_is_rejected() -> None:
    with pytest.raises(MatchError) as exc:
        await manager().create(
            GameConfig(piles=[3], players=[HUMAN, PlayerSpec("x", "X", kind="wizard")])
        )
    assert exc.value.reason == "unknown_agent"
    with pytest.raises(MatchError):  # no registry at all
        await MatchManager().create(GameConfig(piles=[3], players=[HUMAN, BOT]))


class IllegalAgent:
    async def choose_move(self, state, player_id) -> AgentMove:
        return AgentMove(pile=99, count=99, reasoning="nonsense")


class CrashingAgent:
    async def choose_move(self, state, player_id) -> AgentMove:
        raise RuntimeError("boom")


class StuckAgent:
    async def choose_move(self, state, player_id) -> AgentMove:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


@pytest.mark.parametrize("agent", [IllegalAgent(), CrashingAgent()])
async def test_broken_agent_falls_back_to_a_safe_move(agent) -> None:
    m = MatchManager(agents={"nim_optimal": agent})
    match = await m.create(GameConfig(piles=[0, 3], players=[BOT, HUMAN]))
    await m.join(match.id, "human")
    await until(lambda: len(match.state.moves) >= 1)
    assert match.state.piles == (0, 2)
    assert 0 in match.auto_moves and "failed to produce a legal move" in match.reasons[0]
    await m.close()


async def test_turn_timeout_still_applies_to_a_slow_agent() -> None:
    m = MatchManager(agents={"nim_optimal": StuckAgent()})
    match = await m.create(GameConfig(piles=[3], players=[BOT, HUMAN]), turn_timeout=0.1)
    await m.join(match.id, "human")
    await until(lambda: len(match.state.moves) >= 1)
    assert 0 in match.auto_moves and "Timed out" in match.reasons[0]
    await m.close()


async def test_agent_thinking_does_not_block_the_event_loop() -> None:
    """The graph's nodes are sync; the exact search must not freeze other requests."""
    gaps: list[float] = []

    async def ticker() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    # Big last-stone-loses board: the exact search runs up to its budget before giving up.
    state = new_game(
        GameConfig(piles=[30] * 10, players=[BOT, HUMAN], max_take=3, last_stone_loses=True)
    )
    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.03)
    start = time.perf_counter()
    await NimOptimalAgent().choose_move(state, "bot")
    elapsed = time.perf_counter() - start
    task.cancel()
    assert max(gaps) < max(0.1, elapsed / 2), (max(gaps), elapsed)


# --- database: reasoning is saved and comes back in the replay ---


async def test_reasoning_is_saved_and_replayed(migrated_pool) -> None:
    m = manager(store=PgMatchStore(migrated_pool))
    match = await m.create(GameConfig(piles=[1, 2, 3], players=[HUMAN, BOT]))
    await m.join(match.id, "human")
    await play_human_by_default(m, match)

    replay = await PgMatchHistory(migrated_pool).get_replay(match.id)
    assert replay is not None
    kinds = {p["id"]: p["kind"] for p in replay["players"]}
    assert kinds == {"human": "human", "bot": "nim_optimal"}
    for mv in replay["moves"]:
        if mv["player_id"] == "bot":
            assert mv["reasoning"] and not mv["auto"]
        else:
            assert mv["reasoning"] is None


# --- HTTP API ---


def test_api_human_vs_agent() -> None:
    with TestClient(create_app()) as client:
        r = client.post(
            "/matches",
            json={
                "piles": [1, 2, 3],
                "players": [{"id": "me"}, {"id": "bot", "kind": "nim_optimal"}],
            },
        )
        assert r.status_code == 201
        mid = r.json()["id"]
        assert [p["joined"] for p in r.json()["players"]] == [False, True]
        client.post(f"/matches/{mid}/join", json={"player_id": "me"})

        r = client.post(f"/matches/{mid}/moves", json={"player_id": "bot", "pile": 0, "count": 1})
        assert r.status_code == 403 and r.json()["reason"] == "agent_seat"

        r = client.post(f"/matches/{mid}/moves", json={"player_id": "me", "pile": 2, "count": 1})
        assert r.status_code == 200
        deadline = time.time() + 5
        while len(client.get(f"/matches/{mid}").json()["moves"]) < 2:
            assert time.time() < deadline
            time.sleep(0.02)
        reply = client.get(f"/matches/{mid}").json()["moves"][1]
        assert reply["player_id"] == "bot" and reply["reasoning"]


def test_api_unknown_agent_kind() -> None:
    with TestClient(create_app()) as client:
        r = client.post(
            "/matches",
            json={"piles": [3], "players": [{"id": "a"}, {"id": "b", "kind": "wizard"}]},
        )
        assert r.status_code == 422 and r.json()["reason"] == "unknown_agent"

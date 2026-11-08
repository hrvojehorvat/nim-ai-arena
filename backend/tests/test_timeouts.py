import asyncio

import pytest
from fastapi.testclient import TestClient

from app.game.engine import GameConfig, PlayerSpec, default_move, new_game
from app.game.match import Match, MatchManager
from app.main import create_app

pytestmark = pytest.mark.anyio

PLAYERS = [PlayerSpec("alice", "Alice"), PlayerSpec("bob", "Bob")]


class Recorder:
    """on_change callback that lets tests await the next state change."""

    def __init__(self) -> None:
        self.changes: asyncio.Queue[int] = asyncio.Queue()

    async def __call__(self, match: Match) -> None:
        self.changes.put_nowait(len(match.state.moves))

    async def next_move_count(self, timeout: float = 2.0) -> int:
        return await asyncio.wait_for(self.changes.get(), timeout)


async def start(manager: MatchManager, rec: Recorder, piles, timeout: float | None) -> Match:
    match = await manager.create(GameConfig(piles=piles, players=PLAYERS), turn_timeout=timeout)
    await manager.join(match.id, "alice")
    await manager.join(match.id, "bob")
    assert [await rec.next_move_count(), await rec.next_move_count()] == [0, 0]
    return match


def test_default_move_takes_one_from_first_non_empty() -> None:
    state = new_game(GameConfig(piles=[0, 0, 5, 2], players=PLAYERS))
    assert default_move(state) == (2, 1)


async def test_no_timeout_by_default() -> None:
    rec = Recorder()
    manager = MatchManager(on_change=rec)
    match = await start(manager, rec, [3], None)
    assert match.turn_time_left() is None
    await asyncio.sleep(0.05)
    assert rec.changes.empty()


async def test_timer_not_started_while_waiting() -> None:
    manager = MatchManager()
    match = await manager.create(GameConfig(piles=[3], players=PLAYERS), turn_timeout=0.01)
    await manager.join(match.id, "alice")
    assert match.turn_time_left() is None
    await asyncio.sleep(0.05)
    assert match.state.moves == ()


async def test_timeout_plays_default_move_and_passes_turn() -> None:
    rec = Recorder()
    manager = MatchManager(on_change=rec)
    match = await start(manager, rec, [0, 4], 0.05)
    assert 0 < match.turn_time_left() <= 0.05

    assert await rec.next_move_count() == 1
    move = match.state.moves[0]
    assert (move.player_id, move.pile, move.count) == ("alice", 1, 1)
    assert match.auto_moves == {0}
    assert match.state.current_player.id == "bob"
    await manager.close()


async def test_human_move_resets_timer() -> None:
    rec = Recorder()
    manager = MatchManager(on_change=rec)
    match = await start(manager, rec, [10], 0.1)

    await asyncio.sleep(0.06)
    await manager.submit_move(match.id, "alice", 0, 2)
    assert await rec.next_move_count() == 1
    # Bob now has a fresh 0.1s; the next change is his auto move, not a second one for Alice.
    assert await rec.next_move_count() == 2
    assert match.state.moves[1].player_id == "bob"
    assert match.auto_moves == {1}
    await manager.close()


async def test_timer_stops_when_game_ends() -> None:
    rec = Recorder()
    manager = MatchManager(on_change=rec)
    match = await start(manager, rec, [1], 0.03)

    assert await rec.next_move_count() == 1
    assert match.status == "finished" and match.state.winner_id == "alice"
    assert match.turn_time_left() is None and match._timer is None
    await asyncio.sleep(0.08)
    assert rec.changes.empty()


async def test_close_cancels_timers() -> None:
    rec = Recorder()
    manager = MatchManager(on_change=rec)
    match = await start(manager, rec, [5], 0.05)
    await manager.close()
    await asyncio.sleep(0.1)
    assert rec.changes.empty() and match.state.moves == ()


# --- API / WS level (sync tests; anyio mark not needed) ---


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _create(client: TestClient, **extra) -> dict:
    return client.post(
        "/matches", json={"piles": [1, 2], "players": [{"id": "a"}, {"id": "b"}], **extra}
    )


@pytest.mark.parametrize("bad", [0, -1, 3601, "soon"])
def test_invalid_turn_timeout(client, bad) -> None:
    assert _create(client, turn_timeout=bad).status_code == 422


def test_timeout_exposed_and_auto_move_broadcast(client) -> None:
    r = _create(client, turn_timeout=0.2)
    assert r.status_code == 201
    m = r.json()
    assert m["turn_timeout"] == 0.2 and m["turn_time_left"] is None  # waiting

    with client.websocket_connect(f"/ws/matches/{m['id']}?player=a") as a:
        a.receive_json()
        with client.websocket_connect(f"/ws/matches/{m['id']}?player=b") as b:
            active = a.receive_json()["match"]
            b.receive_json()
            assert active["status"] == "active"
            assert 0 < active["turn_time_left"] <= 0.2

            auto = a.receive_json()["match"]  # nobody moves -> server plays for "a"
            assert auto["moves"][-1] == {
                "player_id": "a",
                "pile": 0,
                "count": 1,
                "piles_after": [0, 2],
                "auto": True,
            }
            assert auto["current_player_id"] == "b"

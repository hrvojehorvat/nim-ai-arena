"""History list and replay endpoints (read from Postgres)."""

import pytest
from fastapi.testclient import TestClient

from app.game.engine import GameConfig, PlayerSpec, apply_move, new_game
from app.main import create_app

pytestmark = pytest.mark.anyio

PLAYERS = [{"id": "alice", "name": "Alice"}, {"id": "bob", "name": "Bob"}]


def create(client: TestClient, piles, **extra) -> str:
    r = client.post("/matches", json={"piles": piles, "players": PLAYERS, **extra})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    for p in ("alice", "bob"):
        assert client.post(f"/matches/{mid}/join", json={"player_id": p}).status_code == 200
    return mid


def move(client: TestClient, mid: str, player: str, pile: int, count: int) -> None:
    r = client.post(
        f"/matches/{mid}/moves", json={"player_id": player, "pile": pile, "count": count}
    )
    assert r.status_code == 200, r.text


async def test_replay_matches_engine(test_db_url) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        mid = create(client, [3, 4], max_take=3)
        for who, pile, count in [("alice", 1, 3), ("bob", 0, 3), ("alice", 1, 1)]:
            move(client, mid, who, pile, count)

        r = client.get(f"/matches/{mid}/replay")
        assert r.status_code == 200
        body = r.json()

    assert body["status"] == "finished" and body["winner_id"] == "alice"
    assert body["initial_piles"] == [3, 4] and body["max_take"] == 3
    assert [(p["id"], p["seat"]) for p in body["players"]] == [("alice", 0), ("bob", 1)]
    assert [m["turn_no"] for m in body["moves"]] == [0, 1, 2]

    # Rebuild the game from the replay alone; every stored snapshot must agree with the engine.
    state = new_game(
        GameConfig(
            piles=body["initial_piles"],
            players=[PlayerSpec(p["id"], p["name"]) for p in body["players"]],
            max_take=body["max_take"],
        )
    )
    for m in body["moves"]:
        state = apply_move(state, m["player_id"], m["pile"], m["count"])
        assert list(state.piles) == m["piles_after"]
    assert state.is_over and state.winner_id == body["winner_id"]


async def test_list_is_newest_first_and_paginated(test_db_url) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        ids = [create(client, [n]) for n in (1, 2, 3)]
        move(client, ids[0], "alice", 0, 1)

        rows = client.get("/matches").json()
        assert [r["id"] for r in rows] == ids[::-1]
        first = rows[-1]
        assert first["status"] == "finished" and first["winner_id"] == "alice"
        assert first["move_count"] == 1 and first["initial_piles"] == [1]
        assert first["player_ids"] == ["alice", "bob"] and first["finished_at"] is not None
        assert rows[0]["status"] == "active" and rows[0]["move_count"] == 0

        page = client.get("/matches", params={"limit": 1, "offset": 1}).json()
        assert [r["id"] for r in page] == [ids[1]]
        assert client.get("/matches", params={"limit": 0}).status_code == 422
        assert client.get("/matches", params={"offset": -1}).status_code == 422


async def test_unknown_match_is_404(test_db_url) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        r = client.get("/matches/nope/replay")
    assert r.status_code == 404 and r.json()["reason"] == "match_not_found"


async def test_unfinished_match_survives_restart_as_abandoned(test_db_url) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        mid = create(client, [5, 5])
        move(client, mid, "alice", 0, 2)
    with TestClient(create_app(database_url=test_db_url)) as client:
        body = client.get(f"/matches/{mid}/replay").json()
    assert body["status"] == "abandoned" and body["winner_id"] is None
    assert [m["piles_after"] for m in body["moves"]] == [[3, 5]]


def test_history_needs_a_database() -> None:
    with TestClient(create_app()) as client:
        for path in ("/matches", "/matches/x/replay"):
            r = client.get(path)
            assert r.status_code == 503 and r.json()["reason"] == "history_unavailable"

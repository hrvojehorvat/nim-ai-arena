import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def create(client: TestClient, piles=(1, 2), players=("alice", "bob")) -> dict:
    r = client.post(
        "/matches", json={"piles": list(piles), "players": [{"id": p} for p in players]}
    )
    assert r.status_code == 201, r.text
    return r.json()


def join_all(client: TestClient, match: dict) -> dict:
    for p in match["players"]:
        r = client.post(f"/matches/{match['id']}/join", json={"player_id": p["id"]})
        assert r.status_code == 200, r.text
    return r.json()


def move(client: TestClient, match_id: str, player: str, pile: int, count: int):
    return client.post(
        f"/matches/{match_id}/moves", json={"player_id": player, "pile": pile, "count": count}
    )


def test_create_match_starts_waiting(client) -> None:
    m = create(client, piles=(3, 4, 5))
    assert m["status"] == "waiting"
    assert m["piles"] == m["initial_piles"] == [3, 4, 5]
    assert m["current_player_id"] == "alice"
    assert [p["name"] for p in m["players"]] == ["alice", "bob"]
    assert all(not p["joined"] for p in m["players"])


@pytest.mark.parametrize(
    "body",
    [
        {"piles": [0, 0], "players": [{"id": "a"}, {"id": "b"}]},
        {"piles": [3], "players": [{"id": "a"}]},
        {"piles": [3], "players": [{"id": "a"}, {"id": "a"}]},
    ],
)
def test_create_invalid_config(client, body) -> None:
    r = client.post("/matches", json=body)
    assert r.status_code == 422
    assert r.json()["reason"] == "invalid_config"


def test_create_rejects_non_int_piles(client) -> None:
    r = client.post("/matches", json={"piles": ["3"], "players": [{"id": "a"}, {"id": "b"}]})
    assert r.status_code == 422  # Pydantic validation


def test_get_unknown_match(client) -> None:
    r = client.get("/matches/nope")
    assert r.status_code == 404
    assert r.json()["reason"] == "match_not_found"


def test_join_flow(client) -> None:
    m = create(client)
    r = client.post(f"/matches/{m['id']}/join", json={"player_id": "alice"})
    assert r.json()["status"] == "waiting"
    r = client.post(f"/matches/{m['id']}/join", json={"player_id": "alice"})
    assert r.status_code == 409 and r.json()["reason"] == "already_joined"
    r = client.post(f"/matches/{m['id']}/join", json={"player_id": "mallory"})
    assert r.status_code == 403 and r.json()["reason"] == "unknown_player"
    r = client.post(f"/matches/{m['id']}/join", json={"player_id": "bob"})
    assert r.json()["status"] == "active"


def test_move_before_start_rejected(client) -> None:
    m = create(client)
    r = move(client, m["id"], "alice", 0, 1)
    assert r.status_code == 409 and r.json()["reason"] == "not_started"


def test_full_game_over_http(client) -> None:
    m = join_all(client, create(client, piles=(1, 2)))
    r = move(client, m["id"], "alice", 1, 2)
    assert r.status_code == 200
    assert r.json()["piles"] == [1, 0]
    assert r.json()["current_player_id"] == "bob"

    r = move(client, m["id"], "bob", 0, 1)
    body = r.json()
    assert body["status"] == "finished"
    assert body["winner_id"] == "bob"
    assert body["current_player_id"] is None
    assert [mv["piles_after"] for mv in body["moves"]] == [[1, 0], [0, 0]]

    r = move(client, m["id"], "alice", 0, 1)
    assert r.status_code == 409 and r.json()["reason"] == "game_over"


@pytest.mark.parametrize(
    ("player", "pile", "count", "status", "reason"),
    [
        ("bob", 0, 1, 409, "not_your_turn"),
        ("alice", 5, 1, 422, "invalid_pile"),
        ("alice", 1, 3, 422, "invalid_count"),
    ],
)
def test_illegal_moves_leave_state_unchanged(client, player, pile, count, status, reason):
    m = join_all(client, create(client, piles=(1, 2)))
    r = move(client, m["id"], player, pile, count)
    assert r.status_code == status and r.json()["reason"] == reason
    assert client.get(f"/matches/{m['id']}").json()["piles"] == [1, 2]

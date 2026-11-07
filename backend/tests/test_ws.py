import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app


@pytest.fixture
def client():
    # Context manager => single event loop shared by all HTTP/WS calls in a test.
    with TestClient(create_app()) as c:
        yield c


def create(client: TestClient, piles=(1, 2), players=("alice", "bob")) -> str:
    r = client.post(
        "/matches", json={"piles": list(piles), "players": [{"id": p} for p in players]}
    )
    assert r.status_code == 201
    return r.json()["id"]


def recv_state(ws) -> dict:
    msg = ws.receive_json()
    assert msg["type"] == "state", msg
    return msg["match"]


def test_unknown_match_rejected(client) -> None:
    with client.websocket_connect("/ws/matches/nope?player=alice") as ws:
        assert ws.receive_json()["reason"] == "match_not_found"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4404


def test_unknown_player_rejected(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}?player=mallory") as ws:
        assert ws.receive_json()["reason"] == "unknown_player"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403


def test_connect_joins_and_full_game_broadcasts(client) -> None:
    mid = create(client, piles=(1, 2))
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        assert recv_state(a)["status"] == "waiting"
        with client.websocket_connect(f"/ws/matches/{mid}?player=bob") as b:
            assert recv_state(a)["status"] == "active"
            assert recv_state(b)["status"] == "active"

            a.send_json({"type": "move", "pile": 1, "count": 2})
            for ws in (a, b):
                m = recv_state(ws)
                assert m["piles"] == [1, 0] and m["current_player_id"] == "bob"

            b.send_json({"type": "move", "pile": 0, "count": 1})
            for ws in (a, b):
                m = recv_state(ws)
                assert m["status"] == "finished" and m["winner_id"] == "bob"
                assert ws.receive_json() == {"type": "game_over", "winner_id": "bob"}


def test_illegal_move_errors_only_sender(client) -> None:
    mid = create(client, piles=(1, 2))
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        recv_state(a)
        with client.websocket_connect(f"/ws/matches/{mid}?player=bob") as b:
            recv_state(a), recv_state(b)

            b.send_json({"type": "move", "pile": 0, "count": 1})
            assert b.receive_json()["reason"] == "not_your_turn"

            # Alice's next frame is the result of her own move, not Bob's error.
            a.send_json({"type": "move", "pile": 0, "count": 1})
            assert recv_state(a)["piles"] == [0, 2]
            assert recv_state(b)["piles"] == [0, 2]


def test_bad_message(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        recv_state(a)
        a.send_text("not json")
        assert a.receive_json()["reason"] == "bad_message"
        a.send_json({"type": "move", "pile": "0", "count": 1})
        assert a.receive_json()["reason"] == "bad_message"


def test_move_before_everyone_joined(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        recv_state(a)
        a.send_json({"type": "move", "pile": 0, "count": 1})
        assert a.receive_json()["reason"] == "not_started"


def test_http_move_is_broadcast_to_sockets(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        recv_state(a)
        client.post(f"/matches/{mid}/join", json={"player_id": "bob"})
        assert recv_state(a)["status"] == "active"
        client.post(f"/matches/{mid}/moves", json={"player_id": "alice", "pile": 1, "count": 1})
        assert recv_state(a)["piles"] == [1, 1]


def test_spectator_sees_updates_but_cannot_move(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}") as s:
        assert recv_state(s)["status"] == "waiting"
        s.send_json({"type": "move", "pile": 0, "count": 1})
        assert s.receive_json()["reason"] == "spectator"
        client.post(f"/matches/{mid}/join", json={"player_id": "alice"})
        assert recv_state(s)["players"][0]["joined"] is True


def test_reconnect_keeps_seat(client) -> None:
    mid = create(client)
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        recv_state(a)
    with client.websocket_connect(f"/ws/matches/{mid}?player=alice") as a:
        m = recv_state(a)
        assert m["players"][0]["joined"] is True

from fastapi.testclient import TestClient

from app.main import create_app


def test_agent_catalog_lists_registered_agents() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/agents")
    assert r.status_code == 200
    agents = {a["name"]: a["description"] for a in r.json()}
    assert set(agents) >= {"nim_optimal", "random"}
    assert all(desc for desc in agents.values())


def test_defaults_report_the_server_agent_move_delay(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MOVE_DELAY", "2.5")
    with TestClient(create_app()) as client:
        r = client.get("/defaults")
    assert r.status_code == 200
    assert r.json() == {"agent_move_delay": 2.5}

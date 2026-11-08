from fastapi.testclient import TestClient

from app.main import create_app


def test_agent_catalog_lists_registered_agents() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/agents")
    assert r.status_code == 200
    agents = {a["name"]: a["description"] for a in r.json()}
    assert set(agents) >= {"nim_optimal", "random"}
    assert all(desc for desc in agents.values())

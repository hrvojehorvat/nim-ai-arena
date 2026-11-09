from fastapi.testclient import TestClient

from app.main import create_app


def test_serves_built_frontend_when_configured(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<h1>nim</h1>")
    (tmp_path / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    monkeypatch.setenv("NIM_LLMS", "0")
    with TestClient(create_app()) as client:
        assert "<h1>nim</h1>" in client.get("/").text
        assert client.get("/app.js").status_code == 200
        # API routes are registered first, so they still win over the static mount.
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/agents").status_code == 200


def test_no_frontend_in_development(monkeypatch):
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    monkeypatch.setenv("NIM_LLMS", "0")
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 404

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's shell DATABASE_URL must never leak into tests that don't ask for a DB.
    monkeypatch.delenv("DATABASE_URL", raising=False)

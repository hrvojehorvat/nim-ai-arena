"""Shared fixtures. DB fixtures need Postgres (`docker compose up -d`) and skip without it.

They use a throwaway database (`nim_arena_test`) so dev data is never touched.
"""

import os

import asyncpg
import pytest

from app.db.pool import create_pool, run_migrations


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's shell DATABASE_URL must never leak into tests that don't ask for a DB.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Tests shouldn't wait for the human-friendly pause between agent moves.
    monkeypatch.setenv("AGENT_MOVE_DELAY", "0")
    monkeypatch.setenv("NIM_LLMS", "0")  # no LLM agents (and no localhost probes) in tests


ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://nim:nim@localhost:5432/postgres"
)
TEST_DB = "nim_arena_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"


@pytest.fixture
async def test_db_url() -> str:
    try:
        admin = await asyncpg.connect(ADMIN_URL, timeout=2)
    except (OSError, asyncpg.PostgresError):
        pytest.skip("Postgres not reachable (run `docker compose up -d`)")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await admin.close()
    return TEST_URL


@pytest.fixture
async def pool(test_db_url: str):
    p = await create_pool(test_db_url)
    yield p
    await p.close()


@pytest.fixture
async def migrated_pool(pool):
    await run_migrations(pool)
    return pool

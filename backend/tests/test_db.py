"""Database tests. They need Postgres (`docker compose up -d`) and skip if it's unreachable.

They run in a throwaway database (`nim_arena_test`) so dev data is never touched.
"""

from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.db.pool import MIGRATIONS_DIR, run_migrations
from app.main import create_app

pytestmark = pytest.mark.anyio


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql)


async def test_applies_in_order_and_records_versions(pool, tmp_path: Path) -> None:
    write(tmp_path, "0002_b.sql", "INSERT INTO t VALUES ('b');")
    write(tmp_path, "0001_a.sql", "CREATE TABLE t (v text);")

    assert await run_migrations(pool, tmp_path) == ["0001_a.sql", "0002_b.sql"]

    assert await pool.fetchval("SELECT count(*) FROM t") == 1
    versions = [
        r["version"]
        for r in await pool.fetch("SELECT version FROM schema_migrations ORDER BY version")
    ]
    assert versions == ["0001_a.sql", "0002_b.sql"]


async def test_rerun_is_a_noop_and_new_files_are_picked_up(pool, tmp_path: Path) -> None:
    write(tmp_path, "0001_a.sql", "CREATE TABLE t (v text);")
    assert await run_migrations(pool, tmp_path) == ["0001_a.sql"]
    assert await run_migrations(pool, tmp_path) == []

    write(tmp_path, "0002_b.sql", "ALTER TABLE t ADD COLUMN w text;")
    assert await run_migrations(pool, tmp_path) == ["0002_b.sql"]


async def test_failed_migration_rolls_back_and_is_retried(pool, tmp_path: Path) -> None:
    write(tmp_path, "0001_ok.sql", "CREATE TABLE t (v text);")
    write(tmp_path, "0002_bad.sql", "CREATE TABLE half (v text); SELECT 1/0;")

    with pytest.raises(asyncpg.PostgresError):
        await run_migrations(pool, tmp_path)

    assert await pool.fetchval("SELECT to_regclass('half')") is None  # rolled back
    done = [r["version"] for r in await pool.fetch("SELECT version FROM schema_migrations")]
    assert done == ["0001_ok.sql"]  # earlier migration kept, failed one not recorded

    write(tmp_path, "0002_bad.sql", "CREATE TABLE half (v text);")  # fixed
    assert await run_migrations(pool, tmp_path) == ["0002_bad.sql"]


async def test_real_migrations_directory_applies_cleanly(pool) -> None:
    await run_migrations(pool, MIGRATIONS_DIR)
    assert await run_migrations(pool, MIGRATIONS_DIR) == []


async def test_app_lifespan_opens_pool_and_health_reports_db(test_db_url: str) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        assert client.get("/health").json() == {"status": "ok", "db": "ok"}
        assert client.app.state.db is not None
    # pool closed on shutdown
    assert client.app.state.db.is_closing()

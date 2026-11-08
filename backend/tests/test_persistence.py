"""Match history is written through to Postgres as the game is played."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.matches import PgMatchStore
from app.game.engine import GameConfig, IllegalMoveError, PlayerSpec
from app.game.match import Match, MatchError, MatchManager, NullMatchStore, StorageError
from app.main import create_app

pytestmark = pytest.mark.anyio

PLAYERS = [PlayerSpec("alice", "Alice"), PlayerSpec("bob", "Bob")]


async def new_manager(pool, **kw) -> MatchManager:
    return MatchManager(store=PgMatchStore(pool), **kw)


async def start(manager: MatchManager, piles, **kw) -> Match:
    match = await manager.create(GameConfig(piles=piles, players=PLAYERS, **kw))
    await manager.join(match.id, "alice")
    await manager.join(match.id, "bob")
    return match


async def match_row(pool, match_id: str):
    return await pool.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)


async def test_create_saves_config_and_seats(migrated_pool) -> None:
    manager = await new_manager(migrated_pool)
    match = await manager.create(
        GameConfig(piles=[3, 4], players=PLAYERS, max_take=2), turn_timeout=15
    )

    row = await match_row(migrated_pool, match.id)
    assert row["status"] == "waiting"
    assert row["turn_timeout"] == 15
    assert row["winner_id"] is None and row["finished_at"] is None
    import json

    assert json.loads(row["config"]) == {"piles": [3, 4], "max_take": 2, "last_stone_loses": False}
    seats = await migrated_pool.fetch(
        "SELECT seat, player_id, name, kind FROM match_players WHERE match_id = $1 ORDER BY seat",
        match.id,
    )
    assert [tuple(s.values()) for s in seats] == [
        (0, "alice", "Alice", "human"),
        (1, "bob", "Bob", "human"),
    ]


async def test_status_follows_lifecycle_and_moves_are_saved(migrated_pool) -> None:
    manager = await new_manager(migrated_pool)
    match = await manager.create(GameConfig(piles=[1, 2], players=PLAYERS))
    await manager.join(match.id, "alice")
    assert (await match_row(migrated_pool, match.id))["status"] == "waiting"
    await manager.join(match.id, "bob")
    assert (await match_row(migrated_pool, match.id))["status"] == "active"

    await manager.submit_move(match.id, "alice", 1, 2)
    row = await match_row(migrated_pool, match.id)
    assert row["status"] == "active" and row["finished_at"] is None

    await manager.submit_move(match.id, "bob", 0, 1)
    row = await match_row(migrated_pool, match.id)
    assert row["status"] == "finished" and row["winner_id"] == "bob"
    assert row["finished_at"] is not None

    moves = await migrated_pool.fetch(
        "SELECT turn_no, player_id, pile, count, piles_after, auto FROM moves "
        "WHERE match_id = $1 ORDER BY turn_no",
        match.id,
    )
    assert [tuple(m.values()) for m in moves] == [
        (0, "alice", 1, 2, [1, 0], False),
        (1, "bob", 0, 1, [0, 0], False),
    ]


async def test_illegal_move_saves_nothing(migrated_pool) -> None:
    manager = await new_manager(migrated_pool)
    match = await start(manager, [3])
    with pytest.raises(IllegalMoveError):
        await manager.submit_move(match.id, "bob", 0, 1)  # not bob's turn
    with pytest.raises(IllegalMoveError):
        await manager.submit_move(match.id, "alice", 0, 9)  # too many
    assert await migrated_pool.fetchval("SELECT count(*) FROM moves") == 0


async def test_timeout_auto_move_is_saved_with_flag(migrated_pool) -> None:
    changed = asyncio.Event()

    async def on_change(match: Match) -> None:
        if match.state.moves:
            changed.set()

    manager = MatchManager(on_change=on_change, store=PgMatchStore(migrated_pool))
    match = await manager.create(GameConfig(piles=[0, 4], players=PLAYERS), turn_timeout=0.05)
    await manager.join(match.id, "alice")
    await manager.join(match.id, "bob")
    await asyncio.wait_for(changed.wait(), 2)
    await manager.close()

    row = await migrated_pool.fetchrow(
        "SELECT player_id, pile, count, auto FROM moves WHERE match_id = $1 AND turn_no = 0",
        match.id,
    )
    assert tuple(row.values()) == ("alice", 1, 1, True)


async def test_abandon_unfinished_marks_only_open_matches(migrated_pool) -> None:
    manager = await new_manager(migrated_pool)
    waiting = await manager.create(GameConfig(piles=[1], players=PLAYERS))
    active = await start(manager, [2])
    done = await start(manager, [1])
    await manager.submit_move(done.id, "alice", 0, 1)

    assert await PgMatchStore(migrated_pool).abandon_unfinished() == 2

    statuses = {
        m.id: (await match_row(migrated_pool, m.id))["status"] for m in (waiting, active, done)
    }
    assert statuses == {waiting.id: "abandoned", active.id: "abandoned", done.id: "finished"}


# --- failure handling (no database needed) ---


class FailingStore(NullMatchStore):
    def __init__(self) -> None:
        self.fail = False

    async def record_move(self, *args, **kwargs) -> None:
        if self.fail:
            raise StorageError("db down")

    async def set_status(self, *args, **kwargs) -> None:
        if self.fail:
            raise StorageError("db down")

    async def create(self, match) -> None:
        if self.fail:
            raise StorageError("db down")


async def test_failed_save_rejects_move_and_leaves_state_unchanged() -> None:
    store = FailingStore()
    manager = MatchManager(store=store)
    match = await start(manager, [3])

    store.fail = True
    with pytest.raises(MatchError) as exc:
        await manager.submit_move(match.id, "alice", 0, 1)
    assert exc.value.reason == "storage_error"
    assert match.state.piles == (3,) and match.state.moves == ()

    store.fail = False  # recovers: same move now works
    await manager.submit_move(match.id, "alice", 0, 1)
    assert match.state.piles == (2,)


async def test_failed_save_on_create_and_final_join() -> None:
    store = FailingStore()
    manager = MatchManager(store=store)

    store.fail = True
    with pytest.raises(MatchError) as exc:
        await manager.create(GameConfig(piles=[3], players=PLAYERS))
    assert exc.value.reason == "storage_error"

    store.fail = False
    match = await manager.create(GameConfig(piles=[3], players=PLAYERS))
    await manager.join(match.id, "alice")
    store.fail = True
    with pytest.raises(MatchError):
        await manager.join(match.id, "bob")  # would activate the match; not saved -> not joined
    assert "bob" not in match.joined and match.status == "waiting"


async def test_failed_auto_move_is_retried() -> None:
    store = FailingStore()
    manager = MatchManager(store=store)
    match = await manager.create(GameConfig(piles=[5], players=PLAYERS), turn_timeout=0.05)
    await manager.join(match.id, "alice")
    await manager.join(match.id, "bob")

    store.fail = True
    await asyncio.sleep(0.12)  # at least one auto-move attempt fails and is not applied
    assert match.state.moves == () and match.status == "active"

    store.fail = False  # storage recovers: a later attempt succeeds
    for _ in range(20):
        if match.state.moves:
            break
        await asyncio.sleep(0.05)
    assert len(match.state.moves) >= 1 and 0 in match.auto_moves
    await manager.close()


# --- through the real app ---


async def test_http_game_is_persisted_and_survives_restart(pool, test_db_url: str) -> None:
    with TestClient(create_app(database_url=test_db_url)) as client:
        r = client.post(
            "/matches",
            json={"piles": [1, 2], "players": [{"id": "alice"}, {"id": "bob"}], "max_take": 5},
        )
        assert r.status_code == 201
        mid = r.json()["id"]
        for p in ("alice", "bob"):
            client.post(f"/matches/{mid}/join", json={"player_id": p})
        client.post(f"/matches/{mid}/moves", json={"player_id": "alice", "pile": 1, "count": 2})

    async def state() -> tuple[str, int]:
        row = await pool.fetchrow("SELECT status FROM matches WHERE id = $1", mid)
        n = await pool.fetchval("SELECT count(*) FROM moves WHERE match_id = $1", mid)
        return row["status"], n

    assert await state() == ("active", 1)  # unfinished when the server stopped
    with TestClient(create_app(database_url=test_db_url)):
        pass  # on startup the unreachable match is marked abandoned
    assert await state() == ("abandoned", 1)

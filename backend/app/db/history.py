"""Read side of match history: listing past matches and fetching a replay."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg

from app.game.match import StorageError

_DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)


class PgMatchHistory:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_matches(self, limit: int, offset: int) -> list[dict[str, Any]]:
        """Newest first. Each item is a summary; use `get_replay` for the moves."""
        try:
            rows = await self._pool.fetch(
                """
                SELECT m.id, m.status, m.winner_id, m.created_at, m.finished_at, m.config,
                       (SELECT count(*) FROM moves mv WHERE mv.match_id = m.id) AS move_count,
                       (SELECT array_agg(p.player_id ORDER BY p.seat)
                          FROM match_players p WHERE p.match_id = m.id) AS player_ids
                FROM matches m
                ORDER BY m.created_at DESC, m.id
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e
        out = []
        for r in rows:
            config = json.loads(r["config"])
            out.append(
                {
                    "id": r["id"],
                    "status": r["status"],
                    "winner_id": r["winner_id"],
                    "created_at": r["created_at"],
                    "finished_at": r["finished_at"],
                    "initial_piles": config["piles"],
                    "max_take": config["max_take"],
                    "last_stone_loses": config.get("last_stone_loses", False),
                    "player_ids": r["player_ids"] or [],
                    "move_count": r["move_count"],
                }
            )
        return out

    async def get_replay(self, match_id: str) -> dict[str, Any] | None:
        """Everything needed to replay a match, or None if it doesn't exist."""
        try:
            async with self._pool.acquire() as conn, conn.transaction(isolation="repeatable_read"):
                m = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
                if m is None:
                    return None
                players = await conn.fetch(
                    "SELECT seat, player_id, name, kind FROM match_players "
                    "WHERE match_id = $1 ORDER BY seat",
                    match_id,
                )
                moves = await conn.fetch(
                    "SELECT turn_no, player_id, pile, count, piles_after, auto, reasoning "
                    "FROM moves "
                    "WHERE match_id = $1 ORDER BY turn_no",
                    match_id,
                )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e
        config = json.loads(m["config"])
        created_at: datetime = m["created_at"]
        return {
            "id": m["id"],
            "status": m["status"],
            "winner_id": m["winner_id"],
            "created_at": created_at,
            "finished_at": m["finished_at"],
            "turn_timeout": m["turn_timeout"],
            "initial_piles": config["piles"],
            "max_take": config["max_take"],
            "last_stone_loses": config.get("last_stone_loses", False),
            "players": [
                {"id": p["player_id"], "name": p["name"], "kind": p["kind"], "seat": p["seat"]}
                for p in players
            ],
            "moves": [dict(mv) for mv in moves],
        }

"""PostgreSQL implementation of the MatchStore interface (see app.game.match)."""

from __future__ import annotations

import json

import asyncpg

from app.game.engine import Move
from app.game.match import Match, MatchStatus, StorageError

_DB_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)


class PgMatchStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, match: Match) -> None:
        config = match.state.config
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO matches (id, config, turn_timeout, status)
                    VALUES ($1, $2::jsonb, $3, $4)
                    """,
                    match.id,
                    json.dumps(
                        {
                            "piles": list(config.piles),
                            "max_take": config.max_take,
                            "last_stone_loses": config.last_stone_loses,
                        }
                    ),
                    match.turn_timeout,
                    match.status,
                )
                await conn.executemany(
                    """
                    INSERT INTO match_players (match_id, seat, player_id, name, kind)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    [
                        (match.id, seat, p.id, p.name, p.kind)
                        for seat, p in enumerate(config.players)
                    ],
                )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e

    async def set_status(self, match_id: str, status: MatchStatus) -> None:
        try:
            await self._pool.execute(
                "UPDATE matches SET status = $2 WHERE id = $1", match_id, status
            )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e

    async def record_move(
        self,
        match_id: str,
        turn_no: int,
        move: Move,
        auto: bool,
        status: MatchStatus,
        winner_id: str | None,
        reasoning: str | None = None,
    ) -> None:
        """Insert the move and update the match row atomically."""
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO moves
                        (match_id, turn_no, player_id, pile, count, piles_after, auto, reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    match_id,
                    turn_no,
                    move.player_id,
                    move.pile,
                    move.count,
                    list(move.piles_after),
                    auto,
                    reasoning,
                )
                await conn.execute(
                    """
                    UPDATE matches
                    SET status = $2, winner_id = $3,
                        finished_at = CASE WHEN $2 = 'finished' THEN now() ELSE finished_at END
                    WHERE id = $1
                    """,
                    match_id,
                    status,
                    winner_id,
                )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e

    async def abandon_unfinished(self) -> int:
        """Matches live in memory, so after a restart any waiting/active match is unreachable."""
        try:
            result = await self._pool.execute(
                "UPDATE matches SET status = 'abandoned' WHERE status IN ('waiting', 'active')"
            )
        except _DB_ERRORS as e:
            raise StorageError(str(e)) from e
        return int(result.split()[-1])  # "UPDATE <n>"

"""Connection-pool helper for Phase 1b Postgres.

Phase 1b WS1, Task 1.3. Single module-level pool, dict-row cursors so
tests can index results by column name. Vector type registration runs
on each pooled connection so pgvector returns numpy arrays instead of
strings (used in WS3 onwards).

Usage:
    from db.connection import get_connection

    with get_connection() as conn:
        rows = conn.execute("SELECT 1 AS x").fetchall()
        assert rows[0]["x"] == 1
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_POOL: ConnectionPool | None = None
_POOL_LOCK = Lock()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy db/.env.example to .env.local and "
            "source it, or pass DATABASE_URL inline."
        )
    return url


def _configure_connection(conn: psycopg.Connection[Any]) -> None:
    """Per-connection setup: register the pgvector adapter so vector(n) round-trips
    cleanly to numpy arrays. The pgvector package's psycopg integration is
    no-op when the `vector` extension hasn't been created yet (e.g. tests that
    only touch the agencies table), so this is safe to call unconditionally.
    """
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except psycopg.errors.UndefinedObject:
        # `vector` extension not yet installed. Future WS3 calls will re-register
        # once the migrations have been applied. Tests targeting WS1-only state
        # (no vector column queried) still work.
        pass


def _get_pool() -> ConnectionPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ConnectionPool(
                conninfo=_database_url(),
                min_size=1,
                max_size=5,
                kwargs={"row_factory": dict_row},
                configure=_configure_connection,
                # Explicit open=True silences the psycopg_pool 3.3.x deprecation
                # warning ("the default for the 'open' parameter will become
                # 'False' in a future release"). We rely on eager pool open here
                # so the first get_connection() call doesn't hide a connection
                # error inside a lazy-init path.
                open=True,
                # timeout=5s makes pool init fail loudly if the DB is unreachable
                # rather than hanging the test runner for 30 seconds.
                timeout=5.0,
            )
    return _POOL


@contextmanager
def get_connection() -> Iterator[psycopg.Connection[Any]]:
    """Yield a pooled connection. Auto-commits on exit unless an exception
    propagates, in which case the pool rolls back.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    """Close the module-level pool. Useful for test teardown / clean shutdowns."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
            _POOL = None

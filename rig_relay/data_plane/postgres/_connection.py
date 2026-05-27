"""PostgreSQL connection management with psycopg 3.

Connection lifecycle:
  - autocommit=True prevents "idle in transaction" states
  - Transaction blocks via ``with conn.transaction()`` for atomic work
  - Explicit rollback on any database error before further operations
  - Connections are NOT pooled in the foundation slice (pool deferred)
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._config import PostgresConnectionConfig


class PostgresConnectionError(Exception):
    """Raised when PostgreSQL connection cannot be established."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class PostgresQueryError(Exception):
    """Raised when a PostgreSQL query fails."""

    def __init__(self, message: str, query: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.query = query
        self.detail = detail


def connect(config: PostgresConnectionConfig) -> Connection:
    """Create a psycopg connection from typed configuration.

    Uses autocommit=True by default to prevent idle-in-transaction states.
    The connection string is the canonical psycopg DSN format.

    Raises:
        PostgresConnectionError: If connection fails (unavailable, bad auth, etc.)
    """
    try:
        dsn = config.build_dsn()
        conn = psycopg.connect(dsn, autocommit=config.autocommit)
        logger.debug(
            "PostgreSQL connected to %s:%s/%s as %s",
            config.host,
            config.port,
            config.dbname,
            config.user,
        )
        return conn
    except psycopg.OperationalError as e:
        raise PostgresConnectionError(
            f"PostgreSQL unavailable at {config.host}:{config.port}/{config.dbname}",
            detail=str(e),
        ) from e
    except psycopg.Error as e:
        raise PostgresConnectionError(
            f"PostgreSQL connection failed for {config.host}:{config.port}/{config.dbname}",
            detail=str(e),
        ) from e


def check_connectivity(config: PostgresConnectionConfig) -> dict[str, Any]:
    """Check PostgreSQL connectivity and return a status report.

    Does NOT leave a persistent connection open.

    Returns:
        Dict with ``connected`` (bool), ``server_version``, ``dbname``,
        ``error`` (if any), and ``latency_ms``.
    """
    import time

    result: dict[str, Any] = {
        "connected": False,
        "server_version": "",
        "dbname": config.dbname,
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "error": None,
        "latency_ms": 0,
    }

    try:
        start = time.monotonic()
        conn = connect(config)
        elapsed = time.monotonic() - start

        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
            if row:
                result["server_version"] = row[0]

        conn.close()

        result["connected"] = True
        result["latency_ms"] = round(elapsed * 1000, 1)
    except PostgresConnectionError as e:
        result["error"] = str(e)
        if e.detail:
            result["error_detail"] = e.detail
    except Exception as e:
        result["error"] = str(e)

    return result


@contextmanager
def transactional_cursor(conn: Connection) -> Generator[psycopg.Cursor, None, None]:
    """Yield a cursor within an explicit transaction block.

    On successful exit: commits.
    On exception: rolls back and re-raises.

    Usage:
        with transactional_cursor(conn) as cur:
            cur.execute(...)
    """
    with conn.transaction():
        with conn.cursor() as cur:
            yield cur

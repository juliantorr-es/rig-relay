"""Test fixtures for real PostgreSQL data plane tests.

Creates a disposable PostgreSQL database per test session, runs migrations,
and drops the database on teardown.

Requires a running PostgreSQL instance accessible with the current user.
Connection uses the libpq default (local socket/peer auth) by default.
"""

from __future__ import annotations

from collections.abc import Generator
import secrets
import string

import psycopg
from psycopg import Connection, sql as psql
from pydantic import SecretStr
import pytest

from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._connection import connect
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore


def _random_db_name(prefix: str = "rig_test") -> str:
    """Generate a random database name for test isolation."""
    suffix = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
    )
    return f"{prefix}_{suffix}"


@pytest.fixture(scope="session")
def pg_super_conn() -> Generator[Connection, None, None]:
    """Connection to the postgres database for creating/dropping test databases."""
    conn = psycopg.connect(dbname="postgres", autocommit=True)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def test_db_name(pg_super_conn: Connection) -> Generator[str, None, None]:
    """Create a disposable test database and return its name."""
    db_name = _random_db_name("rig_test_t2")

    with pg_super_conn.cursor() as cur:
        cur.execute(psql.SQL("CREATE DATABASE {}").format(psql.Identifier(db_name)))

    yield db_name

    with pg_super_conn.cursor() as cur:
        cur.execute(
            psql.SQL(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s"
            ),
            (db_name,),
        )
        cur.execute(psql.SQL("DROP DATABASE {}").format(psql.Identifier(db_name)))


@pytest.fixture
def pg_config(test_db_name: str) -> PostgresConnectionConfig:
    """Postgres connection config pointing to the disposable test database.

    Uses the libpq default connection (local Unix socket with peer auth)
    by leaving host and user empty. Override with PGHOST/PGUSER env vars
    if a TCP connection is needed.
    """
    return PostgresConnectionConfig(
        host="",
        port=5432,
        dbname=test_db_name,
        user="",
        password=SecretStr(""),
        schema_name="operational",
        autocommit=True,
    )


@pytest.fixture
def pg_conn(pg_config: PostgresConnectionConfig) -> Generator[Connection, None, None]:
    """Direct psycopg connection to the test database."""
    conn = connect(pg_config)
    yield conn
    if not conn.closed:
        conn.close()


@pytest.fixture
def migrated_store(
    pg_config: PostgresConnectionConfig,
) -> Generator[PostgresOperationalProjectionStore, None, None]:
    """Store with migrations already applied."""
    store = PostgresOperationalProjectionStore(pg_config)
    store.ensure_migrated()
    yield store
    store.close()

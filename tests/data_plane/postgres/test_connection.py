"""PostgreSQL connection tests — real database connectivity."""

from __future__ import annotations

import pytest

from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._connection import (
    PostgresConnectionError,
    check_connectivity,
    connect,
    transactional_cursor,
)


class TestConnection:
    """Connection establishment and refusal tests."""

    def test_connect_to_real_pg(self, pg_conn, pg_config) -> None:
        """Connect to a real PostgreSQL instance and verify."""
        assert pg_conn is not None
        assert not pg_conn.closed
        assert pg_conn.info.dbname == pg_config.dbname

    def test_connect_refused_bad_host(self) -> None:
        """Connection to an unreachable host should raise PostgresConnectionError."""
        config = PostgresConnectionConfig(
            host="192.0.2.1", port=5432, dbname="nonexistent", connect_timeout=2
        )
        with pytest.raises(PostgresConnectionError):
            connect(config)

    def test_connect_refused_bad_port(self) -> None:
        """Connection to a non-listening port should raise."""
        config = PostgresConnectionConfig(
            host="127.0.0.1", port=54321, dbname="postgres", connect_timeout=2
        )
        with pytest.raises(PostgresConnectionError):
            connect(config)

    def test_check_connectivity_success(self, pg_config) -> None:
        """Health check against real PG returns connected status."""
        result = check_connectivity(pg_config)
        assert result["connected"] is True
        assert result["dbname"] == pg_config.dbname
        assert result["latency_ms"] > 0
        assert "PostgreSQL" in result["server_version"]

    def test_check_connectivity_failure(self) -> None:
        """Health check against unreachable host returns disconnected."""
        config = PostgresConnectionConfig(
            host="192.0.2.1", port=5432, connect_timeout=2
        )
        result = check_connectivity(config)
        assert result["connected"] is False
        assert result["error"] is not None

    def test_transactional_cursor_commits(self, pg_conn) -> None:
        """Transaction context commits on success."""
        with transactional_cursor(pg_conn) as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1

    def test_transactional_cursor_rolls_back(self, pg_conn, migrated_store) -> None:
        """Transaction context rolls back on failure."""
        try:
            with transactional_cursor(pg_conn) as cur:
                cur.execute("SELECT 1")
                raise RuntimeError("forced rollback")
        except RuntimeError:
            pass
        # Connection should not be in failed state
        with pg_conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)

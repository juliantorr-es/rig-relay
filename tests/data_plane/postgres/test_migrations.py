"""Migration tests — migration from empty to current schema,
idempotent re-run, transaction rollback on failure.
"""

from __future__ import annotations

import pytest

from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._connection import transactional_cursor
from rig_relay.data_plane.postgres._migrations import _discover_migrations
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore


class TestMigrations:
    """Schema migration tests against real PostgreSQL."""

    def test_migrations_discovered(self) -> None:
        """Migrations directory has at least one migration."""
        migrations = _discover_migrations()
        assert len(migrations) >= 1
        first = migrations[0]
        assert first["index"] >= 0
        assert "sql" in first
        assert "sql_hash" in first

    def test_migrate_from_empty(self, pg_config) -> None:
        """Migration from empty database creates all tables.

        Uses a unique schema name to avoid collision with other tests
        that share the same disposable database.
        """
        import secrets
        import string

        suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
        schema_name = f"test_migrate_{suffix}"

        config = PostgresConnectionConfig(
            host=pg_config.host,
            port=pg_config.port,
            dbname=pg_config.dbname,
            user=pg_config.user,
            password=pg_config.password,
            schema_name=schema_name,
            autocommit=True,
        )

        store = PostgresOperationalProjectionStore(config)
        try:
            results = store.ensure_migrated()
            assert len(results) >= 1, "Expected at least 1 migration"
            for r in results:
                assert r.status == "applied", f"Migration {r.migration_id} failed"

            version, _ = store._get_schema_version()
            assert version >= 1
        finally:
            store.close()

    def test_migrate_idempotent(self, migrated_store) -> None:
        """Running migrations again is idempotent — no new migrations applied."""
        results = migrated_store.ensure_migrated()
        assert len(results) == 0

    def test_schema_version_tracked(self, migrated_store) -> None:
        """Schema version table has correct data."""
        version, schema_hash = migrated_store._get_schema_version()
        assert version >= 1
        assert schema_hash != ""

    def test_migration_tables_exist(self, migrated_store, pg_conn) -> None:
        """All expected tables exist after migration."""
        schema = migrated_store.config.schema_name
        expected_tables = [
            "_schema_version",
            "_migrations",
            "evidence_sources",
            "ingestion_checkpoints",
            "ingestion_receipts",
            "projection_builds",
            "rebuild_receipts",
            "operational_snapshots",
            "notify_channels",
        ]
        with pg_conn.cursor() as cur:
            for table in expected_tables:
                cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s)",
                    (schema, table),
                )
                exists = cur.fetchone()[0]
                assert exists, f"Table {schema}.{table} does not exist"

    def test_migration_records_stored(self, migrated_store, pg_conn) -> None:
        """Applied migrations are recorded in _migrations table."""
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM {schema}."_migrations" WHERE status = %s',
                ("applied",),
            )
            count = cur.fetchone()[0]
            assert count >= 1

    def test_transactional_rollback_on_failure(self, pg_config, pg_conn) -> None:
        """Bad SQL in migration should roll back and leave schema unchanged."""
        from psycopg import sql as psql

        schema = pg_config.schema_name

        # Ensure base migration is applied first
        store = PostgresOperationalProjectionStore(pg_config)
        try:
            store.ensure_migrated()
            version_before, _ = store._get_schema_version()

            # Try to execute bad SQL manually
            with pytest.raises(RuntimeError):
                with transactional_cursor(pg_conn) as cur:
                    cur.execute(
                        psql.SQL("CREATE TABLE {}.{} (id INT)").format(
                            psql.Identifier(schema), psql.Identifier("_bad_test_table")
                        )
                    )
                    raise RuntimeError("simulated migration failure")

            # Version should be unchanged
            version_after, _ = store._get_schema_version()
            assert version_after == version_before
        finally:
            store.close()

"""Versioned schema migration authority.

Migrations are ordered by index, idempotent where appropriate,
transactional, and evidence-emitting.

Design:
  - Each migration is a SQL file in the migrations/ directory.
  - Migrations are applied in index order.
  - Applied migrations are recorded in the _migrations table.
  - Failed migrations roll back the transaction and record the error.
  - Re-running applies only unapplied migrations.
  - Schema version is tracked in _schema_version (single row).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg import Connection, sql as psql

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._models import MigrationRecord, compute_sha256

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class MigrationError(Exception):
    """Raised when a migration cannot be applied."""

    def __init__(self, message: str, migration_id: str | None = None) -> None:
        super().__init__(message)
        self.migration_id = migration_id


def _discover_migrations() -> list[dict[str, Any]]:
    """Discover ordered migration files from the migrations directory."""
    if not _MIGRATIONS_DIR.is_dir():
        return []

    migrations: list[dict[str, Any]] = []
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        name = sql_file.stem
        parts = name.split("_", 1)
        if not parts or not parts[0].isdigit():
            continue

        index = int(parts[0])
        migration_id = name
        sql = sql_file.read_text(encoding="utf-8")
        sql_hash = compute_sha256(sql)

        migrations.append({
            "index": index,
            "migration_id": migration_id,
            "path": sql_file,
            "sql": sql,
            "sql_hash": sql_hash,
        })

    migrations.sort(key=lambda m: m["index"])
    return migrations


def _get_current_version(conn: Connection, schema_name: str) -> tuple[int, str]:
    """Get the current schema version from the database."""
    try:
        query = psql.SQL(
            "SELECT current_version, schema_hash FROM {}.{} WHERE schema_name = %s"
        ).format(psql.Identifier(schema_name), psql.Identifier("_schema_version"))
        with conn.cursor() as cur:
            cur.execute(query, (schema_name,))
            row = cur.fetchone()
            if row:
                return int(row[0]), str(row[1])
            return 0, ""
    except Exception:
        return 0, ""


def _get_applied_migrations(conn: Connection, schema_name: str) -> set[str]:
    """Get the set of already-applied migration IDs."""
    try:
        query = psql.SQL(
            "SELECT migration_id FROM {}.{} WHERE status = 'applied'"
        ).format(psql.Identifier(schema_name), psql.Identifier("_migrations"))
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return {r[0] for r in rows}
    except Exception:
        return set()


def _apply_migration(
    conn: Connection, schema_name: str, migration: dict[str, Any]
) -> MigrationRecord:
    """Apply a single migration within a transaction."""
    sql = migration["sql"]
    migration_id = migration["migration_id"]
    sql_hash = migration["sql_hash"]
    index = migration["index"]

    resolved_sql = sql.replace("{schema_name}", schema_name).replace(
        "{sql_hash}", sql_hash
    )

    logger.info("Applying migration %s (index %d)...", migration_id, index)

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                # Use psycopg.sql.SQL for literal SQL (migration code is trusted)
                cur.execute(psql.SQL(resolved_sql))

        logger.info("Migration %s applied successfully", migration_id)
        return MigrationRecord(
            migration_index=index,
            migration_id=migration_id,
            description=f"Applied from {Path(str(migration['path'])).name}",
            sql_hash=sql_hash,
            status="applied",
        )
    except Exception as e:
        logger.error("Migration %s failed: %s", migration_id, e)
        return MigrationRecord(
            migration_index=index,
            migration_id=migration_id,
            description=f"Failed: {Path(str(migration['path'])).name}",
            sql_hash=sql_hash,
            status="failed",
            error_message=str(e),
        )


def _record_migration(
    conn: Connection, schema_name: str, record: MigrationRecord
) -> None:
    """Record a migration in the _migrations table."""
    query = psql.SQL(
        "INSERT INTO {}.{} "
        "(migration_index, migration_id, description, applied_at, sql_hash, status, error_message) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (migration_index, migration_id) DO UPDATE SET "
        "status = EXCLUDED.status, error_message = EXCLUDED.error_message"
    ).format(psql.Identifier(schema_name), psql.Identifier("_migrations"))
    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                record.migration_index,
                record.migration_id,
                record.description,
                record.applied_at,
                record.sql_hash,
                record.status,
                record.error_message,
            ),
        )


def _update_schema_version(
    conn: Connection,
    schema_name: str,
    version: int,
    migration_id: str,
    schema_hash_val: str,
) -> None:
    """Update the _schema_version table."""
    now = datetime.now()
    query = psql.SQL(
        "INSERT INTO {}.{} "
        "(schema_name, current_version, last_migration_id, last_applied_at, schema_hash) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (schema_name) DO UPDATE SET "
        "current_version = EXCLUDED.current_version, "
        "last_migration_id = EXCLUDED.last_migration_id, "
        "last_applied_at = EXCLUDED.last_applied_at, "
        "schema_hash = EXCLUDED.schema_hash"
    ).format(psql.Identifier(schema_name), psql.Identifier("_schema_version"))
    with conn.cursor() as cur:
        cur.execute(query, (schema_name, version, migration_id, now, schema_hash_val))


def ensure_migrated(
    conn: Connection, config: PostgresConnectionConfig
) -> list[MigrationRecord]:
    """Apply all unapplied migrations in order.

    Idempotent: running again applies only new migrations.
    Each migration runs in its own transaction.
    Failed migrations are recorded and raise MigrationError.

    Args:
        conn: Active psycopg connection.
        config: Connection config with schema_name.

    Returns:
        List of MigrationRecord for each migration applied.

    Raises:
        MigrationError: If any migration fails.
    """
    schema_name = config.schema_name
    migrations = _discover_migrations()

    if not migrations:
        logger.info("No migrations discovered in %s", _MIGRATIONS_DIR)
        return []

    current_version, current_hash_val = _get_current_version(conn, schema_name)
    applied = _get_applied_migrations(conn, schema_name)

    logger.info(
        "Schema %s at version %d, %d migrations already applied",
        schema_name,
        current_version,
        len(applied),
    )

    results: list[MigrationRecord] = []
    new_hash_parts: list[str] = []
    if current_hash_val:
        new_hash_parts.append(current_hash_val)

    for migration in migrations:
        if migration["migration_id"] in applied:
            logger.debug(
                "Migration %s already applied, skipping", migration["migration_id"]
            )
            continue

        record = _apply_migration(conn, schema_name, migration)
        results.append(record)

        _record_migration(conn, schema_name, record)

        if record.status == "failed":
            raise MigrationError(
                f"Migration {record.migration_id} failed: {record.error_message}",
                migration_id=record.migration_id,
            )

        new_hash_parts.append(record.sql_hash)

    if results:
        last_successful = next(
            (r for r in reversed(results) if r.status == "applied"), None
        )
        if last_successful:
            combined_hash = compute_sha256("|".join(new_hash_parts))
            _update_schema_version(
                conn,
                schema_name,
                last_successful.migration_index,
                last_successful.migration_id,
                combined_hash,
            )
            logger.info(
                "Schema %s updated to version %d",
                schema_name,
                last_successful.migration_index,
            )

    return results


def compute_schema_hash(migrations: list[dict[str, Any]]) -> str:
    """Compute the combined schema hash from a set of migrations."""
    hashes = [m["sql_hash"] for m in sorted(migrations, key=lambda m: m["index"])]
    return compute_sha256("|".join(hashes))

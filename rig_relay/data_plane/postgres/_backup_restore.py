"""PostgreSQL operational-schema backup and restore application service.

Uses official PostgreSQL tooling (pg_dump, pg_restore). Backs up
the operational schema only (not the full PostgreSQL installation).
Restore requires a compatible prepared PostgreSQL environment.

Receipts are content-light — no raw connection strings, passwords,
or backup file contents.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, ClassVar

from psycopg import sql as psql

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._connection import check_connectivity, connect
from rig_relay.data_plane.postgres._models import (
    BackupReceipt,
    RestoreReceipt,
    compute_receipt_id,
)


class BackupError(Exception): ...


class RestoreError(Exception): ...


class BackupNotFoundError(Exception): ...


class PostgresBackupService:
    """Application service for PostgreSQL operational-schema backup and restore.

    Uses official PostgreSQL tooling (pg_dump, pg_restore). Backs up
    the operational schema only (not the full PostgreSQL installation).
    Restore requires a compatible prepared PostgreSQL environment.

    Backup scope: operational schema archive generation.
    NOT implemented: full local PostgreSQL installation recovery,
    major-version pg_upgrade migration, cross-server portability.

    Receipts are content-light — no raw connection strings, passwords,
    or backup file contents.
    """

    _FORMAT_MAP: ClassVar[dict[str, str]] = {
        "custom": "c",
        "plain": "p",
        "tar": "t",
        "directory": "d",
    }

    def __init__(
        self,
        config: PostgresConnectionConfig,
        backup_dir: Path | str = ".build/rig-relay/postgres/backups",
    ) -> None:
        self.config = config
        self.backup_dir = Path(backup_dir)

    # ── Backup ─────────────────────────────────────────────────────

    def create_backup(
        self, *, format: str = "custom", verify: bool = True
    ) -> BackupReceipt:
        """Create a PostgreSQL backup of the operational schema.

        The ``--schema`` flag limits backup to the operational schema.
        Full-database and cluster-level backups require pg_dumpall or
        a broader pg_dump invocation.

        Args:
            format: Backup format — one of "custom", "plain", "tar", "directory".
            verify: Whether to verify the backup artifact after creation.

        Returns:
            BackupReceipt with content-light backup metadata.

        Raises:
            BackupError: If connectivity check fails, pg_dump fails, or
                         the pg_dump binary is missing.
        """
        status = check_connectivity(self.config)
        if not status["connected"]:
            raise BackupError(
                f"PostgreSQL not connected: {status.get('error', 'unknown error')}"
            )

        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"backup_{self.config.dbname}_{self.config.schema_name}_{timestamp}.dump"
        )
        backup_path = self.backup_dir / filename

        migration_version = self._get_migration_version()
        table_count_before = self._count_tables()

        pg_format = self._FORMAT_MAP.get(format, "c")

        cmd = ["pg_dump"]
        if self.config.host:
            cmd.append(f"--host={self.config.host}")
        cmd.append(f"--port={self.config.port}")
        cmd.append(f"--dbname={self.config.dbname}")
        if self.config.user:
            cmd.append(f"--username={self.config.user}")
        cmd.extend([
            f"--format={pg_format}",
            f"--schema={self.config.schema_name}",
            "--no-password",
            "--no-owner",
            "--no-privileges",
            f"--file={backup_path}",
        ])

        env = os.environ.copy()
        password = self.config.password.get_secret_value()
        if password:
            env["PGPASSWORD"] = password

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, check=False
            )
        except FileNotFoundError:
            raise BackupError(
                "pg_dump not found. Ensure PostgreSQL client tools are installed."
            ) from None

        if result.returncode != 0:
            logger.error("pg_dump failed: %s", result.stderr.strip())
            raise BackupError(f"pg_dump failed: {result.stderr.strip()}")

        backup_sha256 = self._compute_file_sha256(backup_path)
        backup_size_bytes = backup_path.stat().st_size

        verified = False
        if verify and format != "directory":
            try:
                verified = self.verify_backup(backup_path)
            except BackupError:
                verified = False

        receipt_id = compute_receipt_id("backup", backup_sha256, datetime.now())

        logger.info(
            "Backup created: %s (%d bytes, %d tables, version %d)",
            backup_path.name,
            backup_size_bytes,
            table_count_before,
            migration_version,
        )

        return BackupReceipt(
            receipt_id=receipt_id,
            backup_method="pg_dump",
            database_name=self.config.dbname,
            schema_name=self.config.schema_name,
            format=format,
            backup_sha256=backup_sha256,
            backup_size_bytes=backup_size_bytes,
            table_count=table_count_before,
            migration_version=migration_version,
            secrets_excluded=True,
            exclusion_method="--no-password and --schema restriction",
            backed_up_at=datetime.now(),
            verified=verified,
        )

    # ── Restore ────────────────────────────────────────────────────

    def restore_backup(
        self, backup_path: Path | str, *, verify_equivalence: bool = True
    ) -> RestoreReceipt:
        """Restore a PostgreSQL backup using pg_restore.

        Args:
            backup_path: Path to the backup file.
            verify_equivalence: Whether to verify canonical equivalence after restore.

        Returns:
            RestoreReceipt with content-light restore metadata.

        Raises:
            RestoreError: If connectivity check fails or pg_restore fails.
            BackupNotFoundError: If the backup file does not exist.
        """
        path = Path(backup_path)

        status = check_connectivity(self.config)
        if not status["connected"]:
            raise RestoreError(
                f"PostgreSQL not connected: {status.get('error', 'unknown error')}"
            )

        if not path.exists():
            raise BackupNotFoundError(f"Backup file not found: {path}")

        backup_sha256 = self._compute_file_sha256(path)

        cmd = ["pg_restore"]
        if self.config.host:
            cmd.append(f"--host={self.config.host}")
        cmd.append(f"--port={self.config.port}")
        cmd.append(f"--dbname={self.config.dbname}")
        if self.config.user:
            cmd.append(f"--username={self.config.user}")
        cmd.extend([
            "--no-password",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            "--single-transaction",
            str(path),
        ])

        env = os.environ.copy()
        password = self.config.password.get_secret_value()
        if password:
            env["PGPASSWORD"] = password

        errors: list[str] = []

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, check=False
            )
        except FileNotFoundError:
            raise RestoreError(
                "pg_restore not found. Ensure PostgreSQL client tools are installed."
            ) from None

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "unknown error"
            errors.append(stderr)
            logger.error("pg_restore failed: %s", stderr)
            raise RestoreError(f"pg_restore failed: {stderr}")

        migration_version = self._get_migration_version()
        tables_restored, rows_restored = self._count_tables_and_rows()

        schema_metadata_restored = False
        verification_method = ""
        if verify_equivalence:
            schema_metadata_restored = self._verify_schema_migration_metadata()
            verification_method = (
                "checked _schema_version and _migrations rows present after restore"
            )

        receipt_id = compute_receipt_id("restore", backup_sha256, datetime.now())

        logger.info(
            "Backup restored: %d tables, %d rows, version %d, schema_metadata=%s",
            tables_restored,
            rows_restored,
            migration_version,
            schema_metadata_restored,
        )

        return RestoreReceipt(
            receipt_id=receipt_id,
            backup_sha256=backup_sha256,
            restore_method="pg_restore",
            restored_at=datetime.now(),
            tables_restored=tables_restored,
            rows_restored=rows_restored,
            migration_version_restored=migration_version,
            canonical_equivalence_verified=False,  # Always False — use verified_equivalence_level instead
            verified_equivalence_level=(
                "schema_migration_metadata" if schema_metadata_restored else "none"
            ),
            verification_method=verification_method,
            errors=errors,
        )

    # ── Verify ─────────────────────────────────────────────────────

    def verify_backup(self, backup_path: Path | str) -> bool:
        """Verify a backup artifact is structurally valid.

        Runs ``pg_restore --list`` to check the backup archive is readable.
        Does not actually restore data.

        Args:
            backup_path: Path to the backup file or directory.

        Returns:
            True if the backup passes verification, False otherwise.
        """
        path = Path(backup_path)
        if not path.exists():
            logger.warning("Backup file not found for verification: %s", path)
            return False

        cmd = ["pg_restore", "--list", str(path)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            logger.warning("pg_restore not found, skipping backup verification")
            return False

        if result.returncode != 0:
            logger.warning("Backup verification failed: %s", result.stderr.strip())
            return False

        return True

    # ── List ───────────────────────────────────────────────────────

    def list_backups(self) -> list[dict[str, Any]]:
        """List all backup artifacts in the backup directory.

        Returns:
            List of dicts with filename, size, sha256, and created_at for each
            ``.dump`` file found.
        """
        if not self.backup_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for path in sorted(self.backup_dir.glob("*.dump")):
            if not path.is_file():
                continue
            stat = path.stat()
            results.append({
                "filename": path.name,
                "size": stat.st_size,
                "sha256": self._compute_file_sha256(path),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return results

    # ── Internal helpers ───────────────────────────────────────────

    def _get_migration_version(self) -> int:
        """Get the current schema migration version from the database."""
        try:
            conn = connect(self.config)
            try:
                with conn.cursor() as cur:
                    query = psql.SQL(
                        "SELECT current_version FROM {}.{} WHERE schema_name = %s"
                    ).format(
                        psql.Identifier(self.config.schema_name),
                        psql.Identifier("_schema_version"),
                    )
                    cur.execute(query, (self.config.schema_name,))
                    row = cur.fetchone()
                    if row:
                        return int(row[0])
                    return 0
            finally:
                conn.close()
        except Exception:
            logger.debug("Could not read migration version", exc_info=True)
            return 0

    def _count_tables(self) -> int:
        """Count user tables in the operational schema."""
        try:
            conn = connect(self.config)
            try:
                with conn.cursor() as cur:
                    query = psql.SQL(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_type = %s"
                    )
                    cur.execute(query, (self.config.schema_name, "BASE TABLE"))
                    row = cur.fetchone()
                    return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception:
            logger.debug("Could not count tables", exc_info=True)
            return 0

    def _count_tables_and_rows(self) -> tuple[int, int]:
        """Count restored tables and total rows across all user tables."""
        try:
            conn = connect(self.config)
            try:
                with conn.cursor() as cur:
                    query = psql.SQL(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_type = %s"
                    )
                    cur.execute(query, (self.config.schema_name, "BASE TABLE"))
                    table_rows = cur.fetchall()

                    tables = len(table_rows)
                    total_rows = 0
                    for (table_name,) in table_rows:
                        count_query = psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                            psql.Identifier(self.config.schema_name),
                            psql.Identifier(table_name),
                        )
                        cur.execute(count_query)
                        row = cur.fetchone()
                        if row:
                            total_rows += int(row[0])

                    return tables, total_rows
            finally:
                conn.close()
        except Exception:
            logger.debug("Could not count tables and rows", exc_info=True)
            return 0, 0

    def _verify_schema_migration_metadata(self) -> bool:
        """Check that schema authority and migration metadata are present after restore.

        This verifies that the schema migration tracking tables survived
        the restore. It does NOT prove domain table content equivalence.
        For full product-state equivalence verification, compare domain
        table content digests against a pre-backup digest manifest.
        """
        try:
            conn = connect(self.config)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        psql.SQL(
                            "SELECT COUNT(*) FROM {}.{} WHERE schema_name = %s"
                        ).format(
                            psql.Identifier(self.config.schema_name),
                            psql.Identifier("_schema_version"),
                        ),
                        (self.config.schema_name,),
                    )
                    sv = cur.fetchone()
                    has_schema_version = sv is not None and sv[0] > 0

                    cur.execute(
                        psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                            psql.Identifier(self.config.schema_name),
                            psql.Identifier("_migrations"),
                        )
                    )
                    mig = cur.fetchone()
                    has_migrations = mig is not None and mig[0] > 0

                    return has_schema_version and has_migrations
            finally:
                conn.close()
        except Exception:
            logger.debug("Could not verify schema migration metadata", exc_info=True)
            return False

    @staticmethod
    def _compute_file_sha256(path: Path) -> str:
        """Compute the SHA256 hex digest of a file."""
        sha = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

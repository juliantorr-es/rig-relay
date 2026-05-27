"""PostgreSQL Operational Projection Store.

The primary entry point for the operational data plane. Provides:
  - Migration management
  - Canonical evidence ingestion (idempotent by evidence hash)
  - Projection materialization
  - Projection rebuild (deterministic from canonical evidence)
  - NOTIFY signalling for committed projections
  - Content-light storage guarantees
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection, sql as psql
from psycopg.types.json import Json

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._connection import check_connectivity, connect
from rig_relay.data_plane.postgres._migrations import ensure_migrated
from rig_relay.data_plane.postgres._models import (
    EvidenceSource,
    EvidenceSourceKind,
    IngestionCheckpoint,
    IngestionReceipt,
    MigrationRecord,
    ProjectionBuildReceipt,
    RebuildReceipt,
    compute_receipt_id,
)


class PostgresOperationalProjectionStore:
    """PostgreSQL-backed operational projection and query substrate.

    Materializes content-light application state from canonical evidence,
    records ingestion/migration/rebuild outcomes, and remains rebuildable
    without replacing canonical evidence authority.

    Usage:
        config = PostgresConnectionConfig(host="127.0.0.1", dbname="rig_relay")
        store = PostgresOperationalProjectionStore(config)
        store.ensure_migrated()
        receipt = store.ingest_evidence(evidence_source)
    """

    def __init__(self, config: PostgresConnectionConfig) -> None:
        self.config = config
        self._conn: Connection | None = None

    @property
    def conn(self) -> Connection:
        """Get or create the database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = connect(self.config)
        return self._conn

    def close(self) -> None:
        """Close the database connection if open."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None

    # ── Connectivity ───────────────────────────────────────────────

    def check_health(self) -> dict[str, Any]:
        """Check PostgreSQL connectivity and schema status."""
        result = check_connectivity(self.config)
        if result["connected"]:
            try:
                version, _ = self._get_schema_version()
                result["schema_version"] = version
                result["schema_name"] = self.config.schema_name
            except Exception as e:
                result["schema_status"] = f"error: {e}"
        return result

    # ── Migration management ───────────────────────────────────────

    def ensure_migrated(self) -> list[MigrationRecord]:
        """Apply all unapplied migrations. Idempotent."""
        return ensure_migrated(self.conn, self.config)

    def _get_schema_version(self) -> tuple[int, str]:
        """Get current schema version from the database."""
        query = psql.SQL(
            "SELECT current_version, schema_hash FROM {}.{} WHERE schema_name = %s"
        ).format(
            psql.Identifier(self.config.schema_name), psql.Identifier("_schema_version")
        )
        with self.conn.cursor() as cur:
            cur.execute(query, (self.config.schema_name,))
            row = cur.fetchone()
            if row:
                return int(row[0]), str(row[1])
            return 0, ""

    # ── Canonical evidence ingestion ───────────────────────────────

    def ingest_evidence(
        self,
        *,
        evidence_id: str,
        evidence_kind: str | EvidenceSourceKind,
        evidence_sha256: str,
        source_ledger_path_hash: str = "",
        source_schema_version: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> IngestionReceipt:
        """Ingest a canonical evidence reference into the operational store.

        Atomic and concurrency-safe. Uses ``INSERT ... ON CONFLICT DO NOTHING``
        on the ``evidence_id`` PRIMARY KEY to resolve concurrent duplicate
        submissions without a race-prone preflight SELECT.

        Two outcomes when a duplicate key exists:
        - **duplicate**: the stored ``evidence_sha256``, ``source_ledger_path_hash``,
          and ``source_schema_version`` match the submitted values — the same
          canonical evidence was re-submitted (idempotent replay).
        - **conflict**: any identity field differs — the same ``evidence_id`` was
          submitted with non-equivalent digest/schema/path metadata. This is
          a typed conflict, not a silent duplicate.

        The evidence row and its operational ingestion receipt commit together
        in a single transaction. The caller never receives ``failed`` after the
        evidence row silently committed without its terminal receipt.

        Content-light: stores only digest/reference metadata. The canonical
        evidence payload remains in its original ledger.

        Args:
            evidence_id: Unique evidence record identity (content-derived).
            evidence_kind: Kind of evidence.
            evidence_sha256: SHA256 digest of the canonical evidence payload.
            source_ledger_path_hash: Salted SHA256 hash of source ledger path.
            source_schema_version: Schema version of the evidence artifact.
            provenance: Content-light provenance metadata.

        Returns:
            IngestionReceipt with status: ``ingested``, ``duplicate``,
            ``conflict``, ``refused``, or ``failed``.
        """
        if isinstance(evidence_kind, str):
            try:
                kind = EvidenceSourceKind(evidence_kind)
            except ValueError:
                valid = [e.value for e in EvidenceSourceKind]
                return IngestionReceipt(
                    receipt_id=compute_receipt_id(
                        "ingest", evidence_id, datetime.now()
                    ),
                    evidence_id=evidence_id,
                    evidence_kind=EvidenceSourceKind.UNKNOWN,
                    status="refused",
                    refusal_reason=(
                        f"Invalid evidence_kind: '{evidence_kind}'. Valid: {valid}"
                    ),
                )
        else:
            kind = evidence_kind

        schema = self.config.schema_name
        provenance_data = provenance or {}
        now = datetime.now()

        insert_query = psql.SQL(
            "INSERT INTO {}.{} "
            "(evidence_id, evidence_kind, evidence_sha256, source_ledger_path_hash, "
            "source_schema_version, ingested_at, provenance) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (evidence_id) DO NOTHING"
        ).format(psql.Identifier(schema), psql.Identifier("evidence_sources"))

        try:
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute(
                        insert_query,
                        (
                            evidence_id,
                            kind.value,
                            evidence_sha256,
                            source_ledger_path_hash,
                            source_schema_version,
                            now,
                            Json(provenance_data),
                        ),
                    )
                    inserted = cur.rowcount == 1

                if inserted:
                    receipt = IngestionReceipt(
                        receipt_id=compute_receipt_id("ingest", evidence_id, now),
                        evidence_id=evidence_id,
                        evidence_kind=kind,
                        status="ingested",
                        ingested_at=now,
                        projection_rows_created=1,
                    )
                    self._record_ingestion_receipt(receipt)
                    logger.info("Evidence ingested: %s (%s)", evidence_id, kind.value)
                    return receipt

                # Duplicate key — compare identity fields for conflict detection
                existing = self.get_evidence(evidence_id)
                if existing is None:
                    return IngestionReceipt(
                        receipt_id=compute_receipt_id("ingest", evidence_id, now),
                        evidence_id=evidence_id,
                        evidence_kind=kind,
                        status="failed",
                        refusal_reason="ON CONFLICT DO NOTHING succeeded but existing row not found",
                        ingested_at=now,
                    )

                if (
                    existing.evidence_sha256 == evidence_sha256
                    and existing.source_ledger_path_hash == source_ledger_path_hash
                    and existing.source_schema_version == source_schema_version
                ):
                    receipt = IngestionReceipt(
                        receipt_id=compute_receipt_id("ingest", evidence_id, now),
                        evidence_id=evidence_id,
                        evidence_kind=kind,
                        status="duplicate",
                        ingested_at=now,
                    )
                    self._record_ingestion_receipt(receipt)
                    return receipt

                # Conflict: same evidence_id, different identity metadata
                mismatch_fields: list[str] = []
                if existing.evidence_sha256 != evidence_sha256:
                    mismatch_fields.append("evidence_sha256")
                if existing.source_ledger_path_hash != source_ledger_path_hash:
                    mismatch_fields.append("source_ledger_path_hash")
                if existing.source_schema_version != source_schema_version:
                    mismatch_fields.append("source_schema_version")

                receipt = IngestionReceipt(
                    receipt_id=compute_receipt_id("conflict", evidence_id, now),
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    status="conflict",
                    refusal_reason=(
                        f"Identity conflict: fields {mismatch_fields} differ from stored evidence {evidence_id}"
                    ),
                    ingested_at=now,
                )
                self._record_ingestion_receipt(receipt)
                logger.warning(
                    "Evidence conflict for %s: %s", evidence_id, mismatch_fields
                )
                return receipt

        except Exception as e:
            logger.error("Evidence ingestion failed for %s: %s", evidence_id, e)
            return IngestionReceipt(
                receipt_id=compute_receipt_id("ingest", evidence_id, datetime.now()),
                evidence_id=evidence_id,
                evidence_kind=kind,
                status="failed",
                refusal_reason=str(e),
                ingested_at=datetime.now(),
            )

    def _record_ingestion_receipt(self, receipt: IngestionReceipt) -> None:
        """Record an ingestion receipt in the database."""
        schema = self.config.schema_name
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(receipt_id, evidence_id, evidence_kind, status, refusal_reason, "
            "ingested_at, projection_rows_created) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
        ).format(psql.Identifier(schema), psql.Identifier("ingestion_receipts"))
        with self.conn.cursor() as cur:
            cur.execute(
                query,
                (
                    receipt.receipt_id,
                    receipt.evidence_id,
                    receipt.evidence_kind.value
                    if isinstance(receipt.evidence_kind, EvidenceSourceKind)
                    else receipt.evidence_kind,
                    receipt.status,
                    receipt.refusal_reason,
                    receipt.ingested_at,
                    receipt.projection_rows_created,
                ),
            )

    # ── Ingestion checkpoint management ────────────────────────────

    def update_checkpoint(
        self,
        *,
        ledger_path_hash: str,
        last_sequence: int,
        last_event_id: str,
        records_ingested: int,
    ) -> None:
        """Update or create an ingestion checkpoint for a canonical ledger."""
        schema = self.config.schema_name
        now = datetime.now()
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(ledger_path_hash, last_sequence, last_event_id, records_ingested, last_ingested_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ledger_path_hash) DO UPDATE SET "
            "last_sequence = EXCLUDED.last_sequence, "
            "last_event_id = EXCLUDED.last_event_id, "
            "records_ingested = {}.{}.records_ingested + EXCLUDED.records_ingested, "
            "last_ingested_at = EXCLUDED.last_ingested_at"
        ).format(
            psql.Identifier(schema),
            psql.Identifier("ingestion_checkpoints"),
            psql.Identifier(schema),
            psql.Identifier("ingestion_checkpoints"),
        )
        with self.conn.cursor() as cur:
            cur.execute(
                query,
                (ledger_path_hash, last_sequence, last_event_id, records_ingested, now),
            )

    def get_checkpoint(self, ledger_path_hash: str) -> IngestionCheckpoint | None:
        """Get the ingestion checkpoint for a canonical ledger."""
        schema = self.config.schema_name
        query = psql.SQL(
            "SELECT ledger_path_hash, last_sequence, last_event_id, "
            "records_ingested, last_ingested_at "
            "FROM {}.{} WHERE ledger_path_hash = %s"
        ).format(psql.Identifier(schema), psql.Identifier("ingestion_checkpoints"))
        with self.conn.cursor() as cur:
            cur.execute(query, (ledger_path_hash,))
            row = cur.fetchone()
            if row:
                return IngestionCheckpoint(
                    ledger_path_hash=row[0],
                    last_sequence=row[1],
                    last_event_id=row[2],
                    records_ingested=row[3],
                    last_ingested_at=row[4],
                )
            return None

    # ── Evidence query ─────────────────────────────────────────────

    def count_evidence_by_kind(self) -> dict[str, int]:
        """Count evidence sources grouped by kind."""
        schema = self.config.schema_name
        query = psql.SQL(
            "SELECT evidence_kind, COUNT(*) FROM {}.{} GROUP BY evidence_kind ORDER BY evidence_kind"
        ).format(psql.Identifier(schema), psql.Identifier("evidence_sources"))
        with self.conn.cursor() as cur:
            cur.execute(query)
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_evidence(self, evidence_id: str) -> EvidenceSource | None:
        """Get an evidence source by ID."""
        schema = self.config.schema_name
        query = psql.SQL(
            "SELECT evidence_id, evidence_kind, evidence_sha256, "
            "source_ledger_path_hash, source_schema_version, ingested_at, provenance "
            "FROM {}.{} WHERE evidence_id = %s"
        ).format(psql.Identifier(schema), psql.Identifier("evidence_sources"))
        with self.conn.cursor() as cur:
            cur.execute(query, (evidence_id,))
            row = cur.fetchone()
            if row:
                return EvidenceSource(
                    evidence_id=row[0],
                    evidence_kind=EvidenceSourceKind(row[1]),
                    evidence_sha256=row[2],
                    source_ledger_path_hash=row[3],
                    source_schema_version=row[4],
                    ingested_at=row[5],
                    provenance=row[6] if row[6] else {},
                )
            return None

    # ── Projection build ───────────────────────────────────────────

    def record_projection_build(self, receipt: ProjectionBuildReceipt) -> None:
        """Record a projection materialization in the database."""
        schema = self.config.schema_name
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(receipt_id, projection_name, source_evidence_count, rows_built, "
            "built_at, evidence_source_sha256) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        ).format(psql.Identifier(schema), psql.Identifier("projection_builds"))
        with self.conn.cursor() as cur:
            cur.execute(
                query,
                (
                    receipt.receipt_id,
                    receipt.projection_name,
                    receipt.source_evidence_count,
                    receipt.rows_built,
                    receipt.built_at,
                    receipt.evidence_source_sha256,
                ),
            )

    # ── Rebuild ────────────────────────────────────────────────────

    def clear_projection_data(self) -> int:
        """Clear all projection-derived data while preserving schema authority.

        Deletes from all domain materialization tables, projection tracking
        tables, and evidence ingestion tables.

        Does NOT delete _schema_version, _migrations, or notify_channels.

        Returns:
            Total number of rows deleted.
        """
        schema = self.config.schema_name
        tables = [
            "timeline_builds",
            "timeline_events",
            "repository_estate_builds",
            "repository_observation_changes",
            "repository_observations",
            "repository_workspace_instances",
            "registered_repositories",
            "publication_builds",
            "publication_preview_receipts",
            "publication_reconstruction",
            "rebuild_receipts",
            "projection_builds",
            "ingestion_receipts",
            "ingestion_checkpoints",
            "evidence_sources",
        ]
        total = 0

        with self.conn.transaction():
            with self.conn.cursor() as cur:
                for table in tables:
                    query = psql.SQL("DELETE FROM {}.{}").format(
                        psql.Identifier(schema), psql.Identifier(table)
                    )
                    cur.execute(query)
                    total += cur.rowcount

        logger.info("Cleared %d rows from projection tables", total)
        return total

    def rebuild_from_evidence(
        self,
        *,
        projection_name: str,
        evidence_sources: list[EvidenceSource],
        build_fn: Any = None,
    ) -> RebuildReceipt:
        """Clear and rebuild a projection from canonical evidence sources.

        This is a framework method — concrete rebuild logic is provided by
        later integration milestones that know the specific projection schema.

        For now, demonstrates the deterministic rebuild contract:
        1. Count rows before.
        2. Clear projection data.
        3. Re-ingest evidence sources.
        4. Count rows after.
        5. Emit a RebuildReceipt comparing rows_before and rows_after.

        Args:
            projection_name: Name of the projection being rebuilt.
            evidence_sources: Canonical evidence sources to rebuild from.
            build_fn: Optional callable(store, evidence_sources) for custom rebuild.

        Returns:
            RebuildReceipt with deterministic comparison.
        """
        rows_before = sum(self.count_evidence_by_kind().values())

        receipt_id = compute_receipt_id("rebuild", projection_name, datetime.now())

        if build_fn is not None:
            with self.conn.transaction():
                self.clear_projection_data()
                build_fn(self, evidence_sources)
        else:
            with self.conn.transaction():
                self.clear_projection_data()
                for evidence in evidence_sources:
                    self.ingest_evidence(
                        evidence_id=evidence.evidence_id,
                        evidence_kind=evidence.evidence_kind,
                        evidence_sha256=evidence.evidence_sha256,
                        source_ledger_path_hash=evidence.source_ledger_path_hash,
                        source_schema_version=evidence.source_schema_version,
                        provenance=evidence.provenance,
                    )

        rows_after = sum(self.count_evidence_by_kind().values())
        deterministic = rows_before == rows_after

        receipt = RebuildReceipt(
            receipt_id=receipt_id,
            projection_name=projection_name,
            rows_before=rows_before,
            rows_after=rows_after,
            rebuilt_at=datetime.now(),
            deterministic=deterministic,
        )

        self.record_rebuild_receipt(receipt)
        logger.info(
            "Rebuild %s: %d -> %d rows, deterministic=%s",
            projection_name,
            rows_before,
            rows_after,
            deterministic,
        )
        return receipt

    def record_rebuild_receipt(self, receipt: RebuildReceipt) -> None:
        """Record a rebuild receipt in the database."""
        schema = self.config.schema_name
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(receipt_id, projection_name, rows_before, rows_after, rebuilt_at, deterministic) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        ).format(psql.Identifier(schema), psql.Identifier("rebuild_receipts"))
        with self.conn.cursor() as cur:
            cur.execute(
                query,
                (
                    receipt.receipt_id,
                    receipt.projection_name,
                    receipt.rows_before,
                    receipt.rows_after,
                    receipt.rebuilt_at,
                    receipt.deterministic,
                ),
            )

    def acquire_rebuild_lock(
        self, projection_name: str, *, within_transaction: bool = True
    ) -> None:
        """Acquire an advisory lock serializing rebuilds for a projection domain.

        Uses PostgreSQL advisory transaction lock (pg_advisory_xact_lock)
        when within_transaction=True (lock held until transaction commit/rollback).
        Within a transaction this prevents concurrent rebuilds or materializations
        from interfering with domain projection state.

        When within_transaction=False, uses pg_advisory_lock (session-level).
        """
        from rig_relay.data_plane.postgres._models import compute_advisory_lock_key

        lock_key = compute_advisory_lock_key(projection_name)
        func = "pg_advisory_xact_lock" if within_transaction else "pg_advisory_lock"
        with self.conn.cursor() as cur:
            cur.execute(
                psql.SQL("SELECT {}(%s)").format(psql.Identifier(func)), (lock_key,)
            )

    # ── NOTIFY signalling ──────────────────────────────────────────

    def notify_projection_refresh(self, projection_name: str) -> None:
        """Send a NOTIFY to signal that a projection has been refreshed.

        The payload carries only the projection name — listeners fetch
        the actual data from the database. NOTIFY is always sent only
        after a committed materialization/update.

        This is a refresh signalling seam, NOT an event authority.
        Missing notification does not lose authoritative projection data.
        """
        channel = f"rig_projection_{projection_name}"
        with self.conn.cursor() as cur:
            cur.execute(
                psql.SQL("NOTIFY {}, %s").format(psql.Identifier(channel)),
                (f"projection:{projection_name}",),
            )
        logger.debug(
            "NOTIFY sent on channel %s for projection %s", channel, projection_name
        )

    def register_notify_channel(self, channel_name: str, description: str = "") -> None:
        """Register a notification channel in the channel registry."""
        schema = self.config.schema_name
        query = psql.SQL(
            "INSERT INTO {}.{} (channel_name, description, registered_at) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (channel_name) DO NOTHING"
        ).format(psql.Identifier(schema), psql.Identifier("notify_channels"))
        with self.conn.cursor() as cur:
            cur.execute(query, (channel_name, description, datetime.now()))

    # ── Operational snapshots ──────────────────────────────────────

    def capture_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_kind: str,
        snapshot_data: dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> None:
        """Capture an operational snapshot (service authority/degradation)."""
        schema = self.config.schema_name
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(snapshot_id, snapshot_kind, snapshot_data, captured_at, ttl_seconds) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (snapshot_id) DO UPDATE SET "
            "snapshot_data = EXCLUDED.snapshot_data, "
            "captured_at = EXCLUDED.captured_at"
        ).format(psql.Identifier(schema), psql.Identifier("operational_snapshots"))
        with self.conn.cursor() as cur:
            cur.execute(
                query,
                (
                    snapshot_id,
                    snapshot_kind,
                    Json(snapshot_data),
                    datetime.now(),
                    ttl_seconds,
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Get an operational snapshot by ID."""
        schema = self.config.schema_name
        query = psql.SQL(
            "SELECT snapshot_data FROM {}.{} WHERE snapshot_id = %s"
        ).format(psql.Identifier(schema), psql.Identifier("operational_snapshots"))
        with self.conn.cursor() as cur:
            cur.execute(query, (snapshot_id,))
            row = cur.fetchone()
            if row:
                return row[0] if isinstance(row[0], dict) else {}
            return None

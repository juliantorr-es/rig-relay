"""Timeline materialization into PostgreSQL operational store.

Materializes Investigation Timeline (T4.2) events from the
InvestigationEvidenceTimelineService through its published
build_postgres_projection() contract.

Stores all events including corrupt/degraded/missing ones.
Corrupt evidence is flagged, not discarded.

Authority: PostgreSQL is a disposable read-side projection.
Canonical observability/coordination/publication ledgers remain
the sole authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import sql as psql

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._models import (
    MaterializationReceipt,
    RebuildReceipt,
    compute_receipt_id,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore

# Column order matching the timeline_events table (migration 004).
# materialized_at is excluded — it defaults to now() in the table definition.
_TIMELINE_EVENT_COLUMNS = [
    "event_id",
    "timeline_sequence",
    "observed_at",
    "event_kind",
    "source_domain",
    "source_event_id",
    "source_digest",
    "source_sequence",
    "authority_classification",
    "degradation_detail",
    "session_id",
    "project_id",
    "investigation_id",
    "parent_session_id",
    "task_id",
    "operation_id",
    "outcome",
    "status",
    "latency_ms",
    "path_count",
    "artifact_kind",
    "artifact_sha256",
    "commit_sha",
    "refusal_code",
    "producer_digest",
    "producer_digest_verified",
    "verification_class",
    "content_light_guarantee",
]

# NOT NULL columns with DEFAULT in the table schema. If the projection
# row contains None for these, use the default instead so the NOT NULL
# constraint is satisfied.
_NOT_NULL_DEFAULTS: dict[str, object] = {
    "source_event_id": "",
    "source_digest": "",
    "degradation_detail": "",
    "session_id": "",
    "project_id": "",
    "investigation_id": "",
    "operation_id": "",
    "outcome": "",
    "status": "",
    "producer_digest": "",
    "producer_digest_verified": False,
}


class TimelineMaterializer:
    """Materializes Investigation Timeline (T4.2) events into PostgreSQL.

    Consumes the InvestigationEvidenceTimelineService through its
    published build_postgres_projection() contract.

    Stores all events including corrupt/degraded/missing ones.
    Corrupt evidence is flagged, not discarded.

    Authority: PostgreSQL is a disposable read-side projection.
    Canonical observability/coordination/publication ledgers remain
    the sole authority.
    """

    def __init__(self, store: PostgresOperationalProjectionStore) -> None:
        self.store = store

    # ── Materialize ─────────────────────────────────────────────────

    def materialize(
        self,
        service: Any,  # InvestigationEvidenceTimelineService
    ) -> MaterializationReceipt:
        """Materialize timeline events from the service into PostgreSQL.

        Calls service.assemble_timeline(), builds the PostgreSQL
        projection via the module-level build_postgres_projection(),
        and inserts all rows into timeline_events with ON CONFLICT
        (event_id) DO NOTHING. Records a timeline_builds row with
        degradation counts.

        All operations within a single transaction.
        """
        from rig_relay.investigation_timeline._pg_contract import (
            build_postgres_projection,
        )

        result = service.assemble_timeline()
        projection = build_postgres_projection(result.timeline)
        return self.materialize_from_projection(projection)

    def materialize_from_projection(
        self,
        projection: Any,  # PostgresTimelineProjection
    ) -> MaterializationReceipt:
        """Materialize a pre-built PostgresTimelineProjection into PostgreSQL.

        Useful when the projection has already been assembled and the
        caller wants to avoid calling assemble_timeline() again.

        All operations within a single transaction.
        """
        schema = self.store.config.schema_name
        now = datetime.now()
        rows = projection.rows if hasattr(projection, "rows") else []

        degradation = _compute_degradation_counts(rows)
        receipt = MaterializationReceipt(
            receipt_id=compute_receipt_id("timeline", projection.projection_id, now),
            domain="timeline",
            source_evidence_count=len(rows),
            rows_materialized=0,
            corrupt_rows=0,
            duplicate_rows=0,
            built_at=now,
            evidence_source_sha256="",
            deterministic=True,
        )

        if not rows:
            logger.info("Timeline materialize: no rows to insert")
            return receipt

        columns_sql = psql.SQL(", ").join(
            psql.Identifier(col) for col in _TIMELINE_EVENT_COLUMNS
        )
        placeholders = psql.SQL(", ").join(
            [psql.Placeholder()] * len(_TIMELINE_EVENT_COLUMNS)
        )
        insert_query = psql.SQL(
            "INSERT INTO {}.{} ({}) VALUES ({}) ON CONFLICT (event_id) DO NOTHING"
        ).format(
            psql.Identifier(schema),
            psql.Identifier("timeline_events"),
            columns_sql,
            placeholders,
        )

        with self.store.conn.transaction():
            with self.store.conn.cursor() as cur:
                events_built = 0
                duplicate_rows = 0

                for row in rows:
                    values = _extract_row_values(row)
                    cur.execute(insert_query, values)
                    if cur.rowcount == 1:
                        events_built += 1
                    else:
                        duplicate_rows += 1

                receipt.rows_materialized = events_built
                receipt.duplicate_rows = duplicate_rows
                receipt.corrupt_rows = degradation["corrupt_count"]

                _insert_timeline_build(cur, schema, receipt, degradation, events_built)

        logger.info(
            "Timeline materialized: %d events, %d duplicates, %d row count, "
            "verified=%d degraded=%d corrupt=%d",
            events_built,
            duplicate_rows,
            len(rows),
            degradation["verified_canonical_count"],
            degradation["canonical_degraded_count"],
            degradation["corrupt_count"],
        )

        return receipt

    # ── Rebuild ─────────────────────────────────────────────────────

    def rebuild(self, service: Any) -> RebuildReceipt:
        """Rebuild the timeline from canonical evidence.

        Deletes all timeline_events and timeline_builds rows, then
        re-materializes from the service. Compares rows_before and
        rows_after to determine determinism.

        Returns a RebuildReceipt with the comparison.
        """
        schema = self.store.config.schema_name
        now = datetime.now()

        rows_before = _count_timeline_events(self.store.conn, schema)

        receipt_id = compute_receipt_id("rebuild_timeline", "timeline", now)

        try:
            with self.store.conn.transaction():
                with self.store.conn.cursor() as cur:
                    cur.execute(
                        psql.SQL("DELETE FROM {}.{}").format(
                            psql.Identifier(schema), psql.Identifier("timeline_builds")
                        )
                    )
                    cur.execute(
                        psql.SQL("DELETE FROM {}.{}").format(
                            psql.Identifier(schema), psql.Identifier("timeline_events")
                        )
                    )

            _ = self.materialize(service)

            rows_after = _count_timeline_events(self.store.conn, schema)
        except Exception as e:
            logger.error("Timeline rebuild failed: %s", e)
            return RebuildReceipt(
                receipt_id=receipt_id,
                projection_name="timeline",
                rows_before=rows_before,
                rows_after=0,
                rebuilt_at=now,
                deterministic=False,
            )

        deterministic = rows_before == rows_after

        receipt = RebuildReceipt(
            receipt_id=receipt_id,
            projection_name="timeline",
            rows_before=rows_before,
            rows_after=rows_after,
            rebuilt_at=now,
            deterministic=deterministic,
        )

        logger.info(
            "Timeline rebuilt: %d -> %d rows, deterministic=%s",
            rows_before,
            rows_after,
            deterministic,
        )

        return receipt


# ── Helpers ─────────────────────────────────────────────────────────


def _extract_row_values(row: dict[str, object]) -> list[object]:
    """Extract column values in _TIMELINE_EVENT_COLUMNS order.

    Replaces None with the NOT NULL DEFAULT for columns that require
    a non-null value in the table schema.
    """
    values: list[object] = []
    for col in _TIMELINE_EVENT_COLUMNS:
        val = row.get(col)
        if val is None and col in _NOT_NULL_DEFAULTS:
            values.append(_NOT_NULL_DEFAULTS[col])
        else:
            values.append(val)
    return values


def _compute_degradation_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    """Compute degradation counts from projection rows.

    Inspects verification_class and authority_classification
    to produce counts matching the timeline_builds columns.
    """
    counts = {
        "verified_canonical_count": 0,
        "canonical_degraded_count": 0,
        "corrupt_count": 0,
        "unsupported_count": 0,
        "missing_count": 0,
        "contradictory_count": 0,
        "stale_count": 0,
    }

    for row in rows:
        vc = str(row.get("verification_class", ""))
        ac = str(row.get("authority_classification", ""))

        match vc:
            case "verified_canonical":
                counts["verified_canonical_count"] += 1
            case "canonical_degraded":
                counts["canonical_degraded_count"] += 1
            case "corrupt":
                counts["corrupt_count"] += 1
            case "unsupported":
                counts["unsupported_count"] += 1
            case "missing":
                counts["missing_count"] += 1

        if ac == "contradictory":
            counts["contradictory_count"] += 1
        if ac == "stale":
            counts["stale_count"] += 1

    return counts


def _insert_timeline_build(
    cur: Any,
    schema: str,
    receipt: MaterializationReceipt,
    degradation: dict[str, int],
    events_built: int,
) -> None:
    """Insert a timeline_builds row recording this materialization."""
    query = psql.SQL(
        "INSERT INTO {}.{} ("
        "receipt_id, source_event_count, events_built, "
        "verified_canonical_count, canonical_degraded_count, "
        "corrupt_count, unsupported_count, missing_count, "
        "contradictory_count, stale_count, "
        "built_at, evidence_source_sha256, deterministic"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    ).format(psql.Identifier(schema), psql.Identifier("timeline_builds"))

    cur.execute(
        query,
        (
            receipt.receipt_id,
            receipt.source_evidence_count,
            events_built,
            degradation["verified_canonical_count"],
            degradation["canonical_degraded_count"],
            degradation["corrupt_count"],
            degradation["unsupported_count"],
            degradation["missing_count"],
            degradation["contradictory_count"],
            degradation["stale_count"],
            receipt.built_at,
            receipt.evidence_source_sha256,
            receipt.deterministic,
        ),
    )


def _count_timeline_events(conn: Any, schema: str) -> int:
    """Count rows in timeline_events."""
    query = psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
        psql.Identifier(schema), psql.Identifier("timeline_events")
    )
    with conn.cursor() as cur:
        cur.execute(query)
        row = cur.fetchone()
        return int(row[0]) if row else 0

"""Publication history materialization into PostgreSQL.

Materializes Publication (T1.2) preview evidence from the append-only
publication_preview_evidence.v1.jsonl ledger into PostgreSQL operational tables.

Authority: PostgreSQL is a disposable read-side projection.
The publication_preview_evidence.v1.jsonl ledger remains the sole authority.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

from psycopg import sql as psql

from rig_relay.core.logger import logger
from rig_relay.data_plane.postgres._models import (
    MaterializationReceipt,
    RebuildReceipt,
    compute_receipt_id,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore
from rig_relay.publication._models import LedgerReconstruction


class PublicationMaterializer:
    """Materializes Publication (T1.2) preview evidence into PostgreSQL.

    Consumes the PublicationEvidenceLedger through its load_receipts()
    contract. Materializes preview receipts and reconstruction state
    from the append-only publication_preview_evidence.v1.jsonl ledger.

    Deployment readiness is always tracked as false for preview-only
    evidence. Corrupt receipts are stored with truthful degraded
    classification, not discarded.

    Authority: PostgreSQL is a disposable read-side projection.
    The publication_preview_evidence.v1.jsonl ledger remains the
    sole authority.
    """

    def __init__(self, store: PostgresOperationalProjectionStore) -> None:
        self._store = store
        self._schema = store.config.schema_name

    def materialize(
        self,
        ledger: Any,  # PublicationEvidenceLedger
    ) -> MaterializationReceipt:
        """Materialize all preview receipts from the evidence ledger.

        Calls ledger.load_receipts(authoritative=False) and then
        materializes the reconstruction into PostgreSQL tables
        within a single transaction.
        """
        reconstruction = ledger.load_receipts(authoritative=False)
        ledger_path_hash = _hash_ledger_path(ledger._path)
        return self._materialize_impl(reconstruction, ledger_path_hash)

    def materialize_from_reconstruction(
        self,
        reconstruction: Any,  # LedgerReconstruction
    ) -> MaterializationReceipt:
        """Materialize receipts from an already-loaded reconstruction.

        Used when the caller has already obtained a LedgerReconstruction
        and wants to materialize it without reloading the ledger. The
        ledger_path_hash is not available in this path; reconstruction
        state is stored without a path reference.
        """
        return self._materialize_impl(reconstruction, "")

    def _materialize_impl(
        self, reconstruction: LedgerReconstruction, ledger_path_hash: str
    ) -> MaterializationReceipt:
        """Core materialization logic — idempotent, single-transaction."""
        receipts = reconstruction.receipts
        total_count = reconstruction.total_rows
        now = datetime.now()

        receipt_id = compute_receipt_id("materialize", "publication", now)

        successful_count = 0
        refused_count = 0
        safety_failed_count = 0
        rows_materialized = 0
        duplicate_rows = 0

        with self._store.conn.transaction():
            with self._store.conn.cursor() as cur:
                # ── 1. Materialize preview receipts ──

                for receipt_dict in receipts:
                    compiled_at_str = receipt_dict.get("compiled_at", "")
                    try:
                        compiled_at = datetime.fromisoformat(compiled_at_str)
                    except (ValueError, TypeError):
                        compiled_at = now

                    compilation_successful = receipt_dict.get(
                        "compilation_successful", False
                    )
                    refusal_code_val = receipt_dict.get("refusal_code")
                    refusal_reasons_val = receipt_dict.get("refusal_reasons") or []
                    safety_passed = receipt_dict.get("safety_passed", False)

                    insert_receipt = psql.SQL(
                        "INSERT INTO {}.{} "
                        "(receipt_id, compiled_at, compilation_successful, "
                        "profile_candidate_digest, result_digest, refusal_code, "
                        "refusal_reasons, safety_passed, deployment_ready, preview_only, "
                        "evidence_digest, operation_id, source_event_id, source_event_digest, "
                        "provenance_class, authority_state, content_light_guarantee, "
                        "materialized_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, %s) "
                        "ON CONFLICT (receipt_id) DO NOTHING"
                    ).format(
                        psql.Identifier(self._schema),
                        psql.Identifier("publication_preview_receipts"),
                    )

                    cur.execute(
                        insert_receipt,
                        (
                            receipt_dict.get("receipt_id", ""),
                            compiled_at,
                            compilation_successful,
                            receipt_dict.get("profile_candidate_digest", ""),
                            receipt_dict.get("result_digest", ""),
                            refusal_code_val,
                            refusal_reasons_val,
                            safety_passed,
                            False,
                            True,
                            receipt_dict.get("evidence_digest", ""),
                            receipt_dict.get("operation_id", ""),
                            receipt_dict.get("source_event_id", ""),
                            receipt_dict.get("source_event_digest", ""),
                            "canonical_fact",
                            "canonical_live",
                            True,
                            now,
                        ),
                    )

                    if cur.rowcount == 1:
                        rows_materialized += 1
                    else:
                        duplicate_rows += 1

                    if compilation_successful:
                        successful_count += 1
                    if refusal_code_val is not None:
                        refused_count += 1
                    if not safety_passed:
                        safety_failed_count += 1

                # ── 2. Upsert reconstruction state ──

                authoritative = getattr(reconstruction, "authoritative", False)
                reconstruction_refused = (
                    authoritative and reconstruction.corruption_detected
                )

                upsert_reconstruction = psql.SQL(
                    "INSERT INTO {}.{} "
                    "(ledger_path_hash, total_rows, valid_rows, corrupt_rows, "
                    "corrupt_lines, corruption_detected, authoritative, "
                    "reconstruction_refused, last_reconstructed_at, "
                    "reconstruction_warnings, source_schema_version, materialized_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (ledger_path_hash) DO UPDATE SET "
                    "total_rows = EXCLUDED.total_rows, "
                    "valid_rows = EXCLUDED.valid_rows, "
                    "corrupt_rows = EXCLUDED.corrupt_rows, "
                    "corrupt_lines = EXCLUDED.corrupt_lines, "
                    "corruption_detected = EXCLUDED.corruption_detected, "
                    "authoritative = EXCLUDED.authoritative, "
                    "reconstruction_refused = EXCLUDED.reconstruction_refused, "
                    "last_reconstructed_at = EXCLUDED.last_reconstructed_at, "
                    "reconstruction_warnings = EXCLUDED.reconstruction_warnings, "
                    "source_schema_version = EXCLUDED.source_schema_version, "
                    "materialized_at = EXCLUDED.materialized_at"
                ).format(
                    psql.Identifier(self._schema),
                    psql.Identifier("publication_reconstruction"),
                )

                cur.execute(
                    upsert_reconstruction,
                    (
                        ledger_path_hash or _empty_ledger_hash(),
                        reconstruction.total_rows,
                        reconstruction.valid_rows,
                        reconstruction.corrupt_rows,
                        reconstruction.corrupt_lines,
                        reconstruction.corruption_detected,
                        authoritative,
                        reconstruction_refused,
                        now,
                        reconstruction.reconstruction_warnings,
                        "rig.relay.publication_preview_event.v1",
                        now,
                    ),
                )

                # ── 3. Insert build receipt ──

                reconstruction_healthy = not reconstruction.corruption_detected
                source_count = len(receipts)
                evidence_source_sha256 = _compute_evidence_sha256(receipts)

                insert_build = psql.SQL(
                    "INSERT INTO {}.{} "
                    "(receipt_id, source_receipt_count, receipts_built, "
                    "successful_count, refused_count, safety_failed_count, "
                    "corrupt_receipt_count, reconstruction_healthy, built_at, "
                    "evidence_source_sha256, deterministic) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                ).format(
                    psql.Identifier(self._schema), psql.Identifier("publication_builds")
                )

                cur.execute(
                    insert_build,
                    (
                        receipt_id,
                        source_count,
                        rows_materialized,
                        successful_count,
                        refused_count,
                        safety_failed_count,
                        reconstruction.corrupt_rows,
                        reconstruction_healthy,
                        now,
                        evidence_source_sha256,
                        False,
                    ),
                )

        return MaterializationReceipt(
            receipt_id=receipt_id,
            domain="publication",
            source_evidence_count=total_count,
            rows_materialized=rows_materialized,
            corrupt_rows=reconstruction.corrupt_rows,
            duplicate_rows=duplicate_rows,
            built_at=now,
            evidence_source_sha256=evidence_source_sha256,
            deterministic=False,
        )

    def rebuild(
        self,
        ledger: Any,  # PublicationEvidenceLedger
    ) -> RebuildReceipt:
        """Clear and rebuild all publication materialized rows from ledger.

        1. Counts existing rows in publication tables.
        2. Deletes all rows.
        3. Re-materializes from ledger.
        4. Compares rows_before vs rows_after.
        5. Returns RebuildReceipt with deterministic comparison.
        """
        rows_before = self._count_publication_rows()
        now = datetime.now()
        receipt_id = compute_receipt_id("rebuild", "publication", now)

        with self._store.conn.transaction():
            with self._store.conn.cursor() as cur:
                for table in (
                    "publication_builds",
                    "publication_preview_receipts",
                    "publication_reconstruction",
                ):
                    cur.execute(
                        psql.SQL("DELETE FROM {}.{}").format(
                            psql.Identifier(self._schema), psql.Identifier(table)
                        )
                    )

        self.materialize(ledger)

        rows_after = self._count_publication_rows()
        deterministic = rows_before == rows_after

        receipt = RebuildReceipt(
            receipt_id=receipt_id,
            projection_name="publication",
            rows_before=rows_before,
            rows_after=rows_after,
            rebuilt_at=now,
            deterministic=deterministic,
        )

        self._store._record_rebuild_receipt(receipt)
        logger.info(
            "Rebuild publication: %d -> %d rows, deterministic=%s",
            rows_before,
            rows_after,
            deterministic,
        )
        return receipt

    def _count_publication_rows(self) -> int:
        """Count total rows across all three publication materialization tables."""
        total = 0
        with self._store.conn.cursor() as cur:
            for table in (
                "publication_preview_receipts",
                "publication_reconstruction",
                "publication_builds",
            ):
                cur.execute(
                    psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        psql.Identifier(self._schema), psql.Identifier(table)
                    )
                )
                row = cur.fetchone()
                if row:
                    total += int(row[0])
        return total


def _hash_ledger_path(path: Any) -> str:
    """Compute a salted SHA256 hash of the ledger file path."""
    raw = str(path)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _empty_ledger_hash() -> str:
    """Return the hash for an empty/unknown ledger path."""
    return "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _compute_evidence_sha256(receipts: list[dict]) -> str:
    """Compute a combined SHA256 digest of receipt_ids for evidence provenance."""
    from json import dumps

    ids = sorted(r.get("receipt_id", "") for r in receipts)
    payload = dumps(ids, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

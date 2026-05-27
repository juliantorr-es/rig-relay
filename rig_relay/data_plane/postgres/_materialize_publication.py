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
from rig_relay.data_plane.postgres._materialization_input import (
    PublicationMaterializationInput,
    compute_projection_digest,
)
from rig_relay.data_plane.postgres._models import (
    MaterializationReceipt,
    RebuildReceipt,
    compute_receipt_id,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore


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
        self, input_data: PublicationMaterializationInput
    ) -> MaterializationReceipt:
        """Materialize from a public-boundary-safe materialization input."""
        return self._materialize_impl(
            input_data.reconstruction, input_data.ledger_identity_digest
        )

    def materialize_from_ledger(
        self, ledger: Any, ledger_path_digest: str = ""
    ) -> MaterializationReceipt:
        """Materialize from a PublicationEvidenceLedger (public API only).

        Uses PublicationMaterializationInput.from_ledger() which calls
        ledger.load_receipts() — the public API contract. Never accesses
        ledger._path or other private internals.
        """
        input_data = PublicationMaterializationInput.from_ledger(
            ledger, ledger_path_digest
        )
        return self.materialize(input_data)

    def materialize_from_reconstruction(
        self, reconstruction: Any
    ) -> MaterializationReceipt:
        """Materialize receipts from an already-loaded reconstruction.

        Used when the caller has already obtained a LedgerReconstruction
        and wants to materialize it without reloading the ledger.
        """
        return self._materialize_impl(reconstruction, "")

    def _materialize_impl(
        self, reconstruction: Any, ledger_path_hash: str
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
                            "derived_projection",
                            "controlled_boundary",
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
                        ledger_path_hash or "unknown",
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

    def rebuild(self, input_data: PublicationMaterializationInput) -> RebuildReceipt:
        """Clear and rebuild publication tables. Content-digest determinism."""
        schema = self._schema
        now = datetime.now()
        exclude = ["materialized_at", "built_at"]

        digest_before = compute_projection_digest(
            self._store.conn, schema, "publication_preview_receipts", exclude
        )
        rows_before = self._count_publication_rows()

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
                            psql.Identifier(schema), psql.Identifier(table)
                        )
                    )

        self.materialize(input_data)

        digest_after = compute_projection_digest(
            self._store.conn, schema, "publication_preview_receipts", exclude
        )
        rows_after = self._count_publication_rows()

        deterministic = digest_before == digest_after

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
            "Rebuild publication: %d -> %d rows, digest_before=%s digest_after=%s "
            "deterministic=%s",
            rows_before,
            rows_after,
            digest_before,
            digest_after,
            deterministic,
        )
        return receipt

    def rebuild_from_ledger(
        self, ledger: Any, ledger_path_digest: str = ""
    ) -> RebuildReceipt:
        """Rebuild from a live ledger (convenience wrapper)."""
        input_data = PublicationMaterializationInput.from_ledger(
            ledger, ledger_path_digest
        )
        return self.rebuild(input_data)

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


def _compute_evidence_sha256(receipts: list[dict]) -> str:
    """Compute evidence source digest binding receipt content, not just IDs."""
    import json as _json

    content_parts = []
    for r in receipts:
        content_parts.append({
            "receipt_id": r.get("receipt_id", ""),
            "evidence_digest": r.get("evidence_digest", ""),
            "compilation_successful": r.get("compilation_successful", False),
            "safety_passed": r.get("safety_passed", False),
            "refusal_code": r.get("refusal_code"),
            "operation_id": r.get("operation_id", ""),
        })

    payload = _json.dumps(content_parts, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

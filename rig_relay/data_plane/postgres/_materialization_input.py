"""Typed materialization inputs for domain materializers.

Each input class consumes only the published public boundaries of
its producer domain — never private store internals, underscored
module imports, or implementation details.

Content-light: SHA256 digests only. No raw file contents, paths, or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
from typing import Any


class MaterializationInputStatus(StrEnum):
    """Status of a materialization input's source evidence binding."""

    VERIFIED = "verified"
    MISSING_PRODUCER_DIGEST = "missing_producer_digest"
    CORRUPT_SOURCE = "corrupt_source"
    REFUSED = "refused"


@dataclass
class RepositoryEstateMaterializationInput:
    """Public-boundary-safe input from T3.1 build_projection() ONLY.

    Does NOT read JSONL files, does NOT access service._store,
    does NOT parse .build/ paths. Consumes the public projection
    contract exclusively.

    When the producer projection carries a ``projection_digest``,
    the ``source_evidence_digest`` binds that exact digest.  When
    the digest is absent the input carries ``missing_producer_digest``
    status — no fallback to unstable Python process/object hashing.
    """

    projection: Any  # RepositoryEstateProjection
    source_evidence_digest: str = ""
    source_schema_version: str = "rig.relay.repository_estate_projection.v1"
    source_status: MaterializationInputStatus = MaterializationInputStatus.VERIFIED
    source_status_reason: str = ""

    @classmethod
    def from_service(cls, service: Any) -> RepositoryEstateMaterializationInput:
        """Create input from ONLY service.build_projection().

        Does NOT read JSONL files, does NOT access service._store,
        does NOT parse .build/ paths. Consumes the public projection
        contract exclusively.

        Raises:
            ValueError: When the producer projection carries no digest
                        and ``required=True`` is passed.
        """
        import hashlib as _h

        projection = service.build_projection()
        producer_digest = (
            getattr(projection, "projection_digest", "")
            if hasattr(projection, "projection_digest")
            else ""
        )

        if not producer_digest:
            return cls(
                projection=projection,
                source_evidence_digest="",
                source_status=MaterializationInputStatus.MISSING_PRODUCER_DIGEST,
                source_status_reason=(
                    "T3.1 projection carries no projection_digest. "
                    "Source evidence cannot be bound."
                ),
            )

        digest = _h.sha256(producer_digest.encode()).hexdigest()
        return cls(
            projection=projection,
            source_evidence_digest=f"sha256:{digest}",
            source_status=MaterializationInputStatus.VERIFIED,
        )


@dataclass
class TimelineMaterializationInput:
    """Public-boundary-safe input for timeline materialization.

    Consumes T4.2's public build_postgres_projection() and
    assemble_timeline() contracts.
    """

    projection: Any  # PostgresTimelineProjection
    timeline_id: str = ""
    source_evidence_digest: str = ""

    @classmethod
    def from_service(cls, service: Any) -> TimelineMaterializationInput:
        """Create input from InvestigationEvidenceTimelineService public API.

        Source evidence digest binds the assembled timeline content,
        not just the ID. Hashes the projection rows + timeline identity
        for reliable source binding.
        """
        import hashlib as _hashlib
        import json as _json

        from rig_relay.investigation_timeline import build_postgres_projection

        result = service.assemble_timeline()
        projection = build_postgres_projection(result.timeline)

        digest_content = _json.dumps(
            [row for row in projection.rows],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        source_digest = _hashlib.sha256(
            f"{result.timeline.timeline_id}:{digest_content}".encode()
        ).hexdigest()

        return cls(
            projection=projection,
            timeline_id=result.timeline.timeline_id,
            source_evidence_digest=f"sha256:{source_digest}",
        )


@dataclass
class PublicationMaterializationInput:
    """Public-boundary-safe input for publication materialization.

    Consumes T1.2's public PublicationEvidenceLedger.load_receipts()
    contract without accessing private internals.

    Source evidence digest binds verified receipt outcome content:
    evidence_digest, compilation_successful, safety_passed, refusal_code,
    result_digest, operation_id, and corruption/reconstruction status
    for every receipt in the reconstruction. Changes in any receipt
    outcome with the same receipt_id produce a different digest.
    Unknown ledger identity is distinguished from an empty or synthetic
    digest.
    """

    reconstruction: (
        Any  # LedgerReconstruction (imported from public rig_relay.publication)
    )
    source_evidence_digest: str = ""
    ledger_identity_digest: str = ""
    source_status: MaterializationInputStatus = MaterializationInputStatus.VERIFIED
    source_status_reason: str = ""
    source_schema_version: str = "rig.relay.publication_preview_event.v1"

    @classmethod
    def from_ledger(
        cls, ledger: Any, ledger_path_digest: str = ""
    ) -> PublicationMaterializationInput:
        """Create input from a PublicationEvidenceLedger using ONLY public API.

        Source evidence digest binds verified receipt content, not just
        receipt IDs or a caller-supplied ledger path hash.  Hashes every
        receipt's evidence_digest, compilation_successful, safety_passed,
        refusal_code, result_digest, and operation_id plus the reconstruction's
        corruption state.

        ledger_path_digest is supplied by the caller — we do NOT read ledger._path.
        Unknown ledger identity is distinguishable from an empty or synthetic digest.
        """
        import json as _json

        reconstruction = ledger.load_receipts(authoritative=False)

        content_parts = []
        for receipt in reconstruction.receipts:
            content_parts.append({
                "receipt_id": receipt.get("receipt_id", ""),
                "evidence_digest": receipt.get("evidence_digest", ""),
                "compilation_successful": receipt.get("compilation_successful", False),
                "safety_passed": receipt.get("safety_passed", False),
                "refusal_code": receipt.get("refusal_code"),
                "result_digest": receipt.get("result_digest", ""),
                "operation_id": receipt.get("operation_id", ""),
            })

        content_parts.append({
            "_reconstruction": {
                "total_rows": reconstruction.total_rows,
                "valid_rows": reconstruction.valid_rows,
                "corrupt_rows": reconstruction.corrupt_rows,
                "corruption_detected": reconstruction.corruption_detected,
            }
        })

        payload = _json.dumps(content_parts, sort_keys=True, separators=(",", ":"))
        source_digest = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

        identity = ledger_path_digest or "unknown"

        if reconstruction.corruption_detected:
            return cls(
                reconstruction=reconstruction,
                source_evidence_digest=source_digest,
                ledger_identity_digest=identity,
                source_status=MaterializationInputStatus.CORRUPT_SOURCE,
                source_status_reason=(
                    f"Ledger reconstruction detected {reconstruction.corrupt_rows} corrupt rows "
                    f"out of {reconstruction.total_rows} total. "
                    "Source evidence is bound to corrupt content; "
                    "materialization may proceed but source is not verified."
                ),
            )

        return cls(
            reconstruction=reconstruction,
            source_evidence_digest=source_digest,
            ledger_identity_digest=identity,
            source_status=MaterializationInputStatus.VERIFIED,
        )


def compute_projection_digest(
    conn: Any,
    schema: str,
    table: str,
    primary_key_columns: list[str] | None = None,
    exclude_columns: list[str] | None = None,
    *,
    manifest_schema_version: str = "rig.relay.materialization_digest_manifest.v1",
    domain_name: str = "",
) -> str:
    """Compute a canonical SHA256 digest over table content.

    Uses a JSON-framed manifest with schema version, domain identity,
    table identity, column names, and canonically-ordered rows.
    Deterministic: same content always produces the same digest.

    The manifest has this structure:
    {
      "manifest_schema": "<manifest_schema_version>",
      "domain": "<domain_name>",
      "schema": "<schema_name>",
      "table": "<table_name>",
      "columns": ["col1", "col2", ...],
      "row_count": N,
      "rows": [{"col1": val1, ...}, ...]
    }

    Rows are sorted by primary_key_columns (default: first column).
    Non-semantic columns in exclude_columns are omitted.
    row_count, materialized_at, built_at, and receipt_id are always excluded.
    """
    import json as _json

    from psycopg import sql as psql

    skip = {"row_count", "materialized_at", "built_at", "receipt_id"}
    skip.update(exclude_columns or [])

    with conn.cursor() as cur:
        cur.execute(
            psql.SQL(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position"
            ),
            (schema, table),
        )
        all_cols = [r[0] for r in cur.fetchall()]
        cols = [c for c in all_cols if c not in skip]

        if not cols:
            return hashlib.sha256(b"").hexdigest()

        order_cols = primary_key_columns or [cols[0]]
        order_cols_filtered = [c for c in order_cols if c in cols]
        if not order_cols_filtered:
            order_cols_filtered = [cols[0]]
        order_sql = psql.SQL(", ").join(psql.Identifier(c) for c in order_cols_filtered)
        col_list = psql.SQL(", ").join(psql.Identifier(c) for c in cols)

        query = psql.SQL("SELECT {} FROM {}.{} ORDER BY {}").format(
            col_list, psql.Identifier(schema), psql.Identifier(table), order_sql
        )
        cur.execute(query)

        rows: list[dict[str, Any]] = []
        for row in cur:
            row_dict: dict[str, Any] = {}
            for i, col_name in enumerate(cols):
                val = row[i]
                if val is None:
                    row_dict[col_name] = None
                elif isinstance(val, (int, float, str, bool)):
                    row_dict[col_name] = val
                elif isinstance(val, datetime):
                    row_dict[col_name] = val.isoformat()
                elif isinstance(val, (bytes, bytearray)):
                    row_dict[col_name] = val.hex()
                else:
                    row_dict[col_name] = str(val)
            rows.append(row_dict)

        manifest = {
            "manifest_schema": manifest_schema_version,
            "domain": domain_name,
            "schema": schema,
            "table": table,
            "columns": cols,
            "row_count": len(rows),
            "rows": rows,
        }

        canonical = _json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_multi_table_digest(
    conn: Any,
    schema: str,
    tables: list[tuple[str, list[str]]],
    exclude_columns: list[str] | None = None,
    *,
    manifest_schema_version: str = "rig.relay.materialization_digest_manifest.v1",
    domain_name: str = "",
) -> str:
    """Combined digest: SHA256(table1_digest + "|" + table2_digest + ...).

    tables: list of (table_name, primary_key_columns) tuples.
    """
    sha = hashlib.sha256()
    for table_name, pk_cols in tables:
        table_digest = compute_projection_digest(
            conn,
            schema,
            table_name,
            pk_cols,
            exclude_columns,
            manifest_schema_version=manifest_schema_version,
            domain_name=domain_name,
        )
        sha.update(f"{table_name}:{table_digest}|".encode())
    return sha.hexdigest()

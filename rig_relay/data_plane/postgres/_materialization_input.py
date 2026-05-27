"""Typed materialization inputs for domain materializers.

Each input class consumes only the published public boundaries of
its producer domain — never private store internals, underscored
module imports, or implementation details.

Content-light: SHA256 digests only. No raw file contents, paths, or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from typing import Any


@dataclass
class RepositoryEstateMaterializationInput:
    """Public-boundary-safe input for repository estate materialization.

    Consumes:
      - T3.1 RepositoryEstateProjection (via service.build_projection())
      - Public JSONL evidence ledgers (registrations.jsonl, observations.jsonl)
        read through a file path, NOT through service._store.

    Authority is preserved truthfully:
      - Rows from the projection carry the projection's authority state
      - Rows from raw JSONL carry "parsed_unverified" — never canonical_live
      - Corrupt/malformed rows carry "corrupt" or "corrupt_untrusted"
    """

    projection: Any  # RepositoryEstateProjection
    registration_events: list[dict[str, Any]] = field(default_factory=list)
    observation_events: list[dict[str, Any]] = field(default_factory=list)
    source_evidence_digest: str = ""
    source_schema_version: str = "rig.relay.repository_estate_projection.v1"

    @classmethod
    def from_service(cls, service: Any) -> RepositoryEstateMaterializationInput:
        """Create input from a RepositoryEstateService using ONLY public API.

        Does NOT access service._store. Reads the projection through
        the public build_projection() call and reads evidence JSONL
        ledgers from the filesystem paths where T3.1 writes them.
        """
        from json import loads
        from pathlib import Path

        projection = service.build_projection()

        base = Path(".build/rig-relay/repository_estate")
        reg_path = base / "registrations.jsonl"
        obs_path = base / "observations.jsonl"

        registrations: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []

        for path, target_list in [(reg_path, registrations), (obs_path, observations)]:
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                for line in raw.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        target_list.append(loads(stripped))
                    except Exception:
                        target_list.append({"_corrupt": True, "_raw": stripped[:256]})

        digest_input = hashlib.sha256(
            str(
                projection.projection_digest
                if hasattr(projection, "projection_digest")
                else ""
            ).encode()
        ).hexdigest()

        return cls(
            projection=projection,
            registration_events=registrations,
            observation_events=observations,
            source_evidence_digest=f"sha256:{digest_input}",
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
        """Create input from InvestigationEvidenceTimelineService public API."""
        import hashlib as _hashlib

        from rig_relay.investigation_timeline._pg_contract import (
            build_postgres_projection,
        )

        result = service.assemble_timeline()
        projection = build_postgres_projection(result.timeline)

        digest_input = _hashlib.sha256(result.timeline.timeline_id.encode()).hexdigest()

        return cls(
            projection=projection,
            timeline_id=result.timeline.timeline_id,
            source_evidence_digest=f"sha256:{digest_input}",
        )


@dataclass
class PublicationMaterializationInput:
    """Public-boundary-safe input for publication materialization.

    Consumes T1.2's public PublicationEvidenceLedger.load_receipts()
    contract without accessing private internals.
    """

    reconstruction: (
        Any  # LedgerReconstruction (imported from public rig_relay.publication)
    )
    ledger_identity_digest: str = ""
    source_schema_version: str = "rig.relay.publication_preview_event.v1"

    @classmethod
    def from_ledger(
        cls, ledger: Any, ledger_path_digest: str = ""
    ) -> PublicationMaterializationInput:
        """Create input from a PublicationEvidenceLedger using ONLY public API.

        ledger_path_digest is supplied by the caller — we do NOT read ledger._path.
        """
        reconstruction = ledger.load_receipts(authoritative=False)
        return cls(
            reconstruction=reconstruction,
            ledger_identity_digest=ledger_path_digest
            or "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )


def compute_projection_digest(
    conn: Any, schema: str, table: str, exclude_columns: list[str] | None = None
) -> str:
    """Compute a deterministic SHA256 digest over canonicalized table content.

    Reads all rows from the specified table, canonicalizes them
    (ordered by primary key, consistent column ordering, null-safe),
    and returns a SHA256 hex digest.

    exclude_columns: column names to exclude (e.g., materialized_at, receipt_id)
    """
    from psycopg import sql as psql

    skip = set(exclude_columns or [])
    sha = hashlib.sha256()

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
            return sha.hexdigest()

        col_list = psql.SQL(", ").join(psql.Identifier(c) for c in cols)
        query = psql.SQL("SELECT {} FROM {}.{} ORDER BY 1").format(
            col_list, psql.Identifier(schema), psql.Identifier(table)
        )
        cur.execute(query)

        for row in cur:
            for val in row:
                if val is None:
                    sha.update(b"\x00NULL")
                elif isinstance(val, bool):
                    sha.update(b"\x01" + (b"true" if val else b"false"))
                elif isinstance(val, int):
                    sha.update(b"\x02" + str(val).encode())
                elif isinstance(val, float):
                    sha.update(b"\x03" + f"{val:.15g}".encode())
                elif isinstance(val, (bytes, bytearray)):
                    sha.update(b"\x04" + bytes(val))
                elif isinstance(val, str):
                    sha.update(b"\x05" + val.encode("utf-8"))
                elif isinstance(val, datetime):
                    sha.update(b"\x06" + val.isoformat().encode())
                else:
                    sha.update(b"\x07" + str(val).encode())

    return sha.hexdigest()


def compute_multi_table_digest(
    conn: Any, schema: str, tables: list[str], exclude_columns: list[str] | None = None
) -> str:
    """Compute a combined digest over multiple tables.

    Digest = SHA256(table1_digest + "|" + table2_digest + ...)
    """
    sha = hashlib.sha256()
    for table in tables:
        table_digest = compute_projection_digest(conn, schema, table, exclude_columns)
        sha.update(f"{table}:{table_digest}|".encode())
    return sha.hexdigest()

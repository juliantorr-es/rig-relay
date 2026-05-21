"""Rig Relay Local Analytical Compiler — shared substrate.

Converts append-only JSONL evidence ledgers into deterministic
DuckDB-backed analytical facts and materialized projections.

Doctrine:
  JSONL ledgers remain the append-only source of truth.
  DuckDB is the local analytical compiler, not the operational store.
  Projectors produce deterministic read models.
  Canonical findings and source code are not mutated by analytics.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import duckdb as _duckdb

    HAS_DUCKD = True
except ImportError:
    _duckdb = None
    HAS_DUCKD = False


# ── Ledger loading ──────────────────────────────────────────────


class LedgerLoadResult:
    """Result of loading a JSONL ledger.

    Attributes:
        valid_records: Parsed JSON records.
        diagnostics: Dict with malformed_line_count, malformed_line_numbers,
                     valid_record_count, source_ledger_sha256.
    """

    def __init__(
        self, valid_records: list[dict[str, Any]], diagnostics: dict[str, Any]
    ) -> None:
        self.valid_records = valid_records
        self.diagnostics = diagnostics


def load_jsonl(path: Path) -> LedgerLoadResult:
    """Read a JSONL ledger, parse valid records, collect malformed-line diagnostics.

    Returns:
        LedgerLoadResult with valid_records and diagnostics.
        Missing files produce empty results, not errors.
    """
    if not path.is_file():
        return LedgerLoadResult(
            valid_records=[],
            diagnostics={
                "malformed_line_count": 0,
                "malformed_line_numbers": [],
                "valid_record_count": 0,
                "source_ledger_sha256": "",
            },
        )

    valid: list[dict[str, Any]] = []
    malformed_lines: list[int] = []

    raw_bytes = path.read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8", errors="replace")

    for i, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            valid.append(json.loads(stripped))
        except json.JSONDecodeError:
            malformed_lines.append(i)

    return LedgerLoadResult(
        valid_records=valid,
        diagnostics={
            "malformed_line_count": len(malformed_lines),
            "malformed_line_numbers": malformed_lines[:20],
            "valid_record_count": len(valid),
            "source_ledger_sha256": source_sha256,
        },
    )


# ── DuckDB connection ───────────────────────────────────────────


def connect_in_memory() -> Any:
    """Create an in-memory DuckDB connection.

    Returns a DuckDB connection, or raises RuntimeError if DuckDB is
    not available.
    """
    if not HAS_DUCKD:
        raise RuntimeError("DuckDB is not available. Install with: uv add duckdb")
    assert _duckdb is not None  # narrow for pyright after ImportError guard
    return _duckdb.connect(":memory:")


def create_reports_table(con: Any, records: list[dict[str, Any]]) -> None:
    """Create the reports table from normalized records.

    If records is empty, creates an empty table with the standard schema.
    Uses DuckDB's automatic schema inference from Python dicts.
    """
    if records:
        con.execute(
            "CREATE OR REPLACE TABLE reports AS SELECT * FROM (VALUES (1)) AS t(x) WHERE FALSE"
        )
        con.execute(
            f"CREATE OR REPLACE TABLE reports AS SELECT * FROM ({_build_values_sql(records)}) AS t"
        )
    else:
        con.execute(
            "CREATE TABLE IF NOT EXISTS reports ("
            "report_id VARCHAR, kind VARCHAR, title VARCHAR, "
            "summary VARCHAR, severity VARCHAR, confidence VARCHAR, status VARCHAR, "
            "scope_relation VARCHAR, dedupe_key VARCHAR, dedupe_status VARCHAR, "
            "created_at VARCHAR, affected_path_count INTEGER, evidence_count INTEGER, "
            "blocker_count INTEGER, report_sha256 VARCHAR, event_sha256 VARCHAR)"
        )


def _build_values_sql(records: list[dict[str, Any]]) -> str:
    """Build a DuckDB VALUES clause from a list of normalized dicts."""
    if not records:
        return "SELECT NULL LIMIT 0"

    columns = list(records[0].keys())
    rows: list[str] = []

    for rec in records:
        vals: list[str] = []
        for col in columns:
            v = rec.get(col)
            if v is None:
                vals.append("NULL")
            elif isinstance(v, int):
                vals.append(str(v))
            else:
                escaped = str(v).replace("'", "''")
                vals.append(f"'{escaped}'")
        rows.append("(" + ", ".join(vals) + ")")

    return "SELECT * FROM (VALUES " + ", ".join(rows) + f") AS t({', '.join(columns)})"


def rows_to_dicts(con: Any, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a DuckDB query and return results as a list of dicts.

    Avoids pandas/numpy dependency that fetchdf() requires.
    """
    result = con.execute(query, params)
    columns = [d[0] for d in result.description]
    return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


# ── Projection metadata ─────────────────────────────────────────


_PROJECTOR_VERSION = "1.0.0"


def build_projection_metadata(
    projection_kind: str,
    source_ledger_path: Path,
    diagnostics: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build standard projection metadata for a written index.

    Args:
        projection_kind: Name of the projection (e.g. report_summary, bash_usage_summary).
        source_ledger_path: Path to the source JSONL ledger.
        diagnostics: Diagnostics dict from load_jsonl().
        generated_at: Optional ISO timestamp. Defaults to now.

    Returns:
        Dict with schema_version, projection_kind, generated_at, etc.
    """
    return {
        "schema_version": "rig.report_projection.v1",
        "projection_kind": projection_kind,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "projector_version": _PROJECTOR_VERSION,
        "source_ledger_path": str(source_ledger_path),
        "source_ledger_sha256": diagnostics.get("source_ledger_sha256", ""),
        "valid_record_count": diagnostics.get("valid_record_count", 0),
        "malformed_line_count": diagnostics.get("malformed_line_count", 0),
    }


def write_projection(
    path: Path, data: dict[str, Any] | list[Any], metadata: dict[str, Any] | None = None
) -> Path:
    """Write a deterministic projection JSON file.

    If data is a dict and metadata is provided, merges metadata into the
    output. Lists are wrapped in an envelope if metadata is provided.

    Returns the path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if metadata is not None:
        if isinstance(data, dict):
            output = {**metadata, **data}
        elif isinstance(data, list):
            output = {**metadata, "items": data}
        else:
            output = {**metadata, "data": data}
    else:
        output = data

    path.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ── Normalization helpers ───────────────────────────────────────


def normalize_report_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw report record into a flat tabular row."""
    evidence = record.get("evidence", [])
    affected_paths = record.get("affected_paths", [])
    return {
        "report_id": record.get("report_id", ""),
        "kind": record.get("kind", ""),
        "title": record.get("title", ""),
        "summary": record.get("summary", ""),
        "severity": record.get("severity", ""),
        "confidence": record.get("confidence", ""),
        "status": record.get("status", ""),
        "scope_relation": record.get("scope_relation", ""),
        "dedupe_key": record.get("dedupe_key", ""),
        "dedupe_status": record.get("dedupe_status", ""),
        "created_at": record.get("created_at", ""),
        "affected_path_count": len(affected_paths),
        "evidence_count": len(evidence),
        "blocker_count": len(record.get("blockers", [])),
        "report_sha256": record.get("report_sha256", ""),
        "event_sha256": record.get("event_sha256", ""),
        "details_json": json.dumps(record.get("details", {}), sort_keys=True),
        "links_json": json.dumps(record.get("links", {}), sort_keys=True),
        "evidence_json": json.dumps(evidence, sort_keys=True),
        "affected_paths_json": json.dumps(affected_paths, sort_keys=True),
    }

"""DuckDB Read-Side Projection — Governance Decisions.

Builds a disposable DuckDB table ``governance_decisions`` from ReceiptStore
manifest.jsonl and sharded ReceiptEnvelope JSON files in a content-light,
rebuildable projection.

Doctrine:
  - JSON shard files + manifest.jsonl remain canonical source-of-truth.
  - DuckDB is a disposable analytical/read-side projection — NOT authority.
  - Projection must be rebuildable by deleting/repopulating the table.
  - Projection must validate source counts and content-light fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

HAS_DUCKDB = False
try:
    import duckdb as _duckdb_

    HAS_DUCKDB = True
except ImportError:
    _duckdb_ = None  # type: ignore[assignment]

_GOVERNANCE_DECISIONS_TABLE = "governance_decisions"
_PROJECTION_KIND = "duckdb_governance_decisions_projection.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _rows_to_dicts(result: Any) -> list[dict[str, object]]:
    if result is None:
        return []
    try:
        cols = [desc[0] for desc in result.description]
    except (AttributeError, TypeError, IndexError):
        return []
    return [dict(zip(cols, row)) for row in result.fetchall()]


def build_governance_decisions_projection(
    receipt_store_root: Path, *, derived_dir: Path | None = None
) -> dict[str, Any]:
    if _duckdb_ is None:
        return _no_duckdb_response()

    manifest_path = receipt_store_root / "manifest.jsonl"
    envelopes_dir = receipt_store_root / "envelopes"

    if not manifest_path.is_file():
        return {
            "schema_version": "rig.relay.duckdb_governance_decisions_projection.v1",
            "projection_kind": _PROJECTION_KIND,
            "status": "no_source_data",
            "generated_at": _now_iso(),
            "content_light": True,
            "mutation_authority": False,
            "read_side_only": True,
            "raw_payloads_exposed": False,
            "diagnostics": [{"kind": "missing_manifest", "path": str(manifest_path)}],
        }

    diagnostics: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    manifest_sha256_lines: list[str] = []

    with manifest_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                manifest_rows.append(json.loads(line_str))
            except json.JSONDecodeError:
                diagnostics.append({
                    "kind": "corrupted_manifest_line",
                    "line": line_num,
                    "reason": "JSON decode failure",
                })
                continue
            manifest_sha256_lines.append(line_str)

    manifest_sha256 = _sha256_str("\n".join(sorted(manifest_sha256_lines)))

    envelope_ids_on_disk: set[str] = set()
    if envelopes_dir.is_dir():
        for shard_dir in envelopes_dir.iterdir():
            if not shard_dir.is_dir():
                continue
            for envelope_file in shard_dir.iterdir():
                if envelope_file.suffix == ".json":
                    envelope_ids_on_disk.add(envelope_file.stem)

    conn = _duckdb_.connect(":memory:")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {_GOVERNANCE_DECISIONS_TABLE}")
        conn.execute(
            f"CREATE TABLE {_GOVERNANCE_DECISIONS_TABLE} ("
            "envelope_id VARCHAR, receipt_kind VARCHAR, session_id VARCHAR, "
            "created_at VARCHAR, governance_decision_id VARCHAR, "
            "decision_status VARCHAR, surface VARCHAR, authority_tier VARCHAR, "
            "capability_id VARCHAR, schema_version VARCHAR, "
            "content_light_classification VARCHAR, "
            "manifest_row_index INTEGER, source_manifest_sha256 VARCHAR, "
            "projection_built_at VARCHAR, envelope_path VARCHAR)"
        )

        valid_count = 0
        insert_params: list[tuple[object, ...]] = []
        for idx, row in enumerate(manifest_rows):
            eid = str(row.get("envelope_id", ""))
            if not eid:
                continue
            if eid not in envelope_ids_on_disk:
                diagnostics.append({
                    "kind": "missing_shard",
                    "envelope_id": eid,
                    "manifest_line": idx + 1,
                })
                continue
            insert_params.append(
                _row_to_params(row, idx, manifest_sha256, envelopes_dir)
            )
            valid_count += 1

        if insert_params:
            placeholders = ", ".join(["?"] * len(insert_params[0]))
            conn.executemany(
                f"INSERT INTO {_GOVERNANCE_DECISIONS_TABLE} VALUES ({placeholders})",
                insert_params,
            )

        for eid in sorted(
            envelope_ids_on_disk
            - {str(r.get("envelope_id", "")) for r in manifest_rows}
        ):
            diagnostics.append({"kind": "orphaned_shard", "envelope_id": eid})

        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_gd_decision_id "
            f"ON {_GOVERNANCE_DECISIONS_TABLE}(governance_decision_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_gd_surface "
            f"ON {_GOVERNANCE_DECISIONS_TABLE}(surface)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_gd_authority_tier "
            f"ON {_GOVERNANCE_DECISIONS_TABLE}(authority_tier)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_gd_created_at "
            f"ON {_GOVERNANCE_DECISIONS_TABLE}(created_at)"
        )

        query_results = _build_query_results(conn)
    except Exception as exc:
        conn.close()
        return _build_failed_response(str(exc), diagnostics)
    conn.close()

    projection = {
        "schema_version": "rig.relay.duckdb_governance_decisions_projection.v1",
        "projection_kind": _PROJECTION_KIND,
        "status": "ok",
        "generated_at": _now_iso(),
        "table_name": _GOVERNANCE_DECISIONS_TABLE,
        "source_manifest_path": str(manifest_path),
        "source_manifest_sha256": manifest_sha256,
        "manifest_row_count": len(manifest_rows),
        "valid_record_count": valid_count,
        "orphaned_shard_count": sum(
            1 for d in diagnostics if d.get("kind") == "orphaned_shard"
        ),
        "corrupted_manifest_line_count": sum(
            1 for d in diagnostics if d.get("kind") == "corrupted_manifest_line"
        ),
        "missing_shard_count": sum(
            1 for d in diagnostics if d.get("kind") == "missing_shard"
        ),
        "content_light": True,
        "mutation_authority": False,
        "read_side_only": True,
        "raw_payloads_exposed": False,
        "rebuildable": True,
        "duckdb_version": getattr(_duckdb_, "__version__", "unknown")
        if _duckdb_ is not None
        else "unavailable",
        "query_results": query_results,
        "diagnostics": diagnostics,
    }

    if derived_dir is not None:
        out_path = derived_dir / "governance_decisions_projection_v1.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(projection, ensure_ascii=False, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )
        projection["output_path"] = str(out_path)

    return projection


def query_governance_decisions(
    receipt_store_root: Path, query: str, *, params: list[object] | None = None
) -> list[dict[str, object]]:
    if _duckdb_ is None:
        return []

    manifest_path = receipt_store_root / "manifest.jsonl"
    if not manifest_path.is_file():
        return []

    manifest_rows: list[dict[str, object]] = []
    with manifest_path.open("r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                manifest_rows.append(json.loads(line_str))
            except json.JSONDecodeError:
                continue

    conn = _duckdb_.connect(":memory:")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {_GOVERNANCE_DECISIONS_TABLE}")
        conn.execute(
            f"CREATE TABLE {_GOVERNANCE_DECISIONS_TABLE} ("
            "envelope_id VARCHAR, receipt_kind VARCHAR, session_id VARCHAR, "
            "created_at VARCHAR, governance_decision_id VARCHAR, "
            "decision_status VARCHAR, surface VARCHAR, authority_tier VARCHAR, "
            "capability_id VARCHAR, schema_version VARCHAR, "
            "content_light_classification VARCHAR)"
        )

        insert_params = [
            _row_to_query_params(r) for r in manifest_rows if r.get("envelope_id")
        ]
        if insert_params:
            placeholders = ", ".join(["?"] * len(insert_params[0]))
            conn.executemany(
                f"INSERT INTO {_GOVERNANCE_DECISIONS_TABLE} VALUES ({placeholders})",
                insert_params,
            )

        result = conn.execute(query, params or [])
        return _rows_to_dicts(result)
    except Exception:
        return []
    finally:
        conn.close()


def _no_duckdb_response() -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.duckdb_governance_decisions_projection.v1",
        "projection_kind": _PROJECTION_KIND,
        "status": "duckdb_not_available",
        "generated_at": _now_iso(),
        "content_light": True,
        "mutation_authority": False,
        "read_side_only": True,
        "raw_payloads_exposed": False,
    }


def _build_failed_response(
    error: str, diagnostics: list[dict[str, object]]
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.duckdb_governance_decisions_projection.v1",
        "projection_kind": _PROJECTION_KIND,
        "status": "build_failed",
        "generated_at": _now_iso(),
        "error": error,
        "content_light": True,
        "mutation_authority": False,
        "read_side_only": True,
        "raw_payloads_exposed": False,
        "diagnostics": diagnostics,
    }


def _row_to_params(
    row: dict[str, object], idx: int, manifest_sha256: str, envelopes_dir: Path
) -> tuple[object, ...]:
    eid = str(row["envelope_id"])

    def s(key: str) -> str | None:
        v = row.get(key)
        return str(v) if v is not None else None

    return (
        eid,
        str(row.get("receipt_kind", "")),
        s("session_id"),
        str(row.get("created_at", "")),
        s("governance_decision_id"),
        s("decision_status"),
        s("surface"),
        s("authority_tier"),
        s("capability_id"),
        str(row.get("schema_version", "")),
        s("content_light_classification"),
        idx,
        manifest_sha256,
        _now_iso(),
        str(envelopes_dir / eid[:2] / f"{eid}.json"),
    )


def _row_to_query_params(row: dict[str, object]) -> tuple[object, ...]:
    def s(key: str) -> str | None:
        v = row.get(key)
        return str(v) if v is not None else None

    return (
        str(row.get("envelope_id", "")),
        str(row.get("receipt_kind", "")),
        s("session_id"),
        str(row.get("created_at", "")),
        s("governance_decision_id"),
        s("decision_status"),
        s("surface"),
        s("authority_tier"),
        s("capability_id"),
        str(row.get("schema_version", "")),
        s("content_light_classification"),
    )


def _build_query_results(conn: Any) -> dict[str, list[dict[str, object]]]:
    results: dict[str, list[dict[str, object]]] = {}
    t = _GOVERNANCE_DECISIONS_TABLE
    for label, sql in [
        (
            "recent_decisions",
            f"SELECT governance_decision_id, surface, decision_status, created_at FROM {t} ORDER BY created_at DESC LIMIT 10",
        ),
        (
            "surface_status_summary",
            f"SELECT surface, decision_status, COUNT(*) AS cnt FROM {t} GROUP BY surface, decision_status ORDER BY cnt DESC",
        ),
        (
            "authority_tier_summary",
            f"SELECT authority_tier, COUNT(*) AS cnt FROM {t} GROUP BY authority_tier ORDER BY cnt DESC",
        ),
    ]:
        try:
            results[label] = _rows_to_dicts(conn.execute(sql))
        except Exception:
            pass
    return results


__all__ = [
    "HAS_DUCKDB",
    "build_governance_decisions_projection",
    "query_governance_decisions",
]

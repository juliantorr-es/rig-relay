from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

try:
    import duckdb

    HAS_DUCKDB = True
    DUCKDB_VERSION: str | None = duckdb.__version__
except ImportError:
    HAS_DUCKDB = False
    DUCKDB_VERSION = None
    duckdb = None  # type: ignore[assignment]

DEFAULT_EVENT_FABRIC_PATH = Path(".build/rig-relay/events/event_fabric_v1.jsonl")

_BRIDGE_EVENT_PATTERNS: list[str] = [
    "bridge.connection.begin",
    "bridge.auth.succeeded",
    "bridge.backend_loop.started",
    "bridge.backend_loop.stopped",
    "bridge.status.updated",
    "bridge.first_status.sent",
    "bridge.heartbeat.sent",
    "bridge.backend_stale.detected",
    "bridge.disconnect",
    "bridge.projection_loop.error",
    "bridge.reconnect_failed",
]

_RECONNECT_FAILED_PATTERNS: list[str] = [
    "runtime.reconnect_failed",
    "bridge.reconnect_failed",
]

_CONSUMER_ERROR_PATTERNS: list[str] = [
    "runtime.consumer_error",
    "bridge.projection_loop.error",
]


def _category_prefix(event_type: str) -> str:
    dot_idx = event_type.find(".")
    if dot_idx == -1:
        return "unknown"
    return event_type[:dot_idx]


def _count_malformed_lines(paths: list[Path]) -> int:
    malformed = 0
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
        except Exception:
            pass
    return malformed


def _git_info() -> tuple[str, str]:
    branch = "unknown"
    head = "unknown"
    try:
        import subprocess

        br = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if br.returncode == 0:
            branch = br.stdout.strip()
        hr = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        if hr.returncode == 0:
            head = hr.stdout.strip()
    except Exception:
        pass
    return branch, head


def _build_empty_manifest(status: str = "skipped") -> list[dict[str, Any]]:
    return [
        {
            "query_id": "event_count",
            "purpose": "Count total events in the fabric",
            "input_relation": "event_fabric_jsonl",
            "output_field": "event_count",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "event_type_counts",
            "purpose": "Top 25 event types by count",
            "input_relation": "event_fabric_jsonl",
            "output_field": "event_type_counts",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "event_category_counts",
            "purpose": "Count by dotted category prefix",
            "input_relation": "event_fabric_jsonl",
            "output_field": "event_category_counts",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "producer_counts",
            "purpose": "Count events by producer",
            "input_relation": "event_fabric_jsonl",
            "output_field": "producer_counts",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "sensitivity_class_counts",
            "purpose": "Count by sensitivity class",
            "input_relation": "event_fabric_jsonl",
            "output_field": "sensitivity_class_counts",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "redaction_status_counts",
            "purpose": "Count by redaction status",
            "input_relation": "event_fabric_jsonl",
            "output_field": "redaction_status_counts",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "bridge_lifecycle_summary",
            "purpose": "Bridge event counts by type",
            "input_relation": "event_fabric_jsonl",
            "output_field": "bridge_lifecycle_summary",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "resource_pressure_summary",
            "purpose": "Counts of reconnect_failed, queue_pressure.high, consumer_error events",
            "input_relation": "event_fabric_jsonl",
            "output_field": "resource_pressure_summary",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "consumer_error_summary",
            "purpose": "Consumer error event count",
            "input_relation": "event_fabric_jsonl",
            "output_field": "consumer_error_summary",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "reconnect_pressure_summary",
            "purpose": "Reconnect failed event count",
            "input_relation": "event_fabric_jsonl",
            "output_field": "reconnect_pressure_summary",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "none",
            "status": status,
        },
        {
            "query_id": "causal_chain_summary",
            "purpose": "OBSERVED vs CORRELATED_ONLY causal link counts",
            "input_relation": "event_fabric_jsonl",
            "output_field": "causal_chain_summary",
            "read_side_only": True,
            "mutation_risk": "none",
            "redaction_risk": "low",
            "status": status,
        },
    ]


def build_event_fabric_duckdb_projection(
    log_paths: list[Path] | None = None,
) -> dict[str, Any]:
    branch, head = _git_info()

    if log_paths is None:
        log_paths = [DEFAULT_EVENT_FABRIC_PATH]

    malformed = _count_malformed_lines(log_paths)

    existing_paths = [p for p in log_paths if p.exists()]
    if not existing_paths:
        return {
            "schema_version": "rig.event.duckdb_projection_report.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "no_input_logs",
            "branch": branch,
            "head": head,
            "source_event_logs": [str(p) for p in log_paths],
            "duckdb_available": HAS_DUCKDB,
            "duckdb_version": DUCKDB_VERSION,
            "read_side_only": True,
            "mutation_authority": False,
            "malformed_lines": malformed,
            **_empty_query_results(log_paths, _build_empty_manifest("skipped")),
            "errors": ["No event fabric JSONL files found."]
            if malformed == 0
            else [
                "No event fabric JSONL files found.",
                f"{malformed} malformed lines across input paths.",
            ],
        }

    file_paths = [str(p) for p in existing_paths]

    if not HAS_DUCKDB:
        return {
            "schema_version": "rig.event.duckdb_projection_report.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "duckdb_not_available",
            "branch": branch,
            "head": head,
            "source_event_logs": [str(p) for p in log_paths],
            "duckdb_available": False,
            "duckdb_version": DUCKDB_VERSION,
            "read_side_only": True,
            "mutation_authority": False,
            "malformed_lines": malformed,
            **_empty_query_results(log_paths, _build_empty_manifest("skipped")),
            "errors": [
                "DuckDB is not available. Install duckdb to enable projections."
            ],
        }

    import duckdb as _duckdb

    con = _duckdb.connect(database=":memory:")
    errors: list[str] = []
    manifest = _build_empty_manifest()

    event_count = 0
    event_type_counts: dict[str, int] = {}
    event_category_counts: dict[str, int] = {}
    producer_counts: dict[str, int] = {}
    sensitivity_class_counts: dict[str, int] = {}
    redaction_status_counts: dict[str, int] = {}
    bridge_lifecycle_summary: dict[str, int] = {}
    resource_pressure_summary: dict[str, int] = {
        "reconnect_failed_count": 0,
        "queue_pressure_high_count": 0,
        "consumer_error_count": 0,
    }
    consumer_error_summary: dict[str, int] = {"consumer_error_count": 0}
    reconnect_pressure_summary: dict[str, int] = {"reconnect_failed_count": 0}
    causal_chain_summary: dict[str, int] = {
        "observed_count": 0,
        "correlated_only_count": 0,
    }

    try:
        if len(file_paths) == 1:
            rel = con.read_json(file_paths[0])
        else:
            rel = con.read_json(file_paths[0])
            for fp in file_paths[1:]:
                rel = rel.union(con.read_json(fp))
    except Exception as e:
        errors.append(f"DuckDB read_json failed: {e}")
        con.close()
        return {
            "schema_version": "rig.event.duckdb_projection_report.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "read_failed",
            "branch": branch,
            "head": head,
            "source_event_logs": [str(p) for p in log_paths],
            "duckdb_available": True,
            "duckdb_version": DUCKDB_VERSION,
            "read_side_only": True,
            "mutation_authority": False,
            "malformed_lines": malformed,
            **_empty_query_results(log_paths, manifest),
            "errors": errors,
        }

    def _mark_succeeded(manifest_entry: dict[str, Any]) -> None:
        manifest_entry["status"] = "succeeded"

    # event_count
    m = manifest[0]
    try:
        res = rel.aggregate("count(*)").fetchone()
        if res:
            event_count = int(res[0])
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"event_count query failed: {e}")

    # event_type_counts (top 25)
    m = manifest[1]
    try:
        rows = (
            rel
            .aggregate("event_type, count(*) as cnt")
            .order("cnt DESC")
            .limit(25)
            .fetchall()
        )
        event_type_counts = {str(k): v for k, v in rows if k is not None}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"event_type_counts query failed: {e}")

    # event_category_counts
    m = manifest[2]
    try:
        rows = rel.aggregate("event_type, count(*)").fetchall()
        cat_counts: dict[str, int] = {}
        for row in rows:
            if row[0] is not None:
                cat = _category_prefix(str(row[0]))
                cat_counts[cat] = cat_counts.get(cat, 0) + int(row[1])
        event_category_counts = dict(
            sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
        )
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"event_category_counts query failed: {e}")

    # producer_counts
    m = manifest[3]
    try:
        rows = rel.aggregate("producer, count(*)").fetchall()
        producer_counts = {str(k): v for k, v in rows if k is not None}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"producer_counts query failed: {e}")

    # sensitivity_class_counts
    m = manifest[4]
    try:
        rows = rel.aggregate("sensitivity_class, count(*)").fetchall()
        sensitivity_class_counts = {str(k): v for k, v in rows if k is not None}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"sensitivity_class_counts query failed: {e}")

    # redaction_status_counts
    m = manifest[5]
    try:
        rows = rel.aggregate("redaction_status, count(*)").fetchall()
        redaction_status_counts = {str(k): v for k, v in rows if k is not None}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"redaction_status_counts query failed: {e}")

    # bridge_lifecycle_summary
    m = manifest[6]
    try:
        pattern_filter = " OR ".join(
            f"event_type = '{pt}'" for pt in _BRIDGE_EVENT_PATTERNS
        )
        filtered = rel.filter(pattern_filter)
        rows = filtered.aggregate("event_type, count(*)").fetchall()
        bridge_lifecycle_summary = {str(k): v for k, v in rows if k is not None}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"bridge_lifecycle_summary query failed: {e}")

    # resource_pressure_summary
    m = manifest[7]
    try:
        rc = 0
        qh = 0
        ce = 0
        try:
            rc_res = (
                rel
                .filter(
                    " OR ".join(
                        f"event_type = '{pt}'" for pt in _RECONNECT_FAILED_PATTERNS
                    )
                )
                .aggregate("count(*)")
                .fetchone()
            )
            if rc_res:
                rc = int(rc_res[0])
        except Exception:
            pass
        try:
            qh_res = (
                rel
                .filter("event_type = 'runtime.queue_pressure.high'")
                .aggregate("count(*)")
                .fetchone()
            )
            if qh_res:
                qh = int(qh_res[0])
        except Exception:
            pass
        try:
            ce_res = (
                rel
                .filter(
                    " OR ".join(
                        f"event_type = '{pt}'" for pt in _CONSUMER_ERROR_PATTERNS
                    )
                )
                .aggregate("count(*)")
                .fetchone()
            )
            if ce_res:
                ce = int(ce_res[0])
        except Exception:
            pass
        resource_pressure_summary = {
            "reconnect_failed_count": rc,
            "queue_pressure_high_count": qh,
            "consumer_error_count": ce,
        }
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"resource_pressure_summary query failed: {e}")

    # consumer_error_summary
    m = manifest[8]
    try:
        ce = 0
        try:
            ce_res = (
                rel
                .filter(
                    " OR ".join(
                        f"event_type = '{pt}'" for pt in _CONSUMER_ERROR_PATTERNS
                    )
                )
                .aggregate("count(*)")
                .fetchone()
            )
            if ce_res:
                ce = int(ce_res[0])
        except Exception:
            pass
        consumer_error_summary = {"consumer_error_count": ce}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"consumer_error_summary query failed: {e}")

    # reconnect_pressure_summary
    m = manifest[9]
    try:
        rc = 0
        try:
            rc_res = (
                rel
                .filter(
                    " OR ".join(
                        f"event_type = '{pt}'" for pt in _RECONNECT_FAILED_PATTERNS
                    )
                )
                .aggregate("count(*)")
                .fetchone()
            )
            if rc_res:
                rc = int(rc_res[0])
        except Exception:
            pass
        reconnect_pressure_summary = {"reconnect_failed_count": rc}
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"reconnect_pressure_summary query failed: {e}")

    # causal_chain_summary
    m = manifest[10]
    try:
        observed = 0
        correlated_only = 0
        try:
            o_res = (
                rel
                .filter("causation_id IS NOT NULL AND causation_id != ''")
                .aggregate("count(*)")
                .fetchone()
            )
            if o_res:
                observed = int(o_res[0])
        except Exception:
            pass
        try:
            c_res = (
                rel
                .filter(
                    "correlation_id IS NOT NULL AND correlation_id != '' "
                    "AND (causation_id IS NULL OR causation_id = '')"
                )
                .aggregate("count(*)")
                .fetchone()
            )
            if c_res:
                correlated_only = int(c_res[0])
        except Exception:
            pass
        causal_chain_summary = {
            "observed_count": observed,
            "correlated_only_count": correlated_only,
        }
        _mark_succeeded(m)
    except Exception as e:
        errors.append(f"causal_chain_summary query failed: {e}")

    con.close()

    status = "partial" if errors else "succeeded"

    report: dict[str, Any] = {
        "schema_version": "rig.event.duckdb_projection_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "branch": branch,
        "head": head,
        "source_event_logs": [str(p) for p in log_paths],
        "duckdb_available": HAS_DUCKDB,
        "duckdb_version": DUCKDB_VERSION,
        "read_side_only": True,
        "mutation_authority": False,
        "malformed_lines": malformed,
        "event_count": event_count,
        "event_type_counts": event_type_counts,
        "event_category_counts": event_category_counts,
        "producer_counts": producer_counts,
        "sensitivity_class_counts": sensitivity_class_counts,
        "redaction_status_counts": redaction_status_counts,
        "bridge_lifecycle_summary": bridge_lifecycle_summary,
        "resource_pressure_summary": resource_pressure_summary,
        "consumer_error_summary": consumer_error_summary,
        "reconnect_pressure_summary": reconnect_pressure_summary,
        "causal_chain_summary": causal_chain_summary,
        "query_manifest": manifest,
        "redaction_summary": {
            "raw_payloads_exposed": False,
            "envelope_only": True,
            "payload_hash_only": False,
        },
        "telemetry_redaction_implications": [
            "Only envelope-level fields are extracted; raw payload data is never queried",
            "No persistent DuckDB database files are created",
            "DuckDB queries never write back to the append-only event log",
            "Event counts and category breakdowns are aggregated",
        ],
        "intentionally_deferred": [
            "payload-level inspection for resource usage telemetry",
            "causal chain depth analysis beyond observed/correlated counts",
            "time-series bucketing of pressure events",
        ],
        "recommended_next_slice": "Seed a small event fabric JSONL with example bridge and projection events, then re-run to validate the query path against real data.",
    }
    if errors:
        report["errors"] = errors
    return report


def _empty_query_results(
    log_paths: list[Path], manifest: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "event_count": 0,
        "event_type_counts": {},
        "event_category_counts": {},
        "producer_counts": {},
        "sensitivity_class_counts": {},
        "redaction_status_counts": {},
        "bridge_lifecycle_summary": {},
        "resource_pressure_summary": {
            "reconnect_failed_count": 0,
            "queue_pressure_high_count": 0,
            "consumer_error_count": 0,
        },
        "consumer_error_summary": {"consumer_error_count": 0},
        "reconnect_pressure_summary": {"reconnect_failed_count": 0},
        "causal_chain_summary": {"observed_count": 0, "correlated_only_count": 0},
        "query_manifest": manifest,
        "redaction_summary": {
            "raw_payloads_exposed": False,
            "envelope_only": True,
            "payload_hash_only": False,
        },
        "telemetry_redaction_implications": [
            "Only envelope-level fields are extracted; raw payload data is never queried",
            "No persistent DuckDB database files are created",
            "DuckDB queries never write back to the append-only event log",
            "Event counts and category breakdowns are aggregated",
        ],
        "source_event_logs": [str(p) for p in log_paths],
        "intentionally_deferred": [
            "DuckDB projection engine not available for this run"
        ],
        "recommended_next_slice": "Seed event fabric JSONL with events and ensure DuckDB is installed.",
    }


__all__ = ["DEFAULT_EVENT_FABRIC_PATH", "build_event_fabric_duckdb_projection"]

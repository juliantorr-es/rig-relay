"""Pre-built analytics views for the desktop cockpit.

Each view function takes an AnalyticsEngine instance and returns a list
of dicts with content-light analytics data. No raw prompts, secrets, or
private data are included.
"""

from __future__ import annotations

from typing import Any

WIDGET_REFRESH_INTERVALS: dict[str, int] = {
    "governance_gate_health": 30,
    "session_health_scorecard": 60,
    "tool_latency_heatmap": 120,
    "release_gate_blocker_burndown": 300,
    "dependency_risk_surface": 3600,
    "out_of_scope_findings": 300,
    "correlation_integrity": 120,
    "local_inference_capability": 60,
}


def _safe_query(engine: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return engine.execute_query(sql, params)
    except Exception:
        return []


def view_governance_gate_health(engine: Any) -> list[dict[str, Any]]:
    sql = """SELECT kind, severity, status, COUNT(*) AS count
FROM reports
WHERE kind != ''
GROUP BY kind, severity, status
ORDER BY count DESC
LIMIT 50"""
    rows = _safe_query(engine, sql)
    return _summarise_by_status(rows, "governance_gate_health")


def _summarise_by_status(
    rows: list[dict[str, Any]], view_kind: str
) -> list[dict[str, Any]]:
    if not rows:
        return [{"view_kind": view_kind, "status": "empty", "total": 0}]
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append({
            "view_kind": view_kind,
            "kind": row.get("kind", ""),
            "severity": row.get("severity", ""),
            "status": row.get("status", ""),
            "count": row.get("count", 0),
        })
    return result


def view_session_health_scorecard(engine: Any) -> list[dict[str, Any]]:
    """Aggregate session health indicators from fact_model_turns.

    Content-light: no raw prompts or completions. Counts, latencies, rates only.
    """
    session_sql = """SELECT session_id, COUNT(*) AS turn_count,
       SUM(latency_ms) AS total_latency_ms,
       SUM(input_token_count + output_token_count) AS total_tokens,
       SUM(CASE WHEN error_kind != '' THEN 1 ELSE 0 END) AS error_count,
       SUM(CASE WHEN finish_reason = 'tool_calls' THEN 1 ELSE 0 END) AS tool_call_turns
FROM fact_model_turns
GROUP BY session_id
ORDER BY turn_count DESC
LIMIT 20"""
    turns = _safe_query(engine, session_sql)
    if not turns:
        return [
            {"view_kind": "session_health_scorecard", "status": "empty", "sessions": 0}
        ]
    sessions: list[dict[str, Any]] = []
    for t in turns:
        turn_count = max(1, t.get("turn_count", 1))
        sessions.append({
            "session_id": t.get("session_id", "")[:12] + "...",
            "turn_count": t.get("turn_count", 0),
            "total_tokens": t.get("total_tokens", 0),
            "avg_latency_ms": round(t.get("total_latency_ms", 0) / turn_count),
            "error_rate": round(t.get("error_count", 0) / turn_count, 3),
            "tool_use_rate": round(t.get("tool_call_turns", 0) / turn_count, 3),
        })
    return [
        {
            "view_kind": "session_health_scorecard",
            "sessions": sessions,
            "total_sessions": len(sessions),
        }
    ]


def view_tool_latency_heatmap(engine: Any) -> list[dict[str, Any]]:
    """Tool latency distribution by tool name from fact_tool_invocations."""
    sql = """SELECT tool_name,
       COUNT(*) AS invocation_count,
       MIN(latency_ms) AS min_latency_ms,
       MAX(latency_ms) AS max_latency_ms,
       AVG(latency_ms) AS avg_latency_ms,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_latency_ms,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms
FROM fact_tool_invocations
GROUP BY tool_name
ORDER BY avg_latency_ms DESC
LIMIT 30"""
    rows = _safe_query(engine, sql)
    if not rows:
        return [{"view_kind": "tool_latency_heatmap", "status": "empty", "tools": 0}]
    result: list[dict[str, Any]] = []
    for r in rows:
        result.append({
            "tool_name": r.get("tool_name", ""),
            "invocation_count": r.get("invocation_count", 0),
            "min_latency_ms": r.get("min_latency_ms", 0),
            "max_latency_ms": r.get("max_latency_ms", 0),
            "avg_latency_ms": round(r.get("avg_latency_ms", 0)),
            "p50_latency_ms": round(r.get("p50_latency_ms", 0)),
            "p95_latency_ms": round(r.get("p95_latency_ms", 0)),
        })
    return [
        {
            "view_kind": "tool_latency_heatmap",
            "tools": result,
            "total_tools": len(result),
        }
    ]


def view_release_gate_blocker_burndown(engine: Any) -> list[dict[str, Any]]:
    """Open release gate blockers by status and severity."""
    sql = """SELECT status, severity, COUNT(*) AS count
FROM reports WHERE kind = 'release_gate_blocker' OR kind LIKE '%blocker%'
GROUP BY status, severity
ORDER BY count DESC
LIMIT 30"""
    rows = _safe_query(engine, sql)
    if not rows:
        return [
            {
                "view_kind": "release_gate_blocker_burndown",
                "status": "empty",
                "total_blockers": 0,
            }
        ]
    open_count = sum(
        r.get("count", 0) for r in rows if r.get("status") in {"open", "new"}
    )
    return [
        {
            "view_kind": "release_gate_blocker_burndown",
            "open_blockers": open_count,
            "total_blockers": sum(r.get("count", 0) for r in rows),
            "by_status": [
                {
                    "status": r.get("status", ""),
                    "severity": r.get("severity", ""),
                    "count": r.get("count", 0),
                }
                for r in rows
            ],
        }
    ]


def view_dependency_risk_surface(engine: Any) -> list[dict[str, Any]]:
    """Risk surface from dependency-related reports."""
    sql = """SELECT kind, severity, COUNT(*) AS count
FROM reports WHERE kind LIKE '%dependenc%' OR kind LIKE '%risk%' OR kind LIKE '%supply_chain%'
GROUP BY kind, severity
ORDER BY count DESC
LIMIT 20"""
    rows = _safe_query(engine, sql)
    if not rows:
        return [
            {
                "view_kind": "dependency_risk_surface",
                "status": "empty",
                "total_risks": 0,
            }
        ]
    return [
        {
            "view_kind": "dependency_risk_surface",
            "total_risks": sum(r.get("count", 0) for r in rows),
            "risks": [
                {
                    "kind": r.get("kind", ""),
                    "severity": r.get("severity", ""),
                    "count": r.get("count", 0),
                }
                for r in rows
            ],
        }
    ]


def view_out_of_scope_findings(engine: Any) -> list[dict[str, Any]]:
    """Out-of-scope findings from the canonical JSONL registry."""
    sql = """SELECT kind, severity, status, COUNT(*) AS count
FROM reports WHERE kind = 'out_of_scope_finding' OR kind LIKE '%finding%'
GROUP BY kind, severity, status
ORDER BY count DESC
LIMIT 50"""
    rows = _safe_query(engine, sql)
    if not rows:
        return [
            {
                "view_kind": "out_of_scope_findings",
                "status": "empty",
                "total_findings": 0,
            }
        ]
    return [
        {
            "view_kind": "out_of_scope_findings",
            "total_findings": sum(r.get("count", 0) for r in rows),
            "findings": _summarise_by_status(rows, "out_of_scope_findings"),
        }
    ]


def view_correlation_integrity(engine: Any) -> list[dict[str, Any]]:
    """Cross-store correlation integrity checks.

    Checks that reports, model turns, and tool invocations are internally
    consistent. Returns content-light integrity indicators only.
    """
    sql = """SELECT
  (SELECT COUNT(*) FROM reports) AS report_count,
  (SELECT COUNT(*) FROM fact_model_turns) AS turn_count,
  (SELECT COUNT(DISTINCT report_sha256) FROM reports WHERE report_sha256 != '') AS distinct_report_hashes,
  (SELECT COUNT(DISTINCT stable_prefix_sha256) FROM fact_model_turns WHERE stable_prefix_sha256 != '') AS distinct_prefix_hashes"""
    row = _safe_query(engine, sql)
    if not row:
        return [{"view_kind": "correlation_integrity", "status": "empty"}]
    r = row[0]
    report_count = r.get("report_count", 0) or 0
    turn_count = r.get("turn_count", 0) or 0
    healthy = (report_count > 0) == (turn_count > 0) and bool(
        r.get("distinct_report_hashes")
    ) == bool(r.get("distinct_prefix_hashes"))
    return [
        {
            "view_kind": "correlation_integrity",
            "report_count": report_count,
            "turn_count": turn_count,
            "distinct_report_hashes": r.get("distinct_report_hashes", 0),
            "distinct_prefix_hashes": r.get("distinct_prefix_hashes", 0),
            "integrity_status": "healthy" if healthy else "degraded",
        }
    ]


def view_local_inference_capability(engine: Any) -> list[dict[str, Any]]:
    """Local inference capability summary from model turn data."""
    sql = """SELECT provider, model, COUNT(*) AS turn_count,
       SUM(latency_ms) AS total_latency_ms,
       AVG(CASE WHEN latency_ms > 0 THEN output_token_count * 1000.0 / latency_ms ELSE 0 END) AS tokens_per_sec
FROM fact_model_turns
GROUP BY provider, model
ORDER BY turn_count DESC
LIMIT 20"""
    rows = _safe_query(engine, sql)
    if not rows:
        return [
            {
                "view_kind": "local_inference_capability",
                "status": "empty",
                "providers": 0,
            }
        ]
    result: list[dict[str, Any]] = []
    for r in rows:
        result.append({
            "provider": r.get("provider", ""),
            "model": r.get("model", ""),
            "turn_count": r.get("turn_count", 0),
            "avg_latency_ms": round(
                r.get("total_latency_ms", 0) / max(1, r.get("turn_count", 1))
            ),
            "tokens_per_sec": round(r.get("tokens_per_sec", 0), 1),
        })
    return [
        {
            "view_kind": "local_inference_capability",
            "providers": result,
            "total_providers": len(result),
        }
    ]


_SQL_VIEWS: dict[str, str] = {
    "governance_gate_health": (
        "SELECT event_name AS kind, "
        "COALESCE(CAST(payload ->> '$.severity' AS VARCHAR), 'unknown') AS severity, "
        "COALESCE(CAST(payload ->> '$.status' AS VARCHAR), 'unknown') AS status, "
        "COUNT(*) AS count "
        "FROM observability "
        "WHERE event_name LIKE '%governance%' OR event_name LIKE '%guard%' "
        "GROUP BY event_name, severity, status ORDER BY count DESC LIMIT 50"
    ),
    "session_health_scorecard": (
        "SELECT session_id, COUNT(*) AS event_count, "
        "COUNT(DISTINCT event_name) AS distinct_event_types, "
        "MIN(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS min_latency_ms, "
        "MAX(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS max_latency_ms, "
        "AVG(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS avg_latency_ms "
        "FROM observability "
        "GROUP BY session_id ORDER BY event_count DESC LIMIT 20"
    ),
    "tool_latency_heatmap": (
        "SELECT COALESCE(CAST(payload ->> '$.tool_name' AS VARCHAR), 'unknown') AS tool_name, "
        "COUNT(*) AS invocation_count, "
        "MIN(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS min_latency_ms, "
        "MAX(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS max_latency_ms, "
        "AVG(try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS avg_latency_ms, "
        "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS p50_latency_ms, "
        "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY try_cast(payload ->> '$.duration_ms' AS DOUBLE)) AS p95_latency_ms "
        "FROM observability "
        "WHERE event_name = 'rig.relay.tool.call_completed' "
        "GROUP BY tool_name ORDER BY avg_latency_ms DESC LIMIT 30"
    ),
    "release_gate_blocker_burndown": (
        "SELECT "
        "COALESCE(CAST(payload ->> '$.status' AS VARCHAR), 'unknown') AS status, "
        "COALESCE(CAST(payload ->> '$.severity' AS VARCHAR), 'unknown') AS severity, "
        "COUNT(*) AS count "
        "FROM observability "
        "WHERE event_name LIKE '%blocker%' OR event_name LIKE '%release_gate%' "
        "GROUP BY status, severity ORDER BY count DESC LIMIT 30"
    ),
    "dependency_risk_surface": (
        "SELECT event_name AS kind, "
        "COALESCE(CAST(payload ->> '$.severity' AS VARCHAR), 'unknown') AS severity, "
        "COUNT(*) AS count "
        "FROM observability "
        "WHERE event_name LIKE '%dependenc%' OR event_name LIKE '%risk%' OR event_name LIKE '%supply%' "
        "GROUP BY event_name, severity ORDER BY count DESC LIMIT 20"
    ),
    "out_of_scope_findings": (
        "SELECT event_name AS kind, "
        "COALESCE(CAST(payload ->> '$.severity' AS VARCHAR), 'unknown') AS severity, "
        "COALESCE(CAST(payload ->> '$.status' AS VARCHAR), 'unknown') AS status, "
        "COUNT(*) AS count "
        "FROM observability "
        "WHERE event_name LIKE '%finding%' OR event_name LIKE '%out_of_scope%' "
        "GROUP BY event_name, severity, status ORDER BY count DESC LIMIT 50"
    ),
    "correlation_integrity": (
        "SELECT "
        "(SELECT COUNT(*) FROM observability) AS obs_count, "
        "(SELECT COUNT(*) FROM receipts) AS receipt_count, "
        "(SELECT COUNT(*) FROM trace_events) AS trace_count, "
        "(SELECT COUNT(DISTINCT session_id) FROM observability) AS distinct_sessions"
    ),
    "local_inference_capability": (
        "SELECT "
        "COALESCE(CAST(payload ->> '$.provider' AS VARCHAR), 'unknown') AS provider, "
        "COALESCE(CAST(payload ->> '$.model' AS VARCHAR), 'unknown') AS model, "
        "COUNT(*) AS turn_count, "
        "SUM(try_cast(payload ->> '$.latency_ms' AS DOUBLE)) AS total_latency_ms "
        "FROM observability "
        "WHERE event_name LIKE '%local_inference%' OR event_name LIKE '%model_turn%' "
        "GROUP BY provider, model ORDER BY turn_count DESC LIMIT 20"
    ),
}

VIEW_FUNCTIONS: dict[str, Any] = {
    name: (lambda n=name: _SQL_VIEWS[n]) for name in _SQL_VIEWS
}

_KEBAB_ALIASES: dict[str, str] = {
    "governance-gate-health": "governance_gate_health",
    "session-health": "session_health_scorecard",
    "tool-latency-distribution": "tool_latency_heatmap",
    "release-gate-blocker-burndown": "release_gate_blocker_burndown",
    "dependency-risk-surface": "dependency_risk_surface",
    "out-of-scope-findings": "out_of_scope_findings",
    "correlation-integrity": "correlation_integrity",
    "local-inference-capability": "local_inference_capability",
}

VIEW_FUNCTIONS.update({
    kebab: VIEW_FUNCTIONS[underscore]
    for kebab, underscore in _KEBAB_ALIASES.items()
    if underscore in VIEW_FUNCTIONS
})


__all__ = [
    "VIEW_FUNCTIONS",
    "WIDGET_REFRESH_INTERVALS",
    "view_correlation_integrity",
    "view_dependency_risk_surface",
    "view_governance_gate_health",
    "view_local_inference_capability",
    "view_out_of_scope_findings",
    "view_release_gate_blocker_burndown",
    "view_session_health_scorecard",
    "view_tool_latency_heatmap",
]

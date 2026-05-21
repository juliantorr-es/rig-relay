"""Analytics projection builder for Rig Relay's desktop cockpit.

Reads canonical sources through the AnalyticsEngine, computes pre-built
views, and packages results as projection data. Content-light: no raw
prompts, secrets, or private data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rig_relay.analytics import HAS_DUCKD, load_jsonl
from rig_relay.analytics.engine import AnalyticsEngine
from rig_relay.analytics.views import (
    WIDGET_REFRESH_INTERVALS,
    view_correlation_integrity,
    view_dependency_risk_surface,
    view_governance_gate_health,
    view_local_inference_capability,
    view_out_of_scope_findings,
    view_release_gate_blocker_burndown,
    view_session_health_scorecard,
    view_tool_latency_heatmap,
)

ALL_WIDGET_IDS = [
    "governance_gate_health",
    "session_health_scorecard",
    "tool_latency_heatmap",
    "release_gate_blocker_burndown",
    "dependency_risk_surface",
    "out_of_scope_findings",
    "correlation_integrity",
    "local_inference_capability",
]

_VIEW_FUNCTIONS: dict[str, Any] = {
    "governance_gate_health": view_governance_gate_health,
    "session_health_scorecard": view_session_health_scorecard,
    "tool_latency_heatmap": view_tool_latency_heatmap,
    "release_gate_blocker_burndown": view_release_gate_blocker_burndown,
    "dependency_risk_surface": view_dependency_risk_surface,
    "out_of_scope_findings": view_out_of_scope_findings,
    "correlation_integrity": view_correlation_integrity,
    "local_inference_capability": view_local_inference_capability,
}

_FACT_TABLES_SCHEMA: dict[str, str] = {
    "fact_model_turns": (
        "model_turn_id VARCHAR, session_id VARCHAR, agent_id VARCHAR, "
        "provider VARCHAR, model VARCHAR, mode VARCHAR, "
        "started_at VARCHAR, completed_at VARCHAR, latency_ms DOUBLE, "
        "input_token_count BIGINT, output_token_count BIGINT, "
        "context_window BIGINT, stable_prefix_sha256 VARCHAR, "
        "dynamic_suffix_sha256 VARCHAR, tool_call_count BIGINT, "
        "malformed_tool_call_count BIGINT, retry_count BIGINT, "
        "finish_reason VARCHAR, error_kind VARCHAR, cost_estimate DOUBLE"
    ),
    "fact_bash_invocations": (
        "bash_invocation_id VARCHAR, session_id VARCHAR, "
        "command_family VARCHAR, command_text_hash VARCHAR, "
        "exit_code BIGINT, duration_ms DOUBLE, "
        "reroute_target VARCHAR, environment_sanitized BOOLEAN, "
        "is_dangerous BOOLEAN, start_time VARCHAR"
    ),
    "fact_tool_invocations": (
        "tool_name VARCHAR, invocation_id VARCHAR, session_id VARCHAR, "
        "latency_ms DOUBLE, success BOOLEAN, error_kind VARCHAR"
    ),
}


def build_analytics_projection(
    widgets: list[str] | None = None, reports_root: str | None = None
) -> dict[str, Any]:
    """Build an analytics projection envelope.

    Reads canonical sources through the AnalyticsEngine, computes
    pre-built views, and packages results as projection data.
    Content-light: no raw prompts, secrets, or private data.

    Args:
        widgets: Specific widget IDs to compute. If None, compute all 8.
        reports_root: Optional path to the reports JSONL directory.

    Returns:
        Dict with schema_version, generated_at, and widgets list.
        Each widget has: widget_id, data (list of dicts), optional error.
    """
    selected = list(widgets) if widgets is not None else list(ALL_WIDGET_IDS)

    engine: AnalyticsEngine | None = None
    engine_error: str | None = None

    if HAS_DUCKD:
        try:
            engine = AnalyticsEngine()
            _ingest_ledgers(engine, reports_root)
        except Exception as exc:
            engine = None
            engine_error = str(exc)
    else:
        engine_error = "DuckDB not available"

    result: list[dict[str, Any]] = []
    for widget_id in selected:
        widget_entry: dict[str, Any] = {
            "widget_id": widget_id,
            "refresh_interval_s": WIDGET_REFRESH_INTERVALS.get(widget_id, 120),
        }
        try:
            if engine is None:
                widget_entry["error"] = engine_error or "Analytics engine unavailable"
                widget_entry["data"] = []
            else:
                view_fn = _VIEW_FUNCTIONS.get(widget_id)
                if view_fn is None:
                    widget_entry["error"] = f"Unknown widget: {widget_id}"
                    widget_entry["data"] = []
                else:
                    widget_entry["data"] = view_fn(engine)
                    widget_entry["error"] = None
        except Exception as exc:
            widget_entry["error"] = str(exc)[:500]
            widget_entry["data"] = []

        result.append(widget_entry)

    if engine is not None:
        try:
            engine.close()
        except Exception:
            pass

    return {
        "schema_version": "rig.relay.analytics_projection.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "widgets": result,
        "engine_available": engine is not None,
    }


def _default_reports_dir() -> Path:
    return Path(".rig") / "reports"


def _ingest_ledgers(engine: AnalyticsEngine, reports_root: str | None = None) -> None:
    root = Path(reports_root) if reports_root else _default_reports_dir()

    if root.is_dir():
        rp = root / "reports.jsonl"
        if rp.is_file():
            load_result = load_jsonl(rp)
            from rig_relay.analytics import (
                create_reports_table,
                normalize_report_record,
            )

            normalized = [normalize_report_record(r) for r in load_result.valid_records]
            create_reports_table(engine.con, normalized)

    _ensure_fact_tables(engine)


def _ensure_fact_tables(engine: AnalyticsEngine) -> None:
    con = engine.con
    for table_name, schema_sql in _FACT_TABLES_SCHEMA.items():
        try:
            con.sql(f"SELECT 1 FROM {table_name} LIMIT 0")
        except Exception:
            try:
                con.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema_sql})")
            except Exception:
                pass


__all__ = ["ALL_WIDGET_IDS", "build_analytics_projection"]

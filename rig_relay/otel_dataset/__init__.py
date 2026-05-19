from __future__ import annotations

from rig_relay.otel_dataset._aggregate import (
    aggregate_otel_runs,
    build_hardening_shortlist,
    build_run_manifest,
    load_normalized_run,
    validate_aggregate_outputs,
    write_aggregate_report,
)
from rig_relay.otel_dataset._ingest import ingest_otel_dataset
from rig_relay.otel_dataset._normalize import normalize_otel_capture
from rig_relay.otel_dataset._proposal import (
    build_tool_hardening_proposal,
    classify_recommended_lane,
    compute_priority_score,
    load_trend_artifacts as load_tool_hardening_trend_artifacts,
    rank_hardening_deltas,
    validate_tool_hardening_outputs,
    write_tool_hardening_proposal,
)
from rig_relay.otel_dataset._redact import redact_otel_attributes
from rig_relay.otel_dataset._summarize import build_tool_behavior_summary
from rig_relay.otel_dataset._trend import (
    classify_trend,
    compare_otel_aggregate_runs,
    compute_hardening_deltas,
    load_aggregate_run,
    validate_trend_outputs,
    write_trend_report,
)

__all__ = [
    "aggregate_otel_runs",
    "build_hardening_shortlist",
    "build_run_manifest",
    "build_tool_behavior_summary",
    "build_tool_hardening_proposal",
    "classify_recommended_lane",
    "classify_trend",
    "compare_otel_aggregate_runs",
    "compute_hardening_deltas",
    "compute_priority_score",
    "ingest_otel_dataset",
    "load_aggregate_run",
    "load_normalized_run",
    "load_tool_hardening_trend_artifacts",
    "normalize_otel_capture",
    "rank_hardening_deltas",
    "redact_otel_attributes",
    "validate_aggregate_outputs",
    "validate_tool_hardening_outputs",
    "validate_trend_outputs",
    "write_aggregate_report",
    "write_tool_hardening_proposal",
    "write_trend_report",
]

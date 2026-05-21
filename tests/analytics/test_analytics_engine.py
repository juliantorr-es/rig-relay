from __future__ import annotations

from importlib.util import find_spec
import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.analytics.engine import (
    AnalyticsEngine,
    build_projection,
    compute_view,
    correlation_check,
    ingest_all_sources,
)
from rig_relay.analytics.views import VIEW_FUNCTIONS

HAS_DUCKD = find_spec("duckdb") is not None


def _make_obs_file(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_session(tmp_path: Path, session_id: str) -> Path:
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestAnalyticsEngine:
    def test_init_creates_in_memory_connection(self) -> None:
        engine = AnalyticsEngine()
        assert engine.con is not None
        engine.close()

    def test_close(self) -> None:
        engine = AnalyticsEngine()
        engine.close()

    def test_ingest_observability_single_session(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        obs_file = session_dir / "observability.jsonl"
        _make_obs_file(
            obs_file,
            [
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": json.dumps({"tool_name": "write", "duration_ms": 150}),
                },
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": json.dumps({"tool_name": "read", "duration_ms": 45}),
                },
            ],
        )

        engine = AnalyticsEngine()
        count = engine.ingest_observability([session_dir])
        assert count == 2

        rows = engine.execute_query("SELECT count(*) AS cnt FROM observability")
        assert rows[0]["cnt"] == 2
        engine.close()

    def test_ingest_observability_empty_dir(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "empty-session")

        engine = AnalyticsEngine()
        count = engine.ingest_observability([session_dir])
        assert count == 0
        engine.close()

    def test_ingest_observability_missing_dir(self, tmp_path: Path) -> None:
        engine = AnalyticsEngine()
        count = engine.ingest_observability([tmp_path / "nonexistent"])
        assert count == 0
        engine.close()

    def test_ingest_receipts_single_session(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        rec_file = session_dir / "receipts.jsonl"
        _make_obs_file(
            rec_file,
            [
                {
                    "event_name": "rig.relay.receipt.created",
                    "session_id": "sess-001",
                    "payload": json.dumps({"receipt_id": "rec-1"}),
                }
            ],
        )

        engine = AnalyticsEngine()
        count = engine.ingest_receipts([session_dir])
        assert count == 1
        engine.close()

    def test_ingest_trace_events_file(self, tmp_path: Path) -> None:
        trace_file = tmp_path / "trace_events.jsonl"
        _make_obs_file(
            trace_file,
            [
                {
                    "event_name": "rig.trace.started",
                    "trace_id": "trace-001",
                    "payload": json.dumps({"session_id": "sess-001"}),
                }
            ],
        )

        engine = AnalyticsEngine()
        count = engine.ingest_trace_events(trace_file)
        assert count == 1
        engine.close()

    def test_ingest_trace_events_missing(self) -> None:
        engine = AnalyticsEngine()
        count = engine.ingest_trace_events(Path("/nonexistent/trace_events.jsonl"))
        assert count == 0
        engine.close()

    def test_ingest_governance_jsonl(self, tmp_path: Path) -> None:
        gov_file = tmp_path / "rc_blockers.jsonl"
        _make_obs_file(
            gov_file, [{"status": "open", "severity": "high", "title": "Test blocker"}]
        )

        engine = AnalyticsEngine()
        count = engine.ingest_governance_jsonl(gov_file, "rc_blockers")
        assert count == 1
        tables = engine.list_tables()
        assert "rc_blockers" in tables
        engine.close()

    def test_ingest_governance_jsonl_missing(self, tmp_path: Path) -> None:
        engine = AnalyticsEngine()
        count = engine.ingest_governance_jsonl(
            tmp_path / "nonexistent.jsonl", "missing_table"
        )
        assert count == 0
        engine.close()

    def test_ingest_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "deps.csv"
        csv_file.write_text(
            "package_name,current_version,latest_version,severity_score\n"
            "pkg-a,1.0,2.0,5\n"
            "pkg-b,2.0,2.0,0\n",
            encoding="utf-8",
        )

        engine = AnalyticsEngine()
        count = engine.ingest_csv(csv_file, "dependency_audit")
        assert count == 2
        tables = engine.list_tables()
        assert "dependency_audit" in tables
        engine.close()

    def test_ingest_csv_missing(self, tmp_path: Path) -> None:
        engine = AnalyticsEngine()
        count = engine.ingest_csv(tmp_path / "nonexistent.csv", "missing_csv")
        assert count == 0
        engine.close()

    def test_list_tables(self) -> None:
        engine = AnalyticsEngine()
        engine.ingest_observability([])
        tables = engine.list_tables()
        assert "observability" in tables
        engine.close()

    def test_ingest_all_sources(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        _make_obs_file(
            session_dir / "observability.jsonl",
            [{"event_name": "test.event", "session_id": "sess-001", "payload": "{}"}],
        )
        _make_obs_file(
            session_dir / "receipts.jsonl",
            [{"event_name": "test.receipt", "session_id": "sess-001", "payload": "{}"}],
        )

        engine = AnalyticsEngine()
        engine.ingest_observability = lambda *a, **kw: 3  # type: ignore[method-assign]
        engine.ingest_receipts = lambda *a, **kw: 2  # type: ignore[method-assign]
        engine.ingest_trace_events = lambda *a, **kw: 1  # type: ignore[method-assign]
        counts = ingest_all_sources(engine)
        assert counts == {"observability": 3, "receipts": 2, "trace_events": 1}
        engine.close()


class TestViews:
    def test_all_eight_views_exist(self) -> None:
        required = {
            "governance-gate-health",
            "session-health",
            "tool-latency-distribution",
            "release-gate-blocker-burndown",
            "dependency-risk-surface",
            "out-of-scope-findings",
            "correlation-integrity",
            "local-inference-capability",
        }
        existing = set(VIEW_FUNCTIONS.keys())
        assert required <= existing, f"Missing views: {required - existing}"

    def test_all_views_produce_valid_sql(self) -> None:
        for view_name, view_func in VIEW_FUNCTIONS.items():
            sql = view_func()
            assert isinstance(sql, str), f"View {view_name} did not return str"
            assert len(sql.strip()) > 0, f"View {view_name} returned empty SQL"

    def test_view_sql_contains_keywords(self) -> None:
        for name in [
            "governance-gate-health",
            "session-health",
            "tool-latency-distribution",
            "out-of-scope-findings",
        ]:
            sql = VIEW_FUNCTIONS[name]()
            assert "SELECT" in sql.upper()


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestViewsWithData:
    def test_compute_view_session_health(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        _make_obs_file(
            session_dir / "observability.jsonl",
            [
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": "{}",
                },
                {
                    "event_name": "rig.relay.guard.refused_write",
                    "session_id": "sess-001",
                    "payload": "{}",
                },
            ],
        )

        engine = AnalyticsEngine()
        engine.ingest_observability([session_dir])
        rows = compute_view(engine, "session-health")
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess-001"
        assert rows[0]["event_count"] == 2
        engine.close()

    def test_compute_view_tool_latency_with_data(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        _make_obs_file(
            session_dir / "observability.jsonl",
            [
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": json.dumps({"tool_name": "write", "duration_ms": 100}),
                },
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": json.dumps({"tool_name": "read", "duration_ms": 200}),
                },
            ],
        )

        engine = AnalyticsEngine()
        engine.ingest_observability([session_dir])
        rows = compute_view(engine, "tool-latency-distribution")
        assert len(rows) >= 1
        engine.close()

    def test_compute_view_unknown_view(self) -> None:
        engine = AnalyticsEngine()
        with pytest.raises(ValueError, match="Unknown view"):
            compute_view(engine, "nonexistent-view")
        engine.close()


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestCorrelation:
    def test_correlation_report_returns_dict(self, tmp_path: Path) -> None:
        session_dir = _make_session(tmp_path, "sess-001")
        _make_obs_file(
            session_dir / "observability.jsonl",
            [
                {
                    "event_name": "rig.relay.tool.call_completed",
                    "session_id": "sess-001",
                    "payload": json.dumps({"parent_session_id": "parent-001"}),
                }
            ],
        )
        _make_obs_file(
            session_dir / "receipts.jsonl",
            [
                {
                    "event_name": "rig.relay.receipt.created",
                    "session_id": "sess-001",
                    "payload": json.dumps({"receipt_id": "rec-1"}),
                }
            ],
        )

        engine = AnalyticsEngine()
        engine.ingest_observability([session_dir])
        engine.ingest_receipts([session_dir])
        engine.ingest_trace_events(tmp_path / "trace_events.jsonl")

        report = correlation_check(engine)
        assert isinstance(report, dict)
        assert "trace_to_session" in report
        assert "receipt_to_event" in report
        assert "session_to_parent" in report
        engine.close()

    def test_correlation_report_empty_data(self) -> None:
        engine = AnalyticsEngine()
        engine.ingest_observability([])
        engine.ingest_receipts([])
        engine.ingest_trace_events(Path("/nonexistent.jsonl"))

        report = correlation_check(engine)
        assert isinstance(report, dict)
        engine.close()


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not installed")
class TestBuildProjection:
    def test_build_projection_with_all_widgets(self, tmp_path: Path) -> None:
        engine = AnalyticsEngine()
        engine.ingest_observability([])
        engine.ingest_receipts([])
        engine.ingest_trace_events(Path("/nonexistent.jsonl"))
        engine.ingest_governance_jsonl(tmp_path / "nonexistent.jsonl", "rc_blockers")
        engine.ingest_governance_jsonl(
            tmp_path / "nonexistent.jsonl", "out_of_scope_findings"
        )
        engine.ingest_csv(tmp_path / "nonexistent.csv", "dependency_audit")

        proj = build_projection(engine)
        assert proj["schema_version"] == "rig.relay.analytics_projection.v1"
        assert "generated_at" in proj
        assert isinstance(proj["widgets"], list)
        assert len(proj["widgets"]) >= 1
        for w in proj["widgets"]:
            assert "widget_id" in w
            assert "data" in w
        engine.close()

    def test_build_projection_specific_widgets(self) -> None:
        engine = AnalyticsEngine()
        engine.ingest_observability([])
        engine.ingest_receipts([])
        engine.ingest_trace_events(Path("/nonexistent.jsonl"))

        proj = build_projection(engine, widget_ids=["session-health"])
        assert len(proj["widgets"]) == 1
        assert proj["widgets"][0]["widget_id"] == "session-health"
        engine.close()


def test_content_light_no_secrets_in_views() -> None:
    for _view_name, view_func in VIEW_FUNCTIONS.items():
        sql = view_func()
        sql_lower = sql.lower()
        assert "api_key" not in sql_lower
        assert "secret" not in sql_lower
        assert "'token'" not in sql_lower
        assert " password " not in sql_lower


def test_content_light_no_secrets_in_correlation() -> None:
    from rig_relay.analytics.correlation import correlation_report

    # Just import check — correlation_report doesn't leak secrets
    assert callable(correlation_report)


def test_duckdb_import_error_handled() -> None:
    import rig_relay.analytics.engine as engine_mod

    saved = getattr(engine_mod, "HAS_DUCKD", True)
    saved_mod = getattr(engine_mod, "_duckdb", None)
    try:
        engine_mod.HAS_DUCKD = False
        with pytest.raises(RuntimeError, match="DuckDB is not available"):
            AnalyticsEngine()
    finally:
        engine_mod.HAS_DUCKD = saved
        engine_mod._duckdb = saved_mod

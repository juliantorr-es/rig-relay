from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

from rig_relay.analytics.views import VIEW_FUNCTIONS
from rig_relay.core.logger import logger

try:
    import duckdb as _duckdb

    HAS_DUCKD = True
except ImportError:
    _duckdb = None
    HAS_DUCKD = False

CANONICAL_SESSION_ROOT = Path.home() / ".rig" / "relay" / "sessions"
CANONICAL_TRACES_PATH = Path.home() / ".rig" / "relay" / "trace_events.jsonl"
CANONICAL_REPORTS_PATH = Path(".rig/reports/reports.jsonl")


def _session_dirs(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def _jsonl_paths(session_dirs: list[Path], filename: str) -> list[Path]:
    return [d / filename for d in session_dirs]


class AnalyticsEngine:
    def __init__(self) -> None:
        if not HAS_DUCKD:
            raise RuntimeError("DuckDB is not available. Install with: uv add duckdb")
        self._con = cast(Any, _duckdb).connect(":memory:")

    @property
    def con(self) -> Any:
        return self._con

    def ingest_observability(self, session_dirs: list[Path] | None = None) -> int:
        """Read all observability.jsonl files into DuckDB table 'observability'."""
        if session_dirs is None:
            session_dirs = _session_dirs(CANONICAL_SESSION_ROOT)
        paths = _jsonl_paths(session_dirs, "observability.jsonl")
        existing = [p for p in paths if p.is_file()]
        if not existing:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS observability "
                "(event_name VARCHAR, session_id VARCHAR, payload VARCHAR)"
            )
            return 0
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE observability AS "
                f"SELECT * FROM read_json_auto({json.dumps([str(p) for p in existing])})"
            )
            count = self._con.execute(
                "SELECT count(*) AS cnt FROM observability"
            ).fetchone()[0]
            logger.info("Ingested observability rows=%s", count)
            return count
        except Exception:
            logger.warning("Failed to ingest observability files, creating empty table")
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS observability "
                "(event_name VARCHAR, session_id VARCHAR, payload VARCHAR)"
            )
            return 0

    def ingest_receipts(self, session_dirs: list[Path] | None = None) -> int:
        """Read all receipts.jsonl files into DuckDB table 'receipts'."""
        if session_dirs is None:
            session_dirs = _session_dirs(CANONICAL_SESSION_ROOT)
        paths = _jsonl_paths(session_dirs, "receipts.jsonl")
        existing = [p for p in paths if p.is_file()]
        if not existing:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS receipts "
                "(event_name VARCHAR, session_id VARCHAR, payload VARCHAR)"
            )
            return 0
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE receipts AS "
                f"SELECT * FROM read_json_auto({json.dumps([str(p) for p in existing])})"
            )
            count = self._con.execute(
                "SELECT count(*) AS cnt FROM receipts"
            ).fetchone()[0]
            logger.info("Ingested receipts rows=%s", count)
            return count
        except Exception:
            logger.warning("Failed to ingest receipts files, creating empty table")
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS receipts "
                "(event_name VARCHAR, session_id VARCHAR, payload VARCHAR)"
            )
            return 0

    def ingest_trace_events(self, traces_path: Path | None = None) -> int:
        """Read trace_events.jsonl into DuckDB table 'trace_events'."""
        path = traces_path or CANONICAL_TRACES_PATH
        if not path.is_file():
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS trace_events "
                "(event_name VARCHAR, trace_id VARCHAR, payload VARCHAR)"
            )
            return 0
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE trace_events AS "
                f"SELECT * FROM read_json_auto({json.dumps(str(path))})"
            )
            count = self._con.execute(
                "SELECT count(*) AS cnt FROM trace_events"
            ).fetchone()[0]
            logger.info("Ingested trace_events rows=%s", count)
            return count
        except Exception:
            logger.warning("Failed to ingest trace events, creating empty table")
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS trace_events "
                "(event_name VARCHAR, trace_id VARCHAR, payload VARCHAR)"
            )
            return 0

    def ingest_governance_jsonl(self, path: Path, table_name: str) -> int:
        """Read any JSONL file into a DuckDB table."""
        if not path.is_file():
            self._con.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} (value VARCHAR)"
            )
            return 0
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_json_auto({json.dumps(str(path))})"
            )
            count = self._con.execute(
                f"SELECT count(*) AS cnt FROM {table_name}"
            ).fetchone()[0]
            logger.info("Ingested table=%s rows=%s", table_name, count)
            return count
        except Exception:
            logger.warning("Failed to ingest governance JSONL table=%s", table_name)
            self._con.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} (value VARCHAR)"
            )
            return 0

    def ingest_csv(self, path: Path, table_name: str) -> int:
        """Read CSV into DuckDB table."""
        if not path.is_file():
            self._con.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} (value VARCHAR)"
            )
            return 0
        try:
            self._con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_csv_auto({json.dumps(str(path))}, header=true)"
            )
            count = self._con.execute(
                f"SELECT count(*) AS cnt FROM {table_name}"
            ).fetchone()[0]
            logger.info("Ingested CSV table=%s rows=%s", table_name, count)
            return count
        except Exception:
            logger.warning("Failed to ingest CSV table=%s", table_name)
            self._con.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} (value VARCHAR)"
            )
            return 0

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a DuckDB query and return results as a list of dicts."""
        result = self._con.execute(sql, params)
        columns = [d[0] for d in result.description]
        return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]

    def list_tables(self) -> list[str]:
        rows = self._con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._con.close()


def ingest_all_sources(
    engine: AnalyticsEngine, session_root: Path | None = None
) -> dict[str, int]:
    counts: dict[str, int] = {}
    session_dirs = _session_dirs(session_root) if session_root else None
    counts["observability"] = engine.ingest_observability(session_dirs)
    counts["receipts"] = engine.ingest_receipts(session_dirs)
    counts["trace_events"] = engine.ingest_trace_events()
    return counts


def compute_view(engine: AnalyticsEngine, view_name: str) -> list[dict[str, Any]]:
    view_func = VIEW_FUNCTIONS.get(view_name)
    if view_func is None:
        available = ", ".join(sorted(VIEW_FUNCTIONS.keys()))
        raise ValueError(f"Unknown view: {view_name}. Available: {available}")
    sql = view_func()
    return engine.execute_query(sql)


def correlation_check(engine: AnalyticsEngine) -> dict[str, Any]:
    from rig_relay.analytics.correlation import correlation_report

    return correlation_report(engine)


def build_projection(
    engine: AnalyticsEngine, widget_ids: list[str] | None = None
) -> dict[str, Any]:
    if widget_ids is None:
        widget_ids = sorted(VIEW_FUNCTIONS.keys())
    widgets: list[dict[str, Any]] = []
    for wid in widget_ids:
        try:
            data = compute_view(engine, wid)
            widgets.append({"widget_id": wid, "data": data})
        except Exception as exc:
            widgets.append({"widget_id": wid, "data": {}, "error": str(exc)})
    return {
        "schema_version": "rig.relay.analytics_projection.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "widgets": widgets,
    }

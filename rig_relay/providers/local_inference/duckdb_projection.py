"""DuckDB read-side projections — disposable in-memory analytics.

Consumes JSONL ledgers (benchmark samples, capability evidence rows).
DuckDB connections are ephemeral (in-memory, closed after query).
Never persists data to disk. Handles missing DuckDB gracefully.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import duckdb as _duckdb

    HAS_DUCKDB = True
except ImportError:
    _duckdb = None
    HAS_DUCKDB = False


def _error_no_duckdb() -> dict[str, Any]:
    return {
        "error": "DuckDB not available. Install with: uv add duckdb",
        "sample_count": 0,
    }


def _safe_percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100.0)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def compute_benchmark_summary_from_jsonl(jsonl_path: Path) -> dict[str, Any]:
    """Compute aggregate statistics from a capacity benchmark JSONL file.

    Uses a disposable in-memory DuckDB connection. Reads the JSONL
    with read_json_auto(), computes p50/p95 for latency_ms, ttft_ms,
    tokens_per_sec, and counts by status, error_class, task_profile.

    Returns a dict with aggregate results. On missing file: returns
    zeros. On missing DuckDB: returns an error dict.
    """
    if not HAS_DUCKDB:
        return _error_no_duckdb()

    if not jsonl_path.is_file():
        return {
            "sample_count": 0,
            "latency_ms_p50": None,
            "latency_ms_p95": None,
            "ttft_ms_p50": None,
            "ttft_ms_p95": None,
            "tokens_per_sec_p50": None,
            "tokens_per_sec_p95": None,
            "count_by_status": {},
            "count_by_error_class": {},
            "count_by_task_profile": {},
        }

    assert _duckdb is not None
    con = _duckdb.connect(database=":memory:")
    try:
        con.execute(
            f"CREATE TABLE samples AS SELECT * FROM read_json_auto('{jsonl_path!s}')"
        )

        row_result = con.execute("SELECT count(*) FROM samples").fetchone()
        sample_count: int = row_result[0] if row_result else 0
        if sample_count == 0:
            return {
                "sample_count": 0,
                "latency_ms_p50": None,
                "latency_ms_p95": None,
                "ttft_ms_p50": None,
                "ttft_ms_p95": None,
                "tokens_per_sec_p50": None,
                "tokens_per_sec_p95": None,
                "count_by_status": {},
                "count_by_error_class": {},
                "count_by_task_profile": {},
            }

        latencies = _column_floats(con, "latency_ms")
        ttfts = _column_floats(con, "ttft_ms")
        tps = _column_floats(con, "tokens_per_sec")

        count_by_status = _count_by_column(con, "status")
        count_by_error_class = _count_by_column(con, "error_class")
        count_by_task_profile = _count_by_column(con, "task_profile")

        return {
            "sample_count": sample_count,
            "latency_ms_p50": _safe_percentile(latencies, 50),
            "latency_ms_p95": _safe_percentile(latencies, 95),
            "ttft_ms_p50": _safe_percentile(ttfts, 50),
            "ttft_ms_p95": _safe_percentile(ttfts, 95),
            "tokens_per_sec_p50": _safe_percentile(tps, 50),
            "tokens_per_sec_p95": _safe_percentile(tps, 95),
            "count_by_status": count_by_status,
            "count_by_error_class": count_by_error_class,
            "count_by_task_profile": count_by_task_profile,
        }
    finally:
        con.close()


def compute_evidence_dataset_summary(jsonl_path: Path) -> dict[str, Any]:
    """Compute aggregate statistics from a capability evidence JSONL file.

    Uses a disposable in-memory DuckDB connection. Computes p50/p95
    for local_latency_ms, local_ttft_ms, local_tokens_per_sec, and
    counts by task_profile, machine_class, recommended_route,
    contract_passed.

    Returns a dict with aggregate results. On missing file: returns
    zeros. On missing DuckDB: returns an error dict.
    """
    if not HAS_DUCKDB:
        return _error_no_duckdb()

    if not jsonl_path.is_file():
        return {
            "sample_count": 0,
            "local_latency_ms_p50": None,
            "local_latency_ms_p95": None,
            "local_ttft_ms_p50": None,
            "local_ttft_ms_p95": None,
            "local_tokens_per_sec_p50": None,
            "local_tokens_per_sec_p95": None,
            "count_by_task_profile": {},
            "count_by_machine_class": {},
            "count_by_recommended_route": {},
            "contract_pass_rate": 0.0,
        }

    assert _duckdb is not None
    con = _duckdb.connect(database=":memory:")
    try:
        con.execute(
            f"CREATE TABLE evidence AS SELECT * FROM read_json_auto('{jsonl_path!s}')"
        )

        row_result = con.execute("SELECT count(*) FROM evidence").fetchone()
        sample_count: int = row_result[0] if row_result else 0
        if sample_count == 0:
            return {
                "sample_count": 0,
                "local_latency_ms_p50": None,
                "local_latency_ms_p95": None,
                "local_ttft_ms_p50": None,
                "local_ttft_ms_p95": None,
                "local_tokens_per_sec_p50": None,
                "local_tokens_per_sec_p95": None,
                "count_by_task_profile": {},
                "count_by_machine_class": {},
                "count_by_recommended_route": {},
                "contract_pass_rate": 0.0,
            }

        latencies = _column_floats(con, "local_latency_ms")
        ttfts = _column_floats(con, "local_ttft_ms")
        tps = _column_floats(con, "local_tokens_per_sec")

        count_by_task_profile = _count_by_column(con, "task_profile")
        count_by_machine_class = _count_by_column(con, "machine_class")
        count_by_recommended_route = _count_by_column(con, "recommended_route")

        pass_rate = 0.0
        try:
            pass_res = con.execute(
                "SELECT avg(cast(contract_passed as int)) FROM evidence WHERE contract_passed IS NOT NULL"
            ).fetchone()
            if pass_res and pass_res[0] is not None:
                pass_rate = float(pass_res[0])
        except Exception:
            pass

        return {
            "sample_count": sample_count,
            "local_latency_ms_p50": _safe_percentile(latencies, 50),
            "local_latency_ms_p95": _safe_percentile(latencies, 95),
            "local_ttft_ms_p50": _safe_percentile(ttfts, 50),
            "local_ttft_ms_p95": _safe_percentile(ttfts, 95),
            "local_tokens_per_sec_p50": _safe_percentile(tps, 50),
            "local_tokens_per_sec_p95": _safe_percentile(tps, 95),
            "count_by_task_profile": count_by_task_profile,
            "count_by_machine_class": count_by_machine_class,
            "count_by_recommended_route": count_by_recommended_route,
            "contract_pass_rate": pass_rate,
        }
    finally:
        con.close()


def _column_floats(con: Any, column: str) -> list[float]:
    for table_name in ("samples", "evidence"):
        try:
            rows = con.execute(
                f'SELECT cast("{column}" as double) FROM {table_name} '
                f'WHERE "{column}" IS NOT NULL'
            ).fetchall()
            if rows:
                return [float(r[0]) for r in rows if r[0] is not None]
        except Exception:
            continue
    return []


def _count_by_column(con: Any, column: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for table_name in ("samples", "evidence"):
        try:
            rows = con.execute(
                f'SELECT cast("{column}" as varchar), count(*) FROM {table_name} '
                f'WHERE "{column}" IS NOT NULL AND "{column}" != \'\' '
                f'GROUP BY "{column}" ORDER BY count(*) DESC'
            ).fetchall()
            for key, cnt in rows:
                if key not in result:
                    result[key] = 0
                result[key] += int(cnt)
            if result:
                return result
        except Exception:
            continue
    return result


__all__ = ["compute_benchmark_summary_from_jsonl", "compute_evidence_dataset_summary"]

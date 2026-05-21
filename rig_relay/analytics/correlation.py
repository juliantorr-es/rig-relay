from __future__ import annotations

from typing import Any

from rig_relay.core.logger import logger


def _safe_query(engine: Any, sql: str) -> list[dict[str, Any]]:
    try:
        return engine.execute_query(sql)
    except Exception as exc:
        logger.warning("Correlation query failed: %s", exc)
        return []


def _has_column(engine: Any, table: str, column: str) -> bool:
    try:
        rows = engine.execute_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, column),
        )
        return len(rows) > 0
    except Exception:
        return False


def _has_table(engine: Any, table: str) -> bool:
    try:
        rows = engine.execute_query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = ? AND table_schema = 'main'",
            (table,),
        )
        return len(rows) > 0
    except Exception:
        return False


def check_trace_to_session(engine: Any) -> list[dict[str, Any]]:
    if not _has_table(engine, "observability") or not _has_table(
        engine, "trace_events"
    ):
        return []

    if _has_column(engine, "trace_events", "payload"):
        join_clause = "ON o.session_id = CAST(t.payload ->> '$.session_id' AS VARCHAR)"
    elif _has_column(engine, "trace_events", "session_id"):
        join_clause = "ON o.session_id = t.session_id"
    else:
        return []

    return _safe_query(
        engine,
        f"""
        WITH session_traces AS (
          SELECT
            o.session_id,
            t.trace_id,
            COUNT(*) AS event_count
          FROM observability o
          JOIN trace_events t
            {join_clause}
          GROUP BY o.session_id, t.trace_id
        )
        SELECT
          session_id,
          trace_id,
          event_count
        FROM session_traces
        ORDER BY event_count DESC
        LIMIT 50
    """,
    )


def check_receipt_to_event(engine: Any) -> list[dict[str, Any]]:
    if not _has_table(engine, "observability") or not _has_table(engine, "receipts"):
        return []

    if _has_column(engine, "receipts", "payload"):
        join_clause = "ON o.session_id = CAST(r.payload ->> '$.session_id' AS VARCHAR)"
    elif _has_column(engine, "receipts", "session_id"):
        join_clause = "ON o.session_id = r.session_id"
    else:
        return []

    receipt_id_col = (
        "CAST(r.payload ->> '$.receipt_id' AS VARCHAR)"
        if _has_column(engine, "receipts", "payload")
        else "r.event_name"
    )

    return _safe_query(
        engine,
        f"""
        WITH receipt_links AS (
          SELECT
            o.session_id,
            o.event_name,
            COUNT(*) AS obs_count,
            COUNT(DISTINCT {receipt_id_col}) AS linked_receipts
          FROM observability o
          LEFT JOIN receipts r
            {join_clause}
          GROUP BY o.session_id, o.event_name
        )
        SELECT
          session_id,
          event_name,
          obs_count,
          linked_receipts,
          CASE
            WHEN linked_receipts = 0 THEN 'orphan'
            WHEN linked_receipts < obs_count THEN 'partial'
            ELSE 'complete'
          END AS linkage_status
        FROM receipt_links
        ORDER BY obs_count DESC
        LIMIT 50
    """,
    )


def check_session_to_parent(engine: Any) -> list[dict[str, Any]]:
    if not _has_table(engine, "observability"):
        return []

    if _has_column(engine, "observability", "payload"):
        return _safe_query(
            engine,
            """
            SELECT
              COALESCE(session_id, 'unknown') AS session_id,
              COALESCE(
                CAST(payload ->> '$.parent_session_id' AS VARCHAR), ''
              ) AS parent_session_id,
              COUNT(*) AS event_count
            FROM observability
            WHERE CAST(payload ->> '$.parent_session_id' AS VARCHAR) IS NOT NULL
              AND CAST(payload ->> '$.parent_session_id' AS VARCHAR) != ''
            GROUP BY session_id, CAST(payload ->> '$.parent_session_id' AS VARCHAR)
            ORDER BY event_count DESC
            LIMIT 50
        """,
        )

    return []


def correlation_report(engine: Any) -> dict[str, Any]:
    trace_results = check_trace_to_session(engine)
    receipt_results = check_receipt_to_event(engine)
    session_results = check_session_to_parent(engine)

    gap_count = sum(1 for r in receipt_results if r.get("linkage_status") == "orphan")
    partial_count = sum(
        1 for r in receipt_results if r.get("linkage_status") == "partial"
    )
    orphan_traces = sum(1 for r in trace_results if r.get("event_count", 0) == 0)
    duplicate_sessions = 0
    seen: set[str] = set()
    for r in session_results:
        sid = str(r.get("session_id", ""))
        if sid in seen:
            duplicate_sessions += 1
        seen.add(sid)

    return {
        "trace_to_session": {
            "linked_sessions": len(trace_results),
            "orphan_traces": orphan_traces,
        },
        "receipt_to_event": {
            "total_groups": len(receipt_results),
            "gap_count": gap_count,
            "partial_count": partial_count,
        },
        "session_to_parent": {
            "linked_count": len(session_results),
            "duplicate_sessions": duplicate_sessions,
        },
    }

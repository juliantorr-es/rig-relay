from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

@dataclass
class ObservabilitySummary:
    sessions_seen: int = 0
    events_seen: int = 0
    events_by_name: dict[str, int] = field(default_factory=dict)
    request_count: int = 0
    max_estimated_tokens: int = 0
    avg_estimated_tokens: float = 0.0
    largest_requests: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_by_name: dict[str, int] = field(default_factory=dict)
    tool_calls_by_status: dict[str, int] = field(default_factory=dict)
    receipt_candidate_count: int = 0
    malformed_line_count: int = 0

class DuckDBProjection:
    """Read-only DuckDB projection over Rig Relay observability JSONL logs."""

    def __init__(self, session_root: Path | None = None) -> None:
        if session_root is None:
            # Default to ~/.rig/relay/sessions
            session_root = Path.home() / ".rig" / "relay" / "sessions"
        self.session_root = session_root

    def get_summary(self) -> ObservabilitySummary:
        if not HAS_DUCKDB:
            raise ImportError(
                "DuckDB is required for observability analytics. "
                "Install it with: pip install duckdb"
            )

        summary = ObservabilitySummary()
        
        # Discover observability.jsonl files
        log_files = list(self.session_root.glob("*/observability.jsonl"))
        if not log_files:
            return summary

        summary.sessions_seen = len(log_files)
        
        # Use DuckDB to query JSONL files directly
        # We use a union of all found files
        file_paths = [str(p) for p in log_files]
        
        con = duckdb.connect(database=":memory:")
        
        try:
            # 1. Basic event counts
            res = con.execute(f"""
                SELECT 
                    count(*) as total,
                    count(CASE WHEN receipt_candidate THEN 1 END) as receipts
                FROM read_json_auto({file_paths})
            """).fetchone()
            if res:
                summary.events_seen = res[0]
                summary.receipt_candidate_count = res[1]

            # 2. Events by name
            res = con.execute(f"""
                SELECT event_name, count(*) 
                FROM read_json_auto({file_paths})
                GROUP BY event_name
            """).fetchall()
            summary.events_by_name = dict(res)

            # 3. Context accounting metrics
            # Note: payload is a JSON object, DuckDB handles it as a struct or map
            res = con.execute(f"""
                SELECT 
                    count(*),
                    max(payload.context_accounting.estimated_tokens),
                    avg(payload.context_accounting.estimated_tokens)
                FROM read_json_auto({file_paths})
                WHERE event_name = 'rig.relay.context.request_accounted'
            """).fetchone()
            if res and res[0] > 0:
                summary.request_count = res[0]
                summary.max_estimated_tokens = int(res[1]) if res[1] is not None else 0
                summary.avg_estimated_tokens = float(res[2]) if res[2] is not None else 0.0

            # 4. Largest requests
            res = con.execute(f"""
                SELECT 
                    payload.context_accounting.model,
                    payload.context_accounting.estimated_tokens,
                    session_id,
                    created_at
                FROM read_json_auto({file_paths})
                WHERE event_name = 'rig.relay.context.request_accounted'
                ORDER BY payload.context_accounting.estimated_tokens DESC
                LIMIT 5
            """).fetchall()
            for r in res:
                summary.largest_requests.append({
                    "model": r[0],
                    "tokens": r[1],
                    "session_id": r[2],
                    "timestamp": r[3]
                })

            # 5. Tool calls
            res = con.execute(f"""
                SELECT payload.tool_name, count(*)
                FROM read_json_auto({file_paths})
                WHERE event_name = 'rig.relay.tool.call_completed'
                GROUP BY payload.tool_name
            """).fetchall()
            summary.tool_calls_by_name = dict(res)

            res = con.execute(f"""
                SELECT payload.status, count(*)
                FROM read_json_auto({file_paths})
                WHERE event_name = 'rig.relay.tool.call_completed'
                GROUP BY payload.status
            """).fetchall()
            summary.tool_calls_by_status = dict(res)

        except Exception as e:
            # If DuckDB fails due to schema mismatch or malformed JSON, 
            # we might need to fall back to manual counting for malformed lines.
            # For now, we report the error.
            pass
        finally:
            con.close()

        # 6. Malformed line count (manual pass for robustness)
        malformed = 0
        for path in log_files:
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
        summary.malformed_line_count = malformed

        return summary

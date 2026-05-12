from __future__ import annotations

from dataclasses import dataclass, field
import json
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
    errors: list[str] = field(default_factory=list)

    # Artifact metrics
    artifact_count: int = 0
    artifact_raw_bytes_total: int = 0
    artifact_prompt_visible_bytes_total: int = 0
    artifact_bytes_saved_estimate: int = 0
    artifacts_by_tool: dict[str, int] = field(default_factory=dict)


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
        if not self.session_root.exists():
            return summary

        log_files = list(self.session_root.glob("*/observability.jsonl"))
        if not log_files:
            return summary

        summary.sessions_seen = len(log_files)

        # 1. Malformed line count (manual pass for robustness)
        summary.malformed_line_count = self._count_malformed_lines(log_files, summary)

        # 2. DuckDB Projections
        file_paths = [str(p) for p in log_files]
        con = duckdb.connect(database=":memory:")

        try:
            # Using Relation API to avoid fragile SQL string interpolation
            rel = con.read_json(file_paths)

            # 2a. Basic event counts
            res = rel.aggregate(
                "count(*) as total, count(CASE WHEN receipt_candidate THEN 1 END) as receipts"
            ).fetchone()
            if res:
                summary.events_seen = res[0]
                summary.receipt_candidate_count = res[1]

            # 2b. Events by name
            res = rel.aggregate("event_name, count(*)").fetchall()
            summary.events_by_name = dict(res)

            # 2c. Context accounting metrics
            # Filter for specific events to avoid schema noise in non-accounting payloads
            acc_rel = rel.filter("event_name = 'rig.relay.context.request_accounted'")
            res = acc_rel.aggregate(
                "count(*), "
                "max(payload.context_accounting.estimated_tokens), "
                "avg(payload.context_accounting.estimated_tokens)"
            ).fetchone()

            if res and res[0] > 0:
                summary.request_count = res[0]
                summary.max_estimated_tokens = int(res[1]) if res[1] is not None else 0
                summary.avg_estimated_tokens = (
                    float(res[2]) if res[2] is not None else 0.0
                )

            # 2d. Largest requests
            # We use project() to pick specific nested fields
            res = (
                acc_rel
                .project(
                    "payload.context_accounting.model as model, "
                    "payload.context_accounting.estimated_tokens as tokens, "
                    "session_id, created_at"
                )
                .order("tokens DESC")
                .limit(5)
                .fetchall()
            )

            for r in res:
                summary.largest_requests.append({
                    "model": r[0],
                    "tokens": r[1],
                    "session_id": r[2],
                    "timestamp": r[3],
                })

            # 2e. Tool calls
            tool_rel = rel.filter("event_name = 'rig.relay.tool.call_completed'")
            res = tool_rel.aggregate("payload.tool_name, count(*)").fetchall()
            summary.tool_calls_by_name = dict(res)

            res = tool_rel.aggregate("payload.status, count(*)").fetchall()
            summary.tool_calls_by_status = dict(res)

            # 2f. Artifact metrics
            art_rel = rel.filter(
                "event_name = 'rig.relay.artifact.tool_output_written'"
            )
            res = art_rel.aggregate(
                "count(*), "
                "sum(payload.raw_byte_size), "
                "sum(payload.prompt_visible_byte_size)"
            ).fetchone()

            if res and res[0] > 0:
                summary.artifact_count = res[0]
                summary.artifact_raw_bytes_total = (
                    int(res[1]) if res[1] is not None else 0
                )
                summary.artifact_prompt_visible_bytes_total = (
                    int(res[2]) if res[2] is not None else 0
                )
                summary.artifact_bytes_saved_estimate = (
                    summary.artifact_raw_bytes_total
                    - summary.artifact_prompt_visible_bytes_total
                )

            res = art_rel.aggregate("payload.tool_name, count(*)").fetchall()
            summary.artifacts_by_tool = dict(res)

        except Exception as e:
            summary.errors.append(f"DuckDB projection failed: {e}")
        finally:
            con.close()

        return summary

    def _count_malformed_lines(
        self, log_files: list[Path], summary: ObservabilitySummary
    ) -> int:
        """Count malformed JSON lines manually for robustness."""
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
            except Exception as e:
                summary.errors.append(f"Failed to read {path.name}: {e}")
        return malformed


# Forced refresh

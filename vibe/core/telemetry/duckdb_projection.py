from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

try:
    import duckdb

    from vibe.core.telemetry.constants import EventName

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
    artifact_schema_versions: dict[str, int] = field(default_factory=dict)
    artifact_payload_hashes: list[str] = field(default_factory=list)

    # Context Assembly metrics
    context_assembly_count: int = 0
    max_context_estimated_tokens: int = 0
    avg_context_estimated_tokens: float = 0.0
    max_stable_prefix_bytes: int = 0
    max_dynamic_suffix_bytes: int = 0
    cache_candidate_bytes_total: int = 0
    optimization_hints_by_kind: dict[str, int] = field(default_factory=dict)

    # Context Layout metrics
    context_layout_count: int = 0
    stable_prefix_stable_count: int = 0
    stable_prefix_changed_count: int = 0
    avg_cacheability_ratio: float = 0.0
    max_cache_candidate_bytes: int = 0
    layout_hints_by_kind: dict[str, int] = field(default_factory=dict)


from vibe.core.paths._vibe_home import SESSIONS_ROOT


class DuckDBProjection:
    """Read-only DuckDB projection over Rig Relay observability JSONL logs."""

    def __init__(self, session_root: Path | None = None) -> None:
        if session_root is None:
            # Default to canonical sessions root (~/.rig/relay/sessions)
            session_root = SESSIONS_ROOT.path
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

        log_files = sorted(self.session_root.glob("*/observability.jsonl"))
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
            if "payload" in rel.columns:
                acc_rel = rel.filter(f"event_name = '{EventName.REQUEST_ACCOUNTED}'")
                try:
                    # Using -> and ->> is more resilient to missing keys than dot-notation
                    res = acc_rel.aggregate(
                        "count(*), "
                        "max(CAST(payload->'context_accounting'->>'estimated_tokens' AS BIGINT)), "
                        "avg(CAST(payload->'context_accounting'->>'estimated_tokens' AS BIGINT))"
                    ).fetchone()

                    if res and res[0] > 0:
                        summary.request_count = res[0]
                        summary.max_estimated_tokens = (
                            int(res[1]) if res[1] is not None else 0
                        )
                        summary.avg_estimated_tokens = (
                            float(res[2]) if res[2] is not None else 0.0
                        )

                        # 2d. Largest requests
                        l_res = (
                            acc_rel
                            .project(
                                "payload->'context_accounting'->>'model' as model, "
                                "CAST(payload->'context_accounting'->>'estimated_tokens' AS BIGINT) as tokens, "
                                "session_id, created_at"
                            )
                            .order("tokens DESC")
                            .limit(5)
                            .fetchall()
                        )

                        for r in l_res:
                            summary.largest_requests.append({
                                "model": r[0],
                                "tokens": r[1],
                                "session_id": r[2],
                                "timestamp": r[3],
                            })
                except Exception as e:
                    summary.errors.append(f"Context accounting projection failed: {e}")

            # 2e. Tool calls
            if "payload" in rel.columns:
                tool_rel = rel.filter(f"event_name = '{EventName.TOOL_CALL_COMPLETED}'")
                try:
                    res = tool_rel.aggregate(
                        "payload->>'tool_name', count(*)"
                    ).fetchall()
                    summary.tool_calls_by_name = {
                        str(k): v for k, v in res if k is not None
                    }

                    res = tool_rel.aggregate("payload->>'status', count(*)").fetchall()
                    summary.tool_calls_by_status = {
                        str(k): v for k, v in res if k is not None
                    }
                except Exception as e:
                    summary.errors.append(f"Tool call projection failed: {e}")

            # 2f. Artifact metrics
            if "payload" in rel.columns:
                art_rel = rel.filter(f"event_name = '{EventName.ARTIFACT_WRITTEN}'")
                try:
                    res = art_rel.aggregate(
                        "count(*), "
                        "sum(CAST(payload->>'raw_byte_size' AS BIGINT)), "
                        "sum(CAST(payload->>'prompt_visible_byte_size' AS BIGINT))"
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

                    res = art_rel.aggregate(
                        "payload->>'tool_name', count(*)"
                    ).fetchall()
                    summary.artifacts_by_tool = {
                        str(k): v for k, v in res if k is not None
                    }

                    schema_res = art_rel.aggregate(
                        "coalesce(payload->>'schema_version', 'legacy'), count(*)"
                    ).fetchall()
                    summary.artifact_schema_versions = {
                        str(k): v for k, v in schema_res if k is not None
                    }

                    hash_field = (
                        "coalesce(payload->>'payload_sha256', payload->>'sha256')"
                    )
                    hash_res = art_rel.project(hash_field).fetchall()
                    summary.artifact_payload_hashes = [
                        str(row[0]) for row in hash_res if row and row[0] is not None
                    ]
                except Exception as e:
                    summary.errors.append(f"Artifact projection failed: {e}")

            # 2g. Context Assembly metrics
            if "payload" in rel.columns:
                ca_rel = rel.filter(
                    f"event_name = '{EventName.CONTEXT_ASSEMBLY_REPORTED}'"
                )
                try:
                    res = ca_rel.aggregate(
                        "count(*), "
                        "max(CAST(payload->>'total_estimated_tokens' AS BIGINT)), "
                        "avg(CAST(payload->>'total_estimated_tokens' AS BIGINT)), "
                        "max(CAST(payload->>'stable_prefix_bytes' AS BIGINT)), "
                        "max(CAST(payload->>'dynamic_suffix_bytes' AS BIGINT)), "
                        "sum(CAST(payload->>'cache_candidate_bytes' AS BIGINT))"
                    ).fetchone()

                    if res and res[0] > 0:
                        summary.context_assembly_count = res[0]
                        summary.max_context_estimated_tokens = (
                            int(res[1]) if res[1] is not None else 0
                        )
                        summary.avg_context_estimated_tokens = (
                            float(res[2]) if res[2] is not None else 0.0
                        )
                        summary.max_stable_prefix_bytes = (
                            int(res[3]) if res[3] is not None else 0
                        )
                        summary.max_dynamic_suffix_bytes = (
                            int(res[4]) if res[4] is not None else 0
                        )
                        summary.cache_candidate_bytes_total = (
                            int(res[5]) if res[5] is not None else 0
                        )

                    # Count optimization hints by flattening the list
                    hints_res = ca_rel.project(
                        "payload->'optimization_hints'"
                    ).fetchall()
                    hint_counts: dict[str, int] = {}
                    for row in hints_res:
                        if row[0]:
                            for hint in row[0]:
                                hint_counts[hint] = hint_counts.get(hint, 0) + 1
                    summary.optimization_hints_by_kind = hint_counts
                except Exception as e:
                    summary.errors.append(f"Context assembly projection failed: {e}")

            # 2h. Context Layout metrics
            if "payload" in rel.columns:
                cl_rel = rel.filter(
                    f"event_name = '{EventName.CONTEXT_LAYOUT_PLANNED}'"
                )
                try:
                    res = cl_rel.aggregate(
                        "count(*), "
                        "sum(CASE WHEN payload->>'prefix_stability_status' = 'stable' THEN 1 ELSE 0 END), "
                        "sum(CASE WHEN payload->>'prefix_stability_status' = 'changed' THEN 1 ELSE 0 END), "
                        "avg(CAST(payload->>'cacheability_ratio' AS DOUBLE)), "
                        "max(CAST(payload->>'cache_candidate_bytes' AS BIGINT))"
                    ).fetchone()

                    if res and res[0] > 0:
                        summary.context_layout_count = res[0]
                        summary.stable_prefix_stable_count = (
                            int(res[1]) if res[1] is not None else 0
                        )
                        summary.stable_prefix_changed_count = (
                            int(res[2]) if res[2] is not None else 0
                        )
                        summary.avg_cacheability_ratio = (
                            float(res[3]) if res[3] is not None else 0.0
                        )
                        summary.max_cache_candidate_bytes = (
                            int(res[4]) if res[4] is not None else 0
                        )

                    # Count layout optimization hints
                    l_hints_res = cl_rel.project(
                        "payload->'optimization_hints'"
                    ).fetchall()
                    l_hint_counts: dict[str, int] = {}
                    for row in l_hints_res:
                        if row[0]:
                            for hint in row[0]:
                                l_hint_counts[hint] = l_hint_counts.get(hint, 0) + 1
                    summary.layout_hints_by_kind = l_hint_counts
                except Exception as e:
                    summary.errors.append(f"Context layout projection failed: {e}")

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

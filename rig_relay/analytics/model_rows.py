"""Model turn normalization for the analytical compiler.

Normalizes raw model turn observation records into fact_model_turns rows.
Content-light: hashes, counts, latency. No raw prompts or completions.
"""

from __future__ import annotations

from typing import Any


def normalize_model_turn(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_turn_id": record.get("turn_id", ""),
        "session_id": record.get("session_id", ""),
        "agent_id": record.get("agent_id", ""),
        "provider": record.get("provider", ""),
        "model": record.get("model", ""),
        "mode": record.get("mode", ""),
        "started_at": record.get("started_at", ""),
        "completed_at": record.get("completed_at", ""),
        "latency_ms": record.get("latency_ms", 0),
        "input_token_count": record.get("input_token_count", 0),
        "output_token_count": record.get("output_token_count", 0),
        "context_window": record.get("context_window", 0),
        "stable_prefix_sha256": record.get("stable_prefix_sha256", ""),
        "dynamic_suffix_sha256": record.get("dynamic_suffix_sha256", ""),
        "tool_call_count": record.get("tool_call_count", 0),
        "malformed_tool_call_count": record.get("malformed_tool_call_count", 0),
        "retry_count": record.get("retry_count", 0),
        "finish_reason": record.get("finish_reason", ""),
        "error_kind": record.get("error_kind", ""),
        "cost_estimate": record.get("cost_estimate"),
    }


_MODEL_TURN_SCHEMA = {
    "model_turn_id": "VARCHAR",
    "session_id": "VARCHAR",
    "agent_id": "VARCHAR",
    "provider": "VARCHAR",
    "model": "VARCHAR",
    "mode": "VARCHAR",
    "started_at": "VARCHAR",
    "completed_at": "VARCHAR",
    "latency_ms": "DOUBLE",
    "input_token_count": "BIGINT",
    "output_token_count": "BIGINT",
    "context_window": "BIGINT",
    "stable_prefix_sha256": "VARCHAR",
    "dynamic_suffix_sha256": "VARCHAR",
    "tool_call_count": "BIGINT",
    "malformed_tool_call_count": "BIGINT",
    "retry_count": "BIGINT",
    "finish_reason": "VARCHAR",
    "error_kind": "VARCHAR",
    "cost_estimate": "DOUBLE",
}

FACT_MODEL_TURNS_TABLE = "fact_model_turns"


def build_model_behavior_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "schema_version": "rig.model_projection.v1",
            "projection_kind": "model_behavior_summary",
            "total_turns": 0,
            "by_provider": {},
            "by_model": {},
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "malformed_tool_call_rate": 0.0,
            "retry_rate": 0.0,
            "context_limit_events": 0,
        }

    total_turns = len(records)
    total_input = sum(r.get("input_token_count", 0) for r in records)
    total_output = sum(r.get("output_token_count", 0) for r in records)
    total_latency = sum(r.get("latency_ms", 0) for r in records)
    malformed = sum(1 for r in records if r.get("malformed_tool_call_count", 0) > 0)
    retries = sum(1 for r in records if r.get("retry_count", 0) > 0)
    limit_events = sum(1 for r in records if r.get("error_kind") == "context_limit")

    by_provider: dict[str, Any] = {}
    by_model: dict[str, Any] = {}
    for r in records:
        p = r.get("provider", "unknown")
        m = r.get("model", "unknown")
        if p not in by_provider:
            by_provider[p] = {"turns": 0, "tokens": 0}
        by_provider[p]["turns"] += 1
        by_provider[p]["tokens"] += r.get("input_token_count", 0) + r.get(
            "output_token_count", 0
        )
        if m not in by_model:
            by_model[m] = {"turns": 0, "tokens": 0, "avg_latency": 0.0}
        by_model[m]["turns"] += 1
        by_model[m]["tokens"] += r.get("input_token_count", 0) + r.get(
            "output_token_count", 0
        )

    for m in by_model:
        by_model[m]["avg_latency"] = sum(
            r.get("latency_ms", 0) for r in records if r.get("model") == m
        ) / max(1, by_model[m]["turns"])

    return {
        "schema_version": "rig.model_projection.v1",
        "projection_kind": "model_behavior_summary",
        "total_turns": total_turns,
        "by_provider": by_provider,
        "by_model": by_model,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "avg_latency_ms": total_latency / max(1, total_turns),
        "malformed_tool_call_rate": malformed / max(1, total_turns),
        "retry_rate": retries / max(1, total_turns),
        "context_limit_events": limit_events,
    }


__all__ = [
    "FACT_MODEL_TURNS_TABLE",
    "build_model_behavior_summary",
    "normalize_model_turn",
]

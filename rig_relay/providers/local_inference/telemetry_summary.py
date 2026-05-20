"""Content-light telemetry summary. Forbids raw prompt/completion by default."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import TelemetrySummary


def build_telemetry_summary(
    *,
    capacity_class: str = "",
    runtimes: list[str] | None = None,
    benchmarks_completed: int = 0,
    comparisons_generated: int = 0,
    local_vs_cloud: int = 0,
    now: str | None = None,
) -> TelemetrySummary:
    return TelemetrySummary(
        summary_id=f"ts_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        capacity_class=capacity_class,
        runtimes_detected=runtimes or [],
        benchmark_runs_completed=benchmarks_completed,
        comparison_reports_generated=comparisons_generated,
        local_vs_cloud_comparisons=local_vs_cloud,
        raw_prompt_telemetry=0,
        raw_completion_telemetry=0,
        telemetry_export_allowed=False,
    )


def validate_telemetry_content_light(data: dict) -> list[str]:
    violations: list[str] = []
    forbidden = {
        "raw_prompt",
        "raw_completion",
        "prompt_text",
        "completion_text",
        "api_key",
        "secret",
        "password",
    }
    for key in data:
        if key in forbidden:
            violations.append(f"forbidden_field:{key}")
    return violations


__all__ = ["build_telemetry_summary", "validate_telemetry_content_light"]

"""Dataset export policy — content-light, default aggregate_only."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import DatasetExportPolicy


def build_export_policy(
    *, mode: str = "aggregate_only", now: str | None = None
) -> DatasetExportPolicy:
    return DatasetExportPolicy(
        policy_id=f"dep_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        mode=mode,
        exportable_fields=[
            "machine_class",
            "runtime_backend_id",
            "runtime_kind",
            "model_size_class",
            "task_profile",
            "contract_passed",
            "local_latency_ms",
            "local_tokens_per_sec",
            "recommended_route",
            "confidence",
            "redaction_summary",
        ],
        non_exportable_fields=[
            "raw_prompt",
            "raw_completion",
            "raw_tool_output",
            "private_repo_content",
            "credentials",
            "secrets",
            "absolute_local_paths",
            "usernames",
            "serial_numbers",
        ],
        raw_prompt_exported=False,
        raw_completion_exported=False,
        raw_tool_output_exported=False,
    )


__all__ = ["build_export_policy"]

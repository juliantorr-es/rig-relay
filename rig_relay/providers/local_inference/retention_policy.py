"""Raw prompt/completion retention gate — blocked by default.

Content-light retention policy. Raw logs local-only, separate gate.
Never exports to telemetry without explicit export gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import RawRetentionPolicy, RetentionMode


def _new_policy_id() -> str:
    return f"rrp_{secrets.token_hex(8)}"


def build_retention_policy(
    *, mode: str = "disabled", now: str | None = None
) -> RawRetentionPolicy:
    policy = RawRetentionPolicy(
        policy_id=_new_policy_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        mode=mode,
    )

    if mode == RetentionMode.DISABLED.value:
        policy.user_visible_disclosure = "Raw local inference transcripts are disabled."
        policy.ttl_seconds = 0
        policy.max_bytes_per_session = 0
        policy.export_to_telemetry_allowed = False
    elif mode == RetentionMode.METADATA_ONLY.value:
        policy.user_visible_disclosure = (
            "Only metadata is retained. No raw prompts or completions."
        )
    elif mode == RetentionMode.RAW_LOCAL_TTL.value:
        policy.user_visible_disclosure = (
            "Raw transcripts retained locally with TTL. Not exported to telemetry."
        )
        policy.ttl_seconds = 3600
        policy.max_bytes_per_session = 10485760
    elif mode == RetentionMode.RAW_LOCAL_DEBUG_PACKET.value:
        policy.user_visible_disclosure = (
            "Raw transcripts retained in local debug packet. Not exported."
        )
        policy.ttl_seconds = 7200
        policy.max_bytes_per_session = 52428800

    return policy


__all__ = ["build_retention_policy"]

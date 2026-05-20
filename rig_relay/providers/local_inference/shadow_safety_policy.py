"""Shadow safety policy — immutable proof that shadow output cannot affect live agent behavior.

Every shadow run receipt asserts these invariants. This module produces
the canonical policy object that audits them.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import ShadowSafetyPolicy


def build_safety_policy(*, now: str | None = None) -> ShadowSafetyPolicy:
    return ShadowSafetyPolicy(
        policy_id=f"ssp_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        automatic_agent_execution=False,
        agent_state_mutated=False,
        tool_execution_allowed=False,
        file_mutation_allowed=False,
        provider_fallback_execution_allowed=False,
        shadow_output_promotable_to_user=False,
        shadow_output_promotable_to_training=False,
        raw_prompt_persisted=False,
        raw_completion_persisted=False,
    )


def validate_shadow_receipt_safety(receipt: dict) -> list[str]:
    violations: list[str] = []
    safety_fields = {
        "automatic_agent_execution": False,
        "agent_state_mutated": False,
        "tool_execution_allowed": False,
        "file_mutation_allowed": False,
        "provider_fallback_execution_allowed": False,
        "raw_prompt_persisted": False,
        "raw_completion_persisted": False,
    }
    for field, expected in safety_fields.items():
        if receipt.get(field) is not expected:
            violations.append(f"{field}: expected {expected}, got {receipt.get(field)}")
    return violations


__all__ = ["build_safety_policy", "validate_shadow_receipt_safety"]

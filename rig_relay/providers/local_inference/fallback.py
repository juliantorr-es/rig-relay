"""Provider fallback policy for local inference selection.

Models fallback behavior without executing any provider call.
Explains why local inference was selected, not selected, or blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets
from typing import Any

from rig_relay.providers.local_inference.models import (
    ExplanationCode,
    PolicyResultKind,
    ProviderFallbackDecision,
)


def _new_fallback_id() -> str:
    return f"fb_{secrets.token_hex(8)}"


def decide_fallback(
    *, selection_policy_result: dict[str, Any], now: str | None = None
) -> ProviderFallbackDecision:
    result_kind = selection_policy_result.get("result_kind", "")
    blocked = (
        result_kind.startswith("blocked")
        or result_kind == PolicyResultKind.NOT_CONFIGURED.value
        or result_kind == PolicyResultKind.CONFIGURED_BUT_UNPROBED.value
    )
    selected = result_kind in {
        PolicyResultKind.ELIGIBLE_FOR_MANUAL_SELECTION.value,
        PolicyResultKind.ELIGIBLE_FOR_POLICY_SELECTION.value,
    }

    block_reasons: list[str] = []
    explanation_codes = selection_policy_result.get("explanation_codes", [])

    requires_fallback_for_missing_capability = (
        ExplanationCode.STRUCTURED_JSON_MISSING.value in explanation_codes
        or ExplanationCode.TOOL_CALLING_MISSING.value in explanation_codes
        or ExplanationCode.EMBEDDINGS_MISSING.value in explanation_codes
        or ExplanationCode.VISION_MISSING.value in explanation_codes
    )
    requires_fallback_for_missing_benchmark = (
        ExplanationCode.BENCHMARK_MISSING.value in explanation_codes
    )
    requires_fallback_for_failed_probe = (
        ExplanationCode.PROBE_FAILED.value in explanation_codes
    )
    requires_fallback_for_degraded_diagnostics = (
        ExplanationCode.DIAGNOSTICS_DISABLED.value in explanation_codes
    )
    requires_fallback_for_missing_approval = (
        ExplanationCode.APPROVAL_MISSING.value in explanation_codes
    )

    if result_kind == PolicyResultKind.NOT_CONFIGURED.value:
        block_reasons.append("No local inference endpoint configured")
        fallback_class = "remote_provider"
        fallback_rationale = (
            "Local inference is not configured. "
            "Falling back to remote providers (OpenAI, Anthropic, etc.)."
        )
    elif result_kind == PolicyResultKind.BLOCKED_BY_FAILED_PROBE.value:
        block_reasons.append("Local inference probe failed")
        fallback_class = "remote_provider"
        fallback_rationale = (
            "Local inference endpoint is unreachable. Falling back to remote providers."
        )
    elif result_kind == PolicyResultKind.BLOCKED_BY_STALE_EVIDENCE.value:
        block_reasons.append("Probe evidence is stale")
        fallback_class = "remote_provider"
        fallback_rationale = (
            "Local inference probe evidence is too old. "
            "Falling back to remote providers."
        )
    elif result_kind == PolicyResultKind.BLOCKED_BY_DEGRADED_DIAGNOSTICS.value:
        block_reasons.append("Diagnostics disabled prevents policy selection")
        fallback_class = "remote_provider"
        fallback_rationale = (
            "Local inference diagnostics are disabled. "
            "Falling back to remote providers."
        )
    elif result_kind == PolicyResultKind.BLOCKED_BY_MISSING_CAPABILITY.value:
        missing_caps = [
            c
            for c in explanation_codes
            if c
            in {
                ExplanationCode.STRUCTURED_JSON_MISSING.value,
                ExplanationCode.TOOL_CALLING_MISSING.value,
                ExplanationCode.EMBEDDINGS_MISSING.value,
                ExplanationCode.VISION_MISSING.value,
            }
        ]
        block_reasons.append(f"Missing required capabilities: {missing_caps}")
        fallback_class = "remote_provider"
        fallback_rationale = (
            f"Local inference missing capabilities: {missing_caps}. "
            "Falling back to remote providers."
        )
    elif selected:
        fallback_class = "local_inference_eligible"
        fallback_rationale = "Local inference is eligible. No fallback required."
    else:
        block_reasons.append("Not eligible for local inference")
        fallback_class = "remote_provider"
        fallback_rationale = "Falling back to remote providers."

    return ProviderFallbackDecision(
        decision_id=_new_fallback_id(),
        decided_at=now or datetime.now(UTC).isoformat(),
        local_inference_selected=selected,
        local_inference_blocked=blocked,
        block_reasons=block_reasons,
        fallback_provider_class=fallback_class,
        fallback_rationale=fallback_rationale,
        requires_fallback_for_missing_capability=requires_fallback_for_missing_capability,
        requires_fallback_for_missing_benchmark=requires_fallback_for_missing_benchmark,
        requires_fallback_for_failed_probe=requires_fallback_for_failed_probe,
        requires_fallback_for_degraded_diagnostics=requires_fallback_for_degraded_diagnostics,
        requires_fallback_for_missing_approval=requires_fallback_for_missing_approval,
        evidence_receipts=[],
    )


__all__ = ["decide_fallback"]

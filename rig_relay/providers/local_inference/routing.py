"""Local inference routing decision engine — skeleton only.

Produces RoutingDecision records based on probed runtimes, task profiles,
and benchmark evidence. Dry-run mode returns a default fallback decision
without requiring real probes.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    AlternativeRuntime,
    CapabilityProbeResult,
    PrivacyLocality,
    RoutingConfidence,
    RoutingDecision,
    TaskProfile,
)


def _new_decision_id() -> str:
    return f"route_{secrets.token_hex(8)}"


def select_runtime(
    *,
    probed_runtimes: list[CapabilityProbeResult],
    task_profile: TaskProfile,
    dry_run: bool = False,
) -> RoutingDecision:
    decision_id = _new_decision_id()
    decided_at = datetime.now(UTC).isoformat()

    if dry_run or not probed_runtimes:
        return RoutingDecision(
            decision_id=decision_id,
            decided_at=decided_at,
            task_profile=task_profile,
            selected_runtime_url="local:fallback",
            selected_runtime_engine="unknown",
            decision_rationale=(
                "dry-run mode" if dry_run else "no probed runtimes available"
            ),
            confidence=RoutingConfidence.FALLBACK,
            matched_dimensions=[],
            unmatched_dimensions=["all"],
        )

    reachable = [p for p in probed_runtimes if p.reachable]
    if not reachable:
        return RoutingDecision(
            decision_id=decision_id,
            decided_at=decided_at,
            task_profile=task_profile,
            selected_runtime_url="local:none_reachable",
            selected_runtime_engine="unknown",
            decision_rationale="No reachable local inference runtimes",
            confidence=RoutingConfidence.FALLBACK,
            matched_dimensions=[],
            unmatched_dimensions=["reachability"],
        )

    scored: list[tuple[CapabilityProbeResult, int, list[str], list[str]]] = []
    for probe in reachable:
        score, matched, unmatched = _score_runtime(probe, task_profile)
        scored.append((probe, score, matched, unmatched))

    scored.sort(key=lambda x: x[1], reverse=True)
    best = scored[0]

    alternatives: list[AlternativeRuntime] = []
    for i in range(1, len(scored)):
        probe, score, matched, unmatched = scored[i]
        alternatives.append(
            AlternativeRuntime(
                runtime_url=probe.runtime_url,
                runtime_engine=probe.runtime_engine.value,
                excluded_reason=f"Lower score ({score}) vs selected ({best[1]})",
                matched_dimensions=matched,
                failed_dimensions=unmatched,
            )
        )

    return RoutingDecision(
        decision_id=decision_id,
        decided_at=decided_at,
        task_profile=task_profile,
        selected_runtime_url=best[0].runtime_url,
        selected_runtime_engine=best[0].runtime_engine.value,
        decision_rationale=f"Selected {best[0].runtime_url} ({best[0].runtime_engine.value}) with score {best[1]}",
        confidence=(
            RoutingConfidence.HIGH
            if best[1] >= 8
            else RoutingConfidence.MEDIUM
            if best[1] >= 5
            else RoutingConfidence.LOW
        ),
        matched_dimensions=best[2],
        unmatched_dimensions=best[3],
        alternatives_considered=alternatives,
    )


def _score_runtime(
    probe: CapabilityProbeResult, task_profile: TaskProfile
) -> tuple[int, list[str], list[str]]:
    score = 0
    matched: list[str] = []
    unmatched: list[str] = []

    caps = probe.capabilities
    if caps.chat_completions == "supported":
        score += 2
        matched.append("chat_completions")
    else:
        unmatched.append("chat_completions")

    if task_profile.tool_call_required:
        if caps.tool_calling == "supported":
            score += 2
            matched.append("tool_calling")
        else:
            unmatched.append("tool_calling")

    if task_profile.structured_output_required:
        if caps.structured_json_output == "supported":
            score += 2
            matched.append("structured_json_output")
        else:
            unmatched.append("structured_json_output")

    if caps.streaming == "supported":
        score += 1
        matched.append("streaming")
    else:
        unmatched.append("streaming")

    if task_profile.privacy_locality in {
        PrivacyLocality.MUST_BE_LOCAL,
        PrivacyLocality.PREFER_LOCAL,
    }:
        score += 1
        matched.append("local")

    if probe.health_summary.status == "ok":
        score += 1
        matched.append("health_ok")

    if not probe.errors:
        score += 1
        matched.append("no_probe_errors")

    return score, matched, unmatched


__all__ = ["select_runtime"]

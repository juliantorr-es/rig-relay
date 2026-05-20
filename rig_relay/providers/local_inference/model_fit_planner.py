"""Model fit planner — maps capacity to model candidates. Downloads nothing."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    CapacityScan,
    ModelCandidate,
    ModelFitPlan,
    RecommendationStatus,
)


def plan_models(*, capacity: CapacityScan, now: str | None = None) -> ModelFitPlan:
    plan = ModelFitPlan(
        plan_id=f"mfp_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        capacity_class=capacity.capacity_class,
    )

    candidates = _generate_candidates(capacity)
    plan.candidates = candidates
    plan.recommendations_count = sum(
        1 for c in candidates if c.recommendation_status == "recommended"
    )
    return plan


def _generate_candidates(caps: CapacityScan) -> list[ModelCandidate]:
    cls = caps.capacity_class
    results: list[ModelCandidate] = []

    small = ModelCandidate(
        candidate_id=f"m_small_instruct_{secrets.token_hex(4)}",
        backend_id="ollama"
        if "ollama" in caps.runtimes_detected
        else "llama_cpp_server",
        model_family="small_instruct",
        model_size_class="1B-3B",
        expected_task_profiles=["chat_light"],
        expected_runtime="ollama"
        if "ollama" in caps.runtimes_detected
        else "llama_cpp_server",
    )
    if cls in ("tiny_cpu", "small_cpu"):
        small.recommendation_status = RecommendationStatus.RECOMMENDED.value
        small.reasons.append("fits_cpu_capacity")
    elif cls.startswith("apple_silicon") or cls.startswith("cuda"):
        small.recommendation_status = RecommendationStatus.RECOMMENDED.value
        small.reasons.append("fits_accelerated_capacity")
    else:
        small.recommendation_status = RecommendationStatus.UNKNOWN_CAPACITY.value
    results.append(small)

    medium = ModelCandidate(
        candidate_id=f"m_medium_instruct_{secrets.token_hex(4)}",
        backend_id="ollama"
        if "ollama" in caps.runtimes_detected
        else "llama_cpp_server",
        model_family="medium_instruct",
        model_size_class="7B-9B",
        expected_task_profiles=["chat_light", "code_review_light", "structured_json"],
        expected_runtime="ollama"
        if "ollama" in caps.runtimes_detected
        else "llama_cpp_server",
    )
    if cls in (
        "apple_silicon_medium",
        "apple_silicon_heavy",
        "cuda_medium",
        "cuda_heavy",
    ):
        medium.recommendation_status = RecommendationStatus.RECOMMENDED.value
        medium.reasons.append("fits_accelerated_capacity")
    elif cls in ("apple_silicon_light", "cuda_light"):
        medium.recommendation_status = RecommendationStatus.POSSIBLE_BUT_RISKY.value
        medium.reasons.append("low_memory_may_swap")
    else:
        medium.recommendation_status = RecommendationStatus.NOT_RECOMMENDED.value
        medium.reasons.append("insufficient_cpu_capacity")
    results.append(medium)

    coding = ModelCandidate(
        candidate_id=f"m_coding_instruct_{secrets.token_hex(4)}",
        backend_id="llama_cpp_server",
        model_family="coding_instruct",
        model_size_class="7B-14B",
        expected_task_profiles=[
            "chat_light",
            "code_review_light",
            "structured_json",
            "tool_planning",
        ],
        expected_runtime="llama_cpp_server",
    )
    if cls in ("apple_silicon_heavy", "cuda_heavy"):
        coding.recommendation_status = RecommendationStatus.RECOMMENDED.value
        coding.reasons.append("fits_heavy_capacity")
    elif cls in ("apple_silicon_medium", "cuda_medium"):
        coding.recommendation_status = RecommendationStatus.POSSIBLE_BUT_RISKY.value
    else:
        coding.recommendation_status = RecommendationStatus.NOT_RECOMMENDED.value
    results.append(coding)

    if cls.startswith("cuda"):
        vllm = ModelCandidate(
            candidate_id=f"m_vllm_instruct_{secrets.token_hex(4)}",
            backend_id="vllm",
            model_family="medium_instruct",
            model_size_class="7B-9B",
            expected_task_profiles=[
                "chat_light",
                "code_review_light",
                "structured_json",
                "tool_planning",
            ],
            expected_runtime="vllm",
        )
        vllm.recommendation_status = RecommendationStatus.RECOMMENDED.value
        vllm.reasons.append("cuda_vllm_eligible")
        results.append(vllm)

    return results


__all__ = ["plan_models"]

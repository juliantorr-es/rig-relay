"""Reference comparison for shadow evaluation — content-light metadata comparison.

Compares shadow run results against reference evidence without requiring
raw reference completions. Uses hashes, contract results, latency/token classes.
"""

from __future__ import annotations

import secrets

from rig_relay.providers.local_inference.models import (
    ComparisonStatus,
    ReferenceComparison,
    ShadowRunReceipt,
)


def _new_comparison_id() -> str:
    return f"rcmp_{secrets.token_hex(8)}"


def compare_to_reference(
    *,
    shadow_receipt: ShadowRunReceipt,
    reference_contract_result: str = "",
    reference_hash: str = "",
    reference_latency_class: str = "",
    reference_token_class: str = "",
) -> ReferenceComparison:
    comparison = ReferenceComparison(
        comparison_id=_new_comparison_id(),
        scenario_id=shadow_receipt.scenario_id,
        reference_hash=reference_hash,
        reference_contract_result=reference_contract_result,
    )

    if (
        not reference_hash
        and not reference_contract_result
        and not reference_latency_class
        and not reference_token_class
    ):
        comparison.comparison_status = ComparisonStatus.NO_REFERENCE.value
        return comparison

    checks_passed = 0
    checks_total = 0

    if reference_hash:
        checks_total += 1
        if shadow_receipt.completion_sha256 == reference_hash:
            comparison.completion_hash_match = True
            checks_passed += 1

    if reference_contract_result:
        checks_total += 1
        if shadow_receipt.contract_result == reference_contract_result:
            comparison.contract_result_match = True
            checks_passed += 1

    if reference_latency_class:
        checks_total += 1
        shadow_class = _latency_class(shadow_receipt.latency_ms)
        if shadow_class == reference_latency_class:
            comparison.latency_class_match = True
            checks_passed += 1

    if reference_token_class:
        checks_total += 1
        shadow_token_class = _token_class(shadow_receipt.output_token_count)
        if shadow_token_class == reference_token_class:
            comparison.token_count_class_match = True
            checks_passed += 1

    if checks_total == 0:
        comparison.comparison_status = ComparisonStatus.NO_REFERENCE.value
    elif checks_passed == checks_total:
        comparison.comparison_status = ComparisonStatus.COMPARISON_PASSED.value
    elif checks_passed == 0:
        comparison.comparison_status = ComparisonStatus.COMPARISON_FAILED.value
    else:
        comparison.comparison_status = ComparisonStatus.COMPARISON_FAILED.value

    comparison.comparison_details = f"passed={checks_passed}/{checks_total}"
    return comparison


def _latency_class(ms: int) -> str:
    if ms <= 500:
        return "fast"
    if ms <= 2000:
        return "moderate"
    if ms <= 5000:
        return "slow"
    return "very_slow"


def _token_class(count: int) -> str:
    if count <= 50:
        return "small"
    if count <= 200:
        return "medium"
    if count <= 500:
        return "large"
    return "xlarge"


__all__ = ["compare_to_reference"]

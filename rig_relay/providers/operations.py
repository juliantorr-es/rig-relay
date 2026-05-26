"""Deterministic provider operations projection from canonical evidence ledger.

Lane C-owned internal provider service. Content-light and reconstructable
from the append-only provider evidence ledger. Produces a typed operations
snapshot suitable for human or machine inspection.

Never stores raw prompts, completions, provider payloads, secrets,
API keys, repository contents, or unbounded raw error strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.providers.evidence_ledger import (
    LEDGER_FILE,
    VerifiedLedgerResult,
    load_verified_provider_events,
)

_CORRUPTED_LEDGER_ERROR = (
    "Ledger contains corrupt events — integrity cannot be verified"
)


@dataclass
class ProviderOperationsReport:
    """Deterministic content-light projection of provider operations evidence."""

    schema_version: str = "rig.relay.provider_operations_report.v1"

    # Integrity
    ledger_file: str = ""
    event_count: int = 0
    integrity_event_digests: list[str] = field(default_factory=list)
    integrity_verified: bool = False
    integrity_errors: list[str] = field(default_factory=list)

    # Provider identity summary
    provider_identities: list[str] = field(default_factory=list)
    provider_invocation_count: dict[str, int] = field(default_factory=dict)

    # Invocation categories
    outcome_class_counts: dict[str, int] = field(default_factory=dict)
    streaming_count: int = 0
    non_streaming_count: int = 0

    # Token detail evidence availability
    cached_tokens_events: int = 0
    cached_tokens_verified: int = 0
    reasoning_tokens_events: int = 0
    reasoning_tokens_verified: int = 0

    # Gateway evidence
    gateway_cost_events: int = 0
    gateway_provenance_events: int = 0

    # Discrepancy outcomes
    discrepancy_detected_count: int = 0
    discrepancy_free_count: int = 0

    # Content-light enforcement
    content_light_violations: int = 0

    # Degraded or refusal evidence
    refusal_events: int = 0
    error_events: int = 0
    degraded_evidence_events: int = 0

    # Structural
    generated_at: str = ""
    report_digest: str = ""


def _verify_integrity_from_reader(
    verified: VerifiedLedgerResult, report: ProviderOperationsReport
) -> None:
    """Verify integrity from the canonical verified reader.

    Uses recomputed digests and schema validation from the verified reader,
    not merely digest-string shape. Corrupt events cause integrity failure.
    """
    report.integrity_event_digests = [
        e.get("event_digest", "") for e in verified.valid_events
    ]
    report.integrity_verified = verified.corpus_integrity_verified
    if not verified.corpus_integrity_verified:
        report.integrity_errors.extend(verified.corruption_summary)
    if verified.corrupt_events:
        report.integrity_errors.append(
            f"Corrupt events excluded from report: {len(verified.corrupt_events)}"
        )


def _count_event_fields(
    event: dict[str, Any], report: ProviderOperationsReport
) -> None:
    outcome = event.get("outcome") or {}

    provider_id = outcome.get("requested_provider_id", "unknown")
    if provider_id not in report.provider_identities:
        report.provider_identities.append(provider_id)
    report.provider_invocation_count[provider_id] = (
        report.provider_invocation_count.get(provider_id, 0) + 1
    )

    oc = outcome.get("outcome_class", "unknown")
    report.outcome_class_counts[oc] = report.outcome_class_counts.get(oc, 0) + 1

    if outcome.get("streaming"):
        report.streaming_count += 1
    else:
        report.non_streaming_count += 1

    _count_token_details(outcome, report)
    _count_gateway(outcome, report)
    _count_discrepancy(outcome, report)

    if not event.get("content_light"):
        report.content_light_violations += 1

    _count_degraded(outcome, oc, report)


def _count_token_details(
    outcome: dict[str, Any], report: ProviderOperationsReport
) -> None:
    if outcome.get("cache_read_tokens") is not None:
        report.cached_tokens_events += 1
    if outcome.get("cache_read_verified"):
        report.cached_tokens_verified += 1
    if outcome.get("reasoning_tokens") is not None:
        report.reasoning_tokens_events += 1
    if outcome.get("reasoning_tokens_verified"):
        report.reasoning_tokens_verified += 1


def _count_gateway(outcome: dict[str, Any], report: ProviderOperationsReport) -> None:
    if outcome.get("gateway_total_cost") is not None:
        report.gateway_cost_events += 1
    if outcome.get("gateway_provenance") is not None:
        report.gateway_provenance_events += 1


def _count_discrepancy(
    outcome: dict[str, Any], report: ProviderOperationsReport
) -> None:
    if outcome.get("usage_discrepancy_detected"):
        report.discrepancy_detected_count += 1
    elif outcome.get("usage_discrepancy_detected") is False:
        report.discrepancy_free_count += 1


_REFUSAL_CLASSES: frozenset[str] = frozenset({"refusal", "safety_block"})
_SUCCESS_OR_UNKNOWN: frozenset[str] = frozenset({"success", "unknown"})


def _count_degraded(
    outcome: dict[str, Any], oc: str, report: ProviderOperationsReport
) -> None:
    if oc in _REFUSAL_CLASSES:
        report.refusal_events += 1
    if oc == "error":
        report.error_events += 1
    usage_verified = outcome.get("usage_verified")
    if usage_verified is False or (
        usage_verified is None and oc not in _SUCCESS_OR_UNKNOWN
    ):
        report.degraded_evidence_events += 1


def generate_operations_report(
    verified: VerifiedLedgerResult | None = None,
    *,
    events: list[dict[str, Any]] | None = None,
) -> ProviderOperationsReport:
    """Generate a deterministic provider operations projection from verified evidence.

    Accepts either a VerifiedLedgerResult or raw event dictionaries (deprecated).
    When events are provided directly, integrity is verified against the same
    recomputed-digest and schema-validation rules used by the verified reader.

    If neither is provided, loads from the canonical ledger through
    load_verified_provider_events() which schema-validates and
    digest-recomputes every event. Only valid admitted events contribute
    to provider identity counts, token detail summaries, discrepancy
    counts, and other aggregate fields. Corrupt events are surfaced
    but excluded.

    The returned report is content-light and reconstructable.
    """
    if verified is None and events is not None:
        from rig_relay.providers.query import ProviderEvidenceQueryService

        svc = ProviderEvidenceQueryService.from_test_events(
            events, canonical_source=True
        )
        verified = svc._verified

    if verified is None:
        verified = load_verified_provider_events()

    report = ProviderOperationsReport(
        ledger_file=LEDGER_FILE, event_count=len(verified.valid_events)
    )

    _verify_integrity_from_reader(verified, report)
    for event in verified.valid_events:
        _count_event_fields(event, report)

    if verified.corrupt_events:
        report.integrity_errors.append(
            f"Corrupt events detected: {len(verified.corrupt_events)}"
        )

    report.provider_identities.sort()
    return _finalize_report(report)


def _finalize_report(report: ProviderOperationsReport) -> ProviderOperationsReport:
    report_data = _report_to_ordered_dict(report)
    canonical = hashlib.sha256(
        json.dumps(report_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report.report_digest = f"sha256:{canonical}"
    report.generated_at = datetime.now(UTC).isoformat()
    return report


def _report_to_ordered_dict(report: ProviderOperationsReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "ledger_file": report.ledger_file,
        "event_count": report.event_count,
        "integrity_event_digests": report.integrity_event_digests,
        "integrity_verified": report.integrity_verified,
        "integrity_errors": report.integrity_errors,
        "provider_identities": report.provider_identities,
        "provider_invocation_count": dict(
            sorted(report.provider_invocation_count.items())
        ),
        "outcome_class_counts": dict(sorted(report.outcome_class_counts.items())),
        "streaming_count": report.streaming_count,
        "non_streaming_count": report.non_streaming_count,
        "cached_tokens_events": report.cached_tokens_events,
        "cached_tokens_verified": report.cached_tokens_verified,
        "reasoning_tokens_events": report.reasoning_tokens_events,
        "reasoning_tokens_verified": report.reasoning_tokens_verified,
        "gateway_cost_events": report.gateway_cost_events,
        "gateway_provenance_events": report.gateway_provenance_events,
        "discrepancy_detected_count": report.discrepancy_detected_count,
        "discrepancy_free_count": report.discrepancy_free_count,
        "content_light_violations": report.content_light_violations,
        "refusal_events": report.refusal_events,
        "error_events": report.error_events,
        "degraded_evidence_events": report.degraded_evidence_events,
        "generated_at": report.generated_at,
        "report_digest": report.report_digest,
    }


__all__ = ["ProviderOperationsReport", "generate_operations_report"]

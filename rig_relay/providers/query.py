"""Typed content-light read-side query service over canonical provider evidence.

Lane C-owned internal application-facing boundary. Consumes only canonical
provider evidence events from the append-only ledger. Returns typed,
deterministic, content-light projections. Never stores raw prompts,
completions, provider payloads, secrets, API keys, or repository contents.

Intended for future desktop/Gridline diagnostics surfaces and governed
agent consumption. Never mutates the canonical ledger.
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
    VerifiedProviderEvent,
    load_verified_provider_events,
)

_PROJECTION_SCHEMA_VERSION = "rig.relay.provider_evidence_query_projection.v1"

_REFUSAL_CLASSES: frozenset[str] = frozenset({"refusal", "safety_block"})


@dataclass
class ProviderEvidenceQuery:
    """Typed content-light projection of a single canonical provider evidence event.

    Designed for query responses and diagnostics panels. Every field is
    derived from schema-validated canonical evidence only.
    """

    event_id: str = ""
    created_at: str = ""
    session_id: str = ""
    correlation_id: str = ""
    provider_id: str = ""
    model_id: str = ""
    api_style: str = ""
    outcome_class: str = ""
    streaming: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_read_verified: bool | None = None
    reasoning_tokens: int | None = None
    reasoning_tokens_verified: bool | None = None
    usage_discrepancy_detected: bool | None = None
    usage_verified: bool | None = None
    is_refusal: bool = False
    is_error: bool = False
    event_digest: str = ""
    content_light: bool = True


@dataclass
class ProviderEvidenceQueryResult:
    """Result of a provider evidence query with projection metadata.

    Content-light: no raw events, only typed projections and structural metadata.
    """

    schema_version: str = _PROJECTION_SCHEMA_VERSION
    events: list[ProviderEvidenceQuery] = field(default_factory=list)
    total_canonical_events: int = 0
    matched_count: int = 0
    integrity_verified: bool = False
    integrity_errors: list[str] = field(default_factory=list)
    projection_digest: str = ""
    generated_at: str = ""
    query_description: str = ""


@dataclass
class ProviderEvidenceSummary:
    """Content-light aggregate summary suitable for provider diagnostics panels.

    Reconstructable from canonical evidence. Deterministic over same input.
    """

    schema_version: str = _PROJECTION_SCHEMA_VERSION
    total_events: int = 0
    provider_ids: list[str] = field(default_factory=list)
    api_styles: list[str] = field(default_factory=list)
    streaming_count: int = 0
    non_streaming_count: int = 0
    cached_token_verified_count: int = 0
    reasoning_token_verified_count: int = 0
    discrepancy_count: int = 0
    refusal_count: int = 0
    error_count: int = 0
    integrity_verified: bool = False
    integrity_errors: list[str] = field(default_factory=list)
    digest: str = ""
    generated_at: str = ""
    source_ledger: str = LEDGER_FILE


def _normalize_event(raw: dict[str, Any]) -> ProviderEvidenceQuery:
    outcome = raw.get("outcome") or {}
    oc = outcome.get("outcome_class", "unknown")
    return ProviderEvidenceQuery(
        event_id=raw.get("event_id", ""),
        created_at=raw.get("created_at", ""),
        session_id=raw.get("session_id", ""),
        correlation_id=raw.get("correlation_id", ""),
        provider_id=outcome.get("requested_provider_id", "unknown"),
        model_id=outcome.get("requested_model_id", "unknown"),
        api_style=outcome.get("api_style", "unknown"),
        outcome_class=oc,
        streaming=bool(outcome.get("streaming", False)),
        input_tokens=outcome.get("input_tokens"),
        output_tokens=outcome.get("output_tokens"),
        total_tokens=outcome.get("total_tokens"),
        cache_read_tokens=outcome.get("cache_read_tokens"),
        cache_read_verified=outcome.get("cache_read_verified"),
        reasoning_tokens=outcome.get("reasoning_tokens"),
        reasoning_tokens_verified=outcome.get("reasoning_tokens_verified"),
        usage_discrepancy_detected=outcome.get("usage_discrepancy_detected"),
        usage_verified=outcome.get("usage_verified"),
        is_refusal=oc in _REFUSAL_CLASSES,
        is_error=oc == "error",
        event_digest=raw.get("event_digest", ""),
        content_light=bool(raw.get("content_light", True)),
    )


def _verify_integrity(
    normalized: list[ProviderEvidenceQuery], verified: VerifiedLedgerResult
) -> tuple[bool, list[str]]:
    """Verify integrity against canonical recomputed digests.

    Uses the verified reader's recomputed digest comparison, not merely
    digest-string shape. Corrupt events in the verified result cause
    integrity failure.
    """
    errors: list[str] = list(verified.corruption_summary)
    if not verified.corpus_integrity_verified:
        return False, errors

    digests = [e.event_digest for e in normalized if e.event_digest]
    if len(digests) != len(normalized):
        errors.append("Some normalized events have empty digests")
    if len(set(digests)) != len(normalized):
        errors.append("Duplicate event digests detected")

    if not errors:
        return True, []
    return False, errors


def _compute_projection_digest(
    events: list[ProviderEvidenceQuery], query_description: str
) -> str:
    payload: dict[str, Any] = {
        "schema": _PROJECTION_SCHEMA_VERSION,
        "query": query_description,
        "event_ids": sorted(e.event_id for e in events),
        "event_digests": sorted(e.event_digest for e in events),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProviderEvidenceQueryService:
    """Typed read-side query service over verified canonical provider evidence.

    All methods are read-only. Never mutates the canonical ledger.
    Returns typed, content-light, deterministic projections.

    By default, loads events through the verified reader which schema-validates
    and digest-recomputes every event. A tampered ledger causes integrity failure;
    corrupt events are surfaced but excluded from valid result sets.
    """

    def __init__(self, verified: VerifiedLedgerResult | None = None) -> None:
        if verified is None:
            verified = load_verified_provider_events()
        self._verified = verified
        self._normalized: list[ProviderEvidenceQuery] = [
            _normalize_event(e) for e in verified.valid_events
        ]
        self._integrity_ok, self._integrity_errors = _verify_integrity(
            self._normalized, verified
        )

    @classmethod
    def from_test_events(
        cls, events: list[dict[str, Any]], *, canonical_source: bool = False
    ) -> ProviderEvidenceQueryService:
        """Construct a service from test-only event dictionaries.

        Args:
            events: Raw event dictionaries for testing.
            canonical_source: True only when events were admitted through
                persist_provider_event() and re-read through
                load_verified_provider_events(). When False, integrity
                verification is skipped and projections never claim
                integrity_verified=True.

        Returns:
            A service instance suitable for testing query logic without
            requiring a real ledger file.
        """
        if canonical_source:
            from rig_relay.providers.evidence_ledger import (
                _recompute_event_digest,
                _validate_event_against_schema,
            )

            result = VerifiedLedgerResult()
            seen_ids: set[str] = set()
            seen_digests: set[str] = set()
            for e in events:
                result.total_lines += 1
                try:
                    _validate_event_against_schema(e)
                except Exception as exc:
                    result.schema_invalid_count += 1
                    result.corpus_integrity_verified = False
                    result.corruption_summary.append(
                        f"Event {e.get('event_id', '?')}: schema invalid"
                    )
                    result.events.append(
                        VerifiedProviderEvent(
                            event=e,
                            event_id=e.get("event_id", ""),
                            is_corrupt=True,
                            corruption_kind="schema_invalid",
                            corruption_detail=str(exc),
                        )
                    )
                    result.corrupt_events.append(result.events[-1])
                    continue

                recomputed = _recompute_event_digest(e)
                if recomputed != e.get("event_digest", ""):
                    result.digest_mismatch_count += 1
                    result.corpus_integrity_verified = False
                    result.corruption_summary.append(
                        f"Event {e.get('event_id', '?')}: digest mismatch"
                    )
                    result.events.append(
                        VerifiedProviderEvent(
                            event=e,
                            event_id=e.get("event_id", ""),
                            is_corrupt=True,
                            corruption_kind="digest_mismatch",
                        )
                    )
                    result.corrupt_events.append(result.events[-1])
                    continue

                eid = e.get("event_id", "")
                dg = e.get("event_digest", "")
                if eid in seen_ids or dg in seen_digests:
                    result.duplicate_event_id_count += eid in seen_ids
                    result.duplicate_digest_count += dg in seen_digests
                    result.corpus_integrity_verified = False
                    result.corruption_summary.append(f"Event {eid}: duplicate")
                    result.events.append(
                        VerifiedProviderEvent(
                            event=e,
                            event_id=eid,
                            is_corrupt=True,
                            corruption_kind="duplicate",
                        )
                    )
                    result.corrupt_events.append(result.events[-1])
                    continue

                seen_ids.add(eid)
                seen_digests.add(dg)
                result.events.append(
                    VerifiedProviderEvent(
                        event=e, event_id=eid, event_digest=dg, is_valid=True
                    )
                )
                result.valid_events.append(e)

            if not result.corruption_summary:
                result.corpus_integrity_verified = True
            return cls(verified=result)

        verified = VerifiedLedgerResult(
            events=[
                VerifiedProviderEvent(
                    event=e,
                    event_id=e.get("event_id", ""),
                    event_digest=e.get("event_digest", ""),
                    is_valid=True,
                )
                for e in events
            ],
            total_lines=len(events),
            valid_events=events,
            corpus_integrity_verified=False,
        )
        return cls(verified=verified)

    @property
    def event_count(self) -> int:
        return len(self._normalized)

    @property
    def corrupt_count(self) -> int:
        return len(self._verified.corrupt_events)

    @property
    def integrity_verified(self) -> bool:
        return self._integrity_ok

    @property
    def integrity_errors(self) -> list[str]:
        return list(self._integrity_errors)

    @property
    def corruption_summary(self) -> list[str]:
        return list(self._verified.corruption_summary)

    def all_events(self) -> list[ProviderEvidenceQuery]:
        """Return all valid normalized evidence events."""
        return list(self._normalized)

    def corrupt_events(self) -> list[dict[str, Any]]:
        """Return raw corrupt/untrusted events surfaced by the verified reader."""
        return [v.event for v in self._verified.corrupt_events]

    def list_by_provider(self, provider_id: str) -> ProviderEvidenceQueryResult:
        """Filter valid events by requested provider identity."""
        return self._build_result(
            [e for e in self._normalized if e.provider_id == provider_id],
            f"provider_id={provider_id}",
        )

    def list_by_api_style(self, api_style: str) -> ProviderEvidenceQueryResult:
        """Filter valid events by adapter api_style (e.g. openai, anthropic, openai-responses)."""
        return self._build_result(
            [e for e in self._normalized if e.api_style == api_style],
            f"api_style={api_style}",
        )

    def list_streaming(self) -> ProviderEvidenceQueryResult:
        """Return valid streaming events."""
        return self._build_result(
            [e for e in self._normalized if e.streaming], "streaming=true"
        )

    def list_non_streaming(self) -> ProviderEvidenceQueryResult:
        """Return valid non-streaming events."""
        return self._build_result(
            [e for e in self._normalized if not e.streaming], "streaming=false"
        )

    def list_with_cached_tokens(self) -> ProviderEvidenceQueryResult:
        """Return valid events with verified cached-token details."""
        return self._build_result(
            [e for e in self._normalized if e.cache_read_verified],
            "cache_read_verified=true",
        )

    def list_with_reasoning_tokens(self) -> ProviderEvidenceQueryResult:
        """Return valid events with verified reasoning-token details."""
        return self._build_result(
            [e for e in self._normalized if e.reasoning_tokens_verified],
            "reasoning_tokens_verified=true",
        )

    def list_with_discrepancy(self) -> ProviderEvidenceQueryResult:
        """Return valid events where usage discrepancy was detected."""
        return self._build_result(
            [e for e in self._normalized if e.usage_discrepancy_detected],
            "usage_discrepancy_detected=true",
        )

    def list_refusals(self) -> ProviderEvidenceQueryResult:
        """Return valid refusal and safety-block events."""
        return self._build_result(
            [e for e in self._normalized if e.is_refusal],
            "outcome_class in (refusal, safety_block)",
        )

    def list_errors(self) -> ProviderEvidenceQueryResult:
        """Return valid error events."""
        return self._build_result(
            [e for e in self._normalized if e.is_error], "outcome_class=error"
        )

    def list_degraded(self) -> ProviderEvidenceQueryResult:
        """Return valid events with degraded or unverified usage evidence."""
        return self._build_result(
            [e for e in self._normalized if e.usage_verified is not True],
            "usage_verified != true",
        )

    def lookup_by_event_id(self, event_id: str) -> ProviderEvidenceQuery | None:
        """Look up a single valid event by its event_id."""
        for e in self._normalized:
            if e.event_id == event_id:
                return e
        return None

    def lookup_by_digest(self, digest: str) -> ProviderEvidenceQuery | None:
        """Look up a single valid event by its event_digest."""
        for e in self._normalized:
            if e.event_digest == digest:
                return e
        return None

    def build_summary(self) -> ProviderEvidenceSummary:
        """Build a content-light aggregate summary from valid evidence only."""
        provider_ids: list[str] = []
        api_styles: list[str] = []
        streaming = 0
        non_streaming = 0
        cached_verified = 0
        reasoning_verified = 0
        discrepancy = 0
        refusals = 0
        errors = 0

        for e in self._normalized:
            if e.provider_id not in provider_ids:
                provider_ids.append(e.provider_id)
            if e.api_style not in api_styles:
                api_styles.append(e.api_style)
            if e.streaming:
                streaming += 1
            else:
                non_streaming += 1
            if e.cache_read_verified:
                cached_verified += 1
            if e.reasoning_tokens_verified:
                reasoning_verified += 1
            if e.usage_discrepancy_detected:
                discrepancy += 1
            if e.is_refusal:
                refusals += 1
            if e.is_error:
                errors += 1

        provider_ids.sort()
        api_styles.sort()

        integrity_errors = list(self._integrity_errors)
        if self._verified.corrupt_events:
            integrity_errors.append(
                f"Corrupt events detected: {len(self._verified.corrupt_events)}"
            )

        summary_data: dict[str, Any] = {
            "schema_version": _PROJECTION_SCHEMA_VERSION,
            "total_events": len(self._normalized),
            "corrupt_events": len(self._verified.corrupt_events),
            "provider_ids": provider_ids,
            "api_styles": api_styles,
            "streaming_count": streaming,
            "non_streaming_count": non_streaming,
            "cached_token_verified_count": cached_verified,
            "reasoning_token_verified_count": reasoning_verified,
            "discrepancy_count": discrepancy,
            "refusal_count": refusals,
            "error_count": errors,
            "integrity_verified": self._integrity_ok,
            "integrity_errors": integrity_errors,
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(summary_data, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
        )

        return ProviderEvidenceSummary(
            total_events=len(self._normalized),
            provider_ids=provider_ids,
            api_styles=api_styles,
            streaming_count=streaming,
            non_streaming_count=non_streaming,
            cached_token_verified_count=cached_verified,
            reasoning_token_verified_count=reasoning_verified,
            discrepancy_count=discrepancy,
            refusal_count=refusals,
            error_count=errors,
            integrity_verified=self._integrity_ok,
            integrity_errors=integrity_errors,
            digest=digest,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def build_integrity_projection(self) -> ProviderEvidenceQueryResult:
        """Return events with integrity validation failures only."""
        return self._build_result(
            [
                e
                for e in self._normalized
                if (not e.event_digest)
                or (not e.event_digest.startswith("sha256:"))
                or (not e.content_light)
            ],
            "integrity_invalid",
        )

    def _build_result(
        self, events: list[ProviderEvidenceQuery], query_description: str
    ) -> ProviderEvidenceQueryResult:
        dig = _compute_projection_digest(events, query_description)
        return ProviderEvidenceQueryResult(
            events=events,
            total_canonical_events=len(self._normalized),
            matched_count=len(events),
            integrity_verified=self._integrity_ok,
            integrity_errors=self._integrity_errors,
            projection_digest=dig,
            generated_at=datetime.now(UTC).isoformat(),
            query_description=query_description,
        )


__all__ = [
    "ProviderEvidenceQuery",
    "ProviderEvidenceQueryResult",
    "ProviderEvidenceQueryService",
    "ProviderEvidenceSummary",
]

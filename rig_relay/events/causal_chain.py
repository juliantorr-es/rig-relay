from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto


class CausalConfidence(StrEnum):
    OBSERVED = auto()
    DERIVED = auto()
    INFERRED = auto()
    CORRELATED_ONLY = auto()
    REJECTED = auto()


@dataclass(slots=True)
class CausalLink:
    from_event_id: str
    to_event_id: str
    relationship: str
    evidence: str
    confidence: CausalConfidence = CausalConfidence.OBSERVED


def build_causal_chain(events: list[dict]) -> list[CausalLink]:
    links: list[CausalLink] = []

    groups: dict[str, list[dict]] = {}
    for event in events:
        corr_id = event.get("correlation_id", "")
        if not corr_id:
            continue
        groups.setdefault(corr_id, []).append(event)

    for corr_events in groups.values():
        corr_events.sort(key=lambda e: (e.get("occurred_at", ""), e.get("sequence", 0)))
        event_ids = {e["event_id"] for e in corr_events}
        causally_linked_to: set[str] = set()

        for event in corr_events:
            causation_id = event.get("causation_id", "")
            if causation_id and causation_id in event_ids:
                links.append(
                    CausalLink(
                        from_event_id=causation_id,
                        to_event_id=event["event_id"],
                        relationship="caused",
                        evidence="causation_id",
                        confidence=CausalConfidence.OBSERVED,
                    )
                )
                causally_linked_to.add(event["event_id"])

        if corr_events:
            anchor = corr_events[0]
            for event in corr_events:
                if event is anchor:
                    continue
                if event["event_id"] in causally_linked_to:
                    continue
                links.append(
                    CausalLink(
                        from_event_id=anchor["event_id"],
                        to_event_id=event["event_id"],
                        relationship="correlated_with",
                        evidence="correlation_id",
                        confidence=CausalConfidence.CORRELATED_ONLY,
                    )
                )

    return links


def chain_from_correlation(events: list[dict], correlation_id: str) -> list[CausalLink]:
    filtered = [e for e in events if e.get("correlation_id") == correlation_id]
    return build_causal_chain(filtered)


__all__ = [
    "CausalConfidence",
    "CausalLink",
    "build_causal_chain",
    "chain_from_correlation",
]

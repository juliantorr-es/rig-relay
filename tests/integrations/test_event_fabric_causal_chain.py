from __future__ import annotations

import pytest

from rig_relay.events.causal_chain import (
    CausalConfidence,
    build_causal_chain,
    chain_from_correlation,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def make_event(
    event_id: str,
    correlation_id: str = "corr_a",
    causation_id: str = "",
    occurred_at: str = "2025-01-01T00:00:00+00:00",
    sequence: int = 0,
) -> dict:
    return {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "occurred_at": occurred_at,
        "sequence": sequence,
    }


def test_matching_causation_id_produces_observed_link():
    events = [
        make_event("evt_a", causation_id=""),
        make_event(
            "evt_b",
            causation_id="evt_a",
            occurred_at="2025-01-01T00:01:00+00:00",
            sequence=1,
        ),
    ]
    links = build_causal_chain(events)
    observed = [l for l in links if l.confidence == CausalConfidence.OBSERVED]
    assert len(observed) == 1
    assert observed[0].from_event_id == "evt_a"
    assert observed[0].to_event_id == "evt_b"
    assert observed[0].relationship == "caused"


def test_same_correlation_no_causation_produces_correlated_only():
    events = [
        make_event("evt_a"),
        make_event("evt_b", occurred_at="2025-01-01T00:01:00+00:00", sequence=1),
    ]
    links = build_causal_chain(events)
    correlated = [l for l in links if l.confidence == CausalConfidence.CORRELATED_ONLY]
    assert len(correlated) == 1
    assert correlated[0].from_event_id == "evt_a"
    assert correlated[0].to_event_id == "evt_b"
    assert correlated[0].relationship == "correlated_with"


def test_causation_link_suppresses_correlation_for_same_target():
    events = [
        make_event("evt_a"),
        make_event(
            "evt_b",
            causation_id="evt_a",
            occurred_at="2025-01-01T00:01:00+00:00",
            sequence=1,
        ),
    ]
    links = build_causal_chain(events)
    for link in links:
        if link.to_event_id == "evt_b":
            assert link.confidence == CausalConfidence.OBSERVED


def test_chain_from_correlation_filters_by_correlation_id():
    events = [
        make_event("evt_a", correlation_id="corr_x"),
        make_event(
            "evt_b",
            correlation_id="corr_y",
            occurred_at="2025-01-01T00:01:00+00:00",
            sequence=1,
        ),
    ]
    links = chain_from_correlation(events, "corr_x")
    assert len(links) == 0


def test_empty_event_list_produces_empty_chain():
    links = build_causal_chain([])
    assert links == []


def test_causation_id_pointing_to_nonexistent_event_handled_gracefully():
    events = [
        make_event(
            "evt_orphan", correlation_id="corr_z", causation_id="evt_nonexistent"
        )
    ]
    links = build_causal_chain(events)
    observed = [l for l in links if l.confidence == CausalConfidence.OBSERVED]
    assert len(observed) == 0


def test_events_without_correlation_id_are_ignored():
    events = [
        make_event("evt_a", correlation_id=""),
        make_event(
            "evt_b",
            correlation_id="",
            occurred_at="2025-01-01T00:01:00+00:00",
            sequence=1,
        ),
    ]
    links = build_causal_chain(events)
    assert links == []

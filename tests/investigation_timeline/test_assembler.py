from __future__ import annotations

from pathlib import Path

from rig_relay.investigation_timeline._assembler import InvestigationTimelineAssembler
from rig_relay.investigation_timeline._models import AuthorityClassification

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_assemble_with_three_domains_produces_timeline():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-assemble-001",
    )
    result = assembler.assemble()
    assert result.timeline.events
    assert len(result.timeline.events) > 0
    assert result.timeline.event_count > 0
    assert len(result.timeline.domain_coverage) >= 3


def test_assemble_deterministic_ordering():
    assembler1 = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-det-001",
    )
    assembler2 = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-det-001",
    )
    result1 = assembler1.assemble()
    result2 = assembler2.assemble()

    assert result1.timeline.event_count == result2.timeline.event_count
    assert result1.timeline.event_count > 0

    kinds_1 = [e.event_kind.value for e in result1.timeline.events]
    kinds_2 = [e.event_kind.value for e in result2.timeline.events]
    assert kinds_1 == kinds_2

    digests_1 = [e.source_digest for e in result1.timeline.events]
    digests_2 = [e.source_digest for e in result2.timeline.events]
    assert digests_1 == digests_2


def test_assemble_preserves_source_digests():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        investigation_id="inv-src-001",
    )
    result = assembler.assemble()
    for event in result.timeline.events:
        assert event.source_digest
        assert event.source_digest.startswith("sha256:")


def test_assemble_preserves_authority_classification():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        investigation_id="inv-auth-001",
    )
    result = assembler.assemble()
    for event in result.timeline.events:
        assert event.authority_classification
        assert isinstance(event.authority_classification, AuthorityClassification)


def test_assemble_reports_unsupported_domains():
    assembler = InvestigationTimelineAssembler(investigation_id="inv-unsup-001")
    result = assembler.assemble()
    assert len(result.timeline.unsupported_domains) > 0
    assert "observability" in result.timeline.unsupported_domains


def test_assemble_with_malformed_evidence():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "malformed_evidence.jsonl",
        investigation_id="inv-mal-001",
    )
    result = assembler.assemble()
    assert result.timeline is not None
    assert len(result.errors) > 0
    assert any("malformed JSON" in err for err in result.errors)


def test_assemble_calls_content_light_enforcement():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        investigation_id="inv-cl-001",
    )
    result = assembler.assemble()
    assert result.timeline.content_light_guarantee is True
    for event in result.timeline.events:
        assert event.content_light_guarantee is True

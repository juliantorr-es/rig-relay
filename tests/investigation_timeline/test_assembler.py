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


def test_assembler_preserves_producer_digests():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        publication_ledger_path=FIXTURES_DIR / "publication_preview_sample.jsonl",
        investigation_id="inv-prod-001",
    )
    result = assembler.assemble()
    events_with_producer = [
        e for e in result.timeline.events if e.producer_digest is not None
    ]
    assert len(events_with_producer) > 0, (
        "at least some events must have producer_digest"
    )
    for e in events_with_producer:
        assert e.producer_digest is not None
        assert e.producer_digest.startswith("sha256:")


def test_assembler_counts_verification_classes():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-ver-001",
    )
    result = assembler.assemble()
    ds = result.timeline.degradation_summary
    assert ds.verified_canonical_count > 0, (
        "must count verified canonical events in degradation summary"
    )


def test_assembler_deterministic_with_new_fields():
    assembler1 = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-det-new-001",
    )
    assembler2 = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-det-new-001",
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

    verification_1 = [e.verification_class for e in result1.timeline.events]
    verification_2 = [e.verification_class for e in result2.timeline.events]
    assert verification_1 == verification_2

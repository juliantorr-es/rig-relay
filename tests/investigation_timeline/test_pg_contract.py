from __future__ import annotations

from pathlib import Path

from rig_relay.investigation_timeline._assembler import InvestigationTimelineAssembler
from rig_relay.investigation_timeline._pg_contract import (
    build_postgres_column_definitions,
    build_postgres_indexing_requirements,
    build_postgres_projection,
    build_query_capabilities,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_build_postgres_projection_produces_rows():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        investigation_id="inv-pg-001",
    )
    result = assembler.assemble()
    projection = build_postgres_projection(result.timeline)
    assert projection.row_count == len(projection.rows)
    assert projection.row_count > 0
    assert projection.timeline_id == result.timeline.timeline_id

    first_row = projection.rows[0]
    assert "event_id" in first_row
    assert "observed_at" in first_row
    assert "event_kind" in first_row
    assert "source_domain" in first_row
    assert "source_digest" in first_row
    assert "authority_classification" in first_row
    assert "content_light_guarantee" in first_row
    assert first_row["content_light_guarantee"] is True


def test_postgres_projection_is_deterministic():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        investigation_id="inv-pg-det-001",
    )
    result = assembler.assemble()
    projection1 = build_postgres_projection(result.timeline)
    projection2 = build_postgres_projection(result.timeline)

    assert projection1.row_count == projection2.row_count
    for r1, r2 in zip(projection1.rows, projection2.rows, strict=True):
        assert r1 == r2


def test_postgres_indexing_requirements_exist():
    indexes = build_postgres_indexing_requirements()
    assert len(indexes) > 0
    index_names = {idx.index_name for idx in indexes}
    assert "idx_timeline_sequence" in index_names
    assert "idx_timeline_event_kind" in index_names
    assert "idx_timeline_authority_classification" in index_names
    assert "idx_timeline_session_id" in index_names
    assert all(idx.index_type == "btree" for idx in indexes)


def test_postgres_query_capabilities_listed():
    capabilities = build_query_capabilities()
    assert len(capabilities) > 0
    assert any("chronological" in c.lower() for c in capabilities)
    assert any("refusal" in c.lower() for c in capabilities)
    assert any("degradation" in c.lower() for c in capabilities)


def test_postgres_column_definitions_correct_count():
    columns = build_postgres_column_definitions()
    assert len(columns) >= 23
    column_names = {col.column_name for col in columns}
    assert "event_id" in column_names
    assert "timeline_sequence" in column_names
    assert "observed_at" in column_names
    assert "event_kind" in column_names
    assert "source_domain" in column_names
    assert "authority_classification" in column_names
    assert "content_light_guarantee" in column_names

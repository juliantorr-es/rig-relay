from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.investigation_timeline._assembler import InvestigationTimelineAssembler
from rig_relay.investigation_timeline._duckdb_export import build_duckdb_export

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def assembled_timeline():
    assembler = InvestigationTimelineAssembler(
        observability_path=FIXTURES_DIR / "observability_sample.jsonl",
        coordination_path=FIXTURES_DIR / "coordination_events_sample.jsonl",
        disclosure_path=FIXTURES_DIR / "disclosure_transitions_sample.jsonl",
        investigation_id="inv-ddb-001",
    )
    return assembler.assemble().timeline


def test_build_duckdb_export_produces_datasets(assembled_timeline, tmp_path):
    export = build_duckdb_export(assembled_timeline, tmp_path)
    assert len(export.datasets) > 0
    dataset_names = {ds.dataset_name for ds in export.datasets}
    assert "investigation_timeline_events" in dataset_names
    assert "investigation_timeline_aggregates" in dataset_names

    events_path = tmp_path / "investigation_timeline_events.jsonl"
    assert events_path.exists()
    aggregates_path = tmp_path / "investigation_timeline_summary.jsonl"
    assert aggregates_path.exists()

    for ds in export.datasets:
        assert ds.dataset_sha256.startswith("sha256:")
        assert ds.row_count >= 0


def test_duckdb_export_is_rebuildable(assembled_timeline, tmp_path):
    export1 = build_duckdb_export(assembled_timeline, tmp_path / "run1")
    export2 = build_duckdb_export(assembled_timeline, tmp_path / "run2")

    sha1 = export1.datasets[0].dataset_sha256
    sha2 = export2.datasets[0].dataset_sha256
    assert sha1 == sha2


def test_duckdb_export_asserts_read_side_only(assembled_timeline, tmp_path):
    export = build_duckdb_export(assembled_timeline, tmp_path)
    authority = export.authority_separation
    assert authority.read_side_only is True
    assert authority.mutation_authority is False


def test_duckdb_export_has_view_definitions(assembled_timeline, tmp_path):
    export = build_duckdb_export(assembled_timeline, tmp_path)
    assert len(export.view_definitions) > 0
    view_names = {v.view_name for v in export.view_definitions}
    assert "v_timeline_chronological" in view_names
    assert "v_timeline_refusals" in view_names
    assert "v_timeline_degradation" in view_names
    assert "v_timeline_tool_outcomes" in view_names
    assert "v_timeline_checkpoints" in view_names
    for v_def in export.view_definitions:
        assert v_def.sql
        assert "CREATE" in v_def.sql


def test_duckdb_export_content_light_enforcement(assembled_timeline, tmp_path):
    export = build_duckdb_export(assembled_timeline, tmp_path)
    assert export.content_light_guarantee is True
    assert export.rebuildable is True

    events_path = tmp_path / "investigation_timeline_events.jsonl"
    content = events_path.read_text()
    forbidden_fields = [
        "raw_file_contents",
        "api_key",
        "stdout",
        "stderr",
        "raw_prompt",
    ]
    for field in forbidden_fields:
        assert field not in content.lower()


def test_duckdb_export_includes_verification_class(assembled_timeline, tmp_path):
    export = build_duckdb_export(assembled_timeline, tmp_path)
    assert export.rebuildable is True
    events_path = tmp_path / "investigation_timeline_events.jsonl"
    assert events_path.exists()

    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            assert "verification_class" in row, (
                "exported dataset row must include verification_class field"
            )
            assert row["verification_class"] in {
                "VERIFIED_CANONICAL",
                "PARSED_UNVERIFIED",
                "CANONICAL_DEGRADED",
                "CORRUPT",
                "UNSUPPORTED",
                "MISSING",
            }

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.rig_relay_create_builtin_refinement_packets import generate_packets


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _sample_backlog() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "rig.relay.builtin_tool_refinement_item.v1",
            "item_id": "refine_1",
            "created_at": "2026-05-13T00:00:00Z",
            "tool_name": "bash",
            "tool_family": "bash",
            "refinement_kind": "replace_shell_pattern",
            "priority": "P0",
            "confidence": 0.9,
            "evidence_window": "window",
            "evidence_sources": ["tool_failure_patterns_dataset"],
            "event_count": 10,
            "failure_count": 2,
            "refusal_count": 0,
            "timeout_count": 0,
            "fallback_to_bash_count": 8,
            "truncation_count": 0,
            "artifact_size_bytes": 1,
            "storage_pressure_score": 0,
            "coordination_pressure_score": 0,
            "suggested_replacement_tool": "typed built-in",
            "recommended_action": "Create typed built-in.",
            "rationale": "Repeated fallback to bash indicates a typed surface would remove brittle shell parsing.",
            "safety_notes": "Content-light row.",
            "warnings": [],
        },
        {
            "schema_version": "rig.relay.builtin_tool_refinement_item.v1",
            "item_id": "refine_2",
            "created_at": "2026-05-13T00:00:00Z",
            "tool_name": "read_file",
            "tool_family": "read",
            "refinement_kind": "harden_existing_tool",
            "priority": "P2",
            "confidence": 0.6,
            "evidence_window": "window",
            "evidence_sources": ["tool_failure_patterns_dataset"],
            "event_count": 3,
            "failure_count": 1,
            "refusal_count": 0,
            "timeout_count": 0,
            "fallback_to_bash_count": 0,
            "truncation_count": 0,
            "artifact_size_bytes": 1,
            "storage_pressure_score": 0,
            "coordination_pressure_score": 0,
            "suggested_replacement_tool": None,
            "recommended_action": "Harden the existing tool.",
            "rationale": "Failure signal.",
            "safety_notes": "Content-light row.",
            "warnings": [],
        },
    ]


def test_dry_run_reports_selected_items_without_writing_files(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    packet_paths, warnings = generate_packets(
        backlog, report, tmp_path / "out", 1, None, True
    )
    assert packet_paths
    assert not warnings
    assert not any((tmp_path / "out").rglob("mission_packet.json"))


def test_generator_creates_one_packet_per_top_backlog_item(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    packet_paths, warnings = generate_packets(
        backlog, report, tmp_path / "out", 2, None, False
    )
    assert len(packet_paths) == 2
    assert not warnings
    assert len(list((tmp_path / "out").glob("*/mission_packet.json"))) == 2


def test_prompt_begins_with_required_agents_sentence(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    generate_packets(backlog, report, tmp_path / "out", 1, None, False)
    prompt = next((tmp_path / "out").glob("*/prompt.md")).read_text(encoding="utf-8")
    assert prompt.startswith(
        "Before doing anything, read AGENTS.md and summarize the Git discipline rules you will follow. Do not edit files until you have done that."
    )


def test_generated_packet_references_source_item_id(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    generate_packets(backlog, report, tmp_path / "out", 1, None, False)
    packet = json.loads(
        next((tmp_path / "out").glob("*/mission_packet.json")).read_text(
            encoding="utf-8"
        )
    )
    assert packet["source_item_id"] == "refine_1"


def test_generated_content_is_content_light(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    generate_packets(backlog, report, tmp_path / "out", 1, None, False)
    prompt = next((tmp_path / "out").glob("*/prompt.md")).read_text(encoding="utf-8")
    assert "stdout" not in prompt
    assert "stderr" not in prompt
    assert "diff" not in prompt


def test_missing_backlog_produces_clear_warning(tmp_path: Path) -> None:
    packet_paths, warnings = generate_packets(
        tmp_path / "missing.jsonl",
        tmp_path / "report.md",
        tmp_path / "out",
        1,
        None,
        True,
    )
    assert not packet_paths
    assert warnings
    assert "Backlog not found" in warnings[0]


def test_priority_filter_and_limit_work(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    packet_paths, warnings = generate_packets(
        backlog, report, tmp_path / "out", 1, {"P0"}, False
    )
    assert len(packet_paths) == 1
    assert not warnings
    assert "P0-bash" in packet_paths[0].name


def test_mission_packet_validates_against_existing_schema(tmp_path: Path) -> None:
    backlog = tmp_path / "backlog.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(backlog, _sample_backlog())
    report.write_text("# report", encoding="utf-8")
    generate_packets(backlog, report, tmp_path / "out", 1, None, False)
    packet = json.loads(
        next((tmp_path / "out").glob("*/mission_packet.json")).read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.builtin_tool_refinement_packet.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=packet, schema=schema)

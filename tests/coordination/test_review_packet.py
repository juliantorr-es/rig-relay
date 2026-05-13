from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rig_relay_create_review_packet import (
    VALID_REVIEW_KINDS,
    _generate_review_id,
    _validate_schema,
    create_review_packet,
)


def test_generate_review_id() -> None:
    rid = _generate_review_id()
    assert rid.startswith("review_")
    assert len(rid) > 10


def test_create_packet_basic(tmp_path: Path) -> None:
    report = tmp_path / "final_report.md"
    report.write_text("# Mission complete\n\nAll tests pass.", encoding="utf-8")

    packet = create_review_packet(
        session_id="sess-1",
        task_id="task-1",
        final_report_path=report,
        review_kind="next_slice",
        output_dir=tmp_path / "out",
        branch="main",
        head="abc123",
    )
    assert packet["session_id"] == "sess-1"
    assert packet["task_id"] == "task-1"
    assert packet["requested_review_kind"] == "next_slice"
    assert packet["branch"] == "main"
    assert packet["head"] == "abc123"
    assert packet["status"] == "needs_review"
    assert packet["schema_version"] == "rig.relay.review_packet.v1"

    # Check output layout
    out_dir = tmp_path / "out"
    assert (out_dir / "review_packet.json").is_file()
    assert (out_dir / "final_report.md").is_file()
    assert (out_dir / "README.md").is_file()
    assert (out_dir / "reviewer_response.md").is_file()
    assert (out_dir / "resume_prompt.md").is_file()


def test_create_packet_with_artifact_manifest(tmp_path: Path) -> None:
    report = tmp_path / "final_report.md"
    report.write_text("# Report", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"files": ["a.py"]}', encoding="utf-8")

    packet = create_review_packet(
        session_id="sess-1",
        final_report_path=report,
        artifact_manifest_path=manifest,
        review_kind="risk_review",
        output_dir=tmp_path / "out",
    )
    assert packet["artifact_manifest_path"] is not None
    assert packet["artifact_manifest_path"].endswith("artifact_manifest.json")
    assert (tmp_path / "out" / "artifact_manifest.json").is_file()


def test_create_packet_with_dataset_report(tmp_path: Path) -> None:
    report = tmp_path / "final_report.md"
    report.write_text("# Report", encoding="utf-8")
    dataset = tmp_path / "dataset_report.json"
    dataset.write_text('{"row_counts": {"test": 5}}', encoding="utf-8")

    packet = create_review_packet(
        session_id="sess-1",
        final_report_path=report,
        dataset_report_path=dataset,
        review_kind="dataset_review",
        output_dir=tmp_path / "out",
    )
    assert packet["dataset_report_path"] is not None
    assert (tmp_path / "out" / "dataset_report.json").is_file()


def test_create_packet_missing_report_fails(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    with pytest.raises(SystemExit):
        create_review_packet(
            session_id="sess-1",
            final_report_path=missing,
            review_kind="next_slice",
            output_dir=tmp_path / "out",
        )


def test_create_packet_invalid_review_kind_fails(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# x", encoding="utf-8")
    with pytest.raises(SystemExit):
        create_review_packet(
            session_id="s-1",
            final_report_path=report,
            review_kind="invalid_kind",
            output_dir=tmp_path / "out",
        )


def test_create_packet_invalid_status_fails(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# x", encoding="utf-8")
    with pytest.raises(SystemExit):
        create_review_packet(
            session_id="s-1",
            final_report_path=report,
            review_kind="next_slice",
            status="bad_status",
            output_dir=tmp_path / "out",
        )


def test_create_packet_all_review_kinds(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# Report", encoding="utf-8")

    for kind in sorted(VALID_REVIEW_KINDS):
        out = tmp_path / kind
        packet = create_review_packet(
            session_id="s-1", final_report_path=report, review_kind=kind, output_dir=out
        )
        assert packet["requested_review_kind"] == kind
        assert (out / "review_packet.json").is_file()


def test_create_packet_with_all_optional_paths(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# R")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    dataset = tmp_path / "dataset.json"
    dataset.write_text("{}")
    coord = tmp_path / "coord.json"
    coord.write_text("{}")
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text("{}")

    packet = create_review_packet(
        session_id="s-1",
        final_report_path=report,
        artifact_manifest_path=manifest,
        dataset_report_path=dataset,
        coordination_summary_path=coord,
        checkpoint_summary_path=ckpt,
        review_kind="architecture_review",
        output_dir=tmp_path / "full",
        branch="main",
        head="def456",
    )
    assert packet["artifact_manifest_path"] is not None
    assert packet["dataset_report_path"] is not None
    assert packet["coordination_summary_path"] is not None
    assert packet["checkpoint_summary_path"] is not None

    out = tmp_path / "full"
    assert (out / "artifact_manifest.json").is_file()
    assert (out / "dataset_report.json").is_file()
    assert (out / "coordination_summary.json").is_file()
    assert (out / "checkpoint_summary.json").is_file()


def test_schema_validation_passes(tmp_path: Path) -> None:
    """Packet should validate against the JSON Schema."""
    report = tmp_path / "r.md"
    report.write_text("# x")
    packet = create_review_packet(
        session_id="s-1",
        final_report_path=report,
        review_kind="prompt_generation",
        output_dir=tmp_path / "out",
    )
    errors = _validate_schema(packet)
    assert errors == [], f"Schema validation errors: {errors}"


def test_packet_does_not_embed_raw_content(tmp_path: Path) -> None:
    """Verify review_packet.json does not contain raw file contents, secrets, etc."""
    report = tmp_path / "r.md"
    report.write_text("# Some sensitive output\n\napi_key=sk-test\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"files": ["secret.py"]}', encoding="utf-8")

    packet = create_review_packet(
        session_id="s-1",
        final_report_path=report,
        artifact_manifest_path=manifest,
        review_kind="commit_review",
        output_dir=tmp_path / "out",
    )

    packet_json = json.dumps(packet)
    # The packet should not embed the actual file contents
    assert "# Some sensitive output" not in packet_json
    assert "sk-test" not in packet_json
    # The manifest content should not be inlined
    assert '"files"' not in packet_json or packet_json.count('"files"') == 0
    # Only file paths, not contents
    assert packet["final_report_path"] is not None
    assert packet["artifact_manifest_path"] is not None


def test_forbidden_fields_in_packet(tmp_path: Path) -> None:
    """Default forbidden fields should be present in the packet."""
    report = tmp_path / "r.md"
    report.write_text("# x")
    packet = create_review_packet(
        session_id="s-1",
        final_report_path=report,
        review_kind="next_slice",
        output_dir=tmp_path / "out",
    )
    forbidden = packet.get("forbidden_fields", [])
    assert "raw_file_contents" in forbidden
    assert "secrets" in forbidden
    assert "raw_private_code" in forbidden
    assert "raw_prompt_text" in forbidden


def test_create_packet_with_parent_session(tmp_path: Path) -> None:
    report = tmp_path / "r.md"
    report.write_text("# x")
    packet = create_review_packet(
        session_id="child-sess",
        parent_session_id="parent-sess",
        final_report_path=report,
        review_kind="next_slice",
        output_dir=tmp_path / "out",
    )
    assert packet["parent_session_id"] == "parent-sess"


def test_readme_contains_review_kind(tmp_path: Path) -> None:
    report = tmp_path / "r.md"
    report.write_text("# x")
    create_review_packet(
        session_id="s-1",
        final_report_path=report,
        review_kind="risk_review",
        output_dir=tmp_path / "out",
    )
    readme = (tmp_path / "out" / "README.md").read_text(encoding="utf-8")
    assert "risk_review" in readme
    assert "safety" in readme.lower()

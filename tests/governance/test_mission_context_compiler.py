from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.governance.mission_context_compiler import (
    MissionContextCompiler,
    MissionContextCompilerResult,
)
from rig_relay.governance.mission_context_packet import (
    MissionContextPacket,
    MissionContextPacketReceipt,
)
from rig_relay.governance.mission_envelope import MissionEnvelope

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKET_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.mission_context_packet.v1.schema.json"
)
RECEIPT_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.mission_context_packet_receipt.v1.schema.json"
)


def _mission_envelope() -> MissionEnvelope:
    return MissionEnvelope.model_validate({
        "schema_version": "rig.mission_envelope.v1",
        "mission_id": "mission-2026-05-14-context-packet-spine",
        "title": "Compile deterministic mission context packet",
        "created_at": "2026-05-14T12:00:00+00:00",
        "repo_root": "/Users/user/Developer/GitHub/rig-relay",
        "branch": "main",
        "head": "61b46b8",
        "dirty_summary": {
            "tracked_modified_count": 1,
            "untracked_count": 0,
            "protected_dirty_count": 0,
        },
        "allowed_paths": ["docs/governance", "docs/schemas"],
        "protected_paths": ["/Users/user/.rig/relay"],
        "instruction_paths": ["AGENTS.md"],
        "acceptance_checks": [
            "uv run pytest tests/governance/test_mission_context_compiler.py -q"
        ],
        "handoff_required": True,
    })


def _compiler() -> MissionContextCompiler:
    return MissionContextCompiler()


def test_minimal_envelope_compiles_to_valid_packet_and_receipt(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "alpha.md").write_text("alpha\n", encoding="utf-8")
    (source_root / "beta.json").write_text('{"beta": 1}', encoding="utf-8")

    result = _compiler().compile(
        _mission_envelope(),
        source_roots=[source_root],
        created_at="2026-05-14T12:30:00+00:00",
    )

    assert isinstance(result, MissionContextCompilerResult)
    assert isinstance(result.packet, MissionContextPacket)
    assert isinstance(result.receipt, MissionContextPacketReceipt)
    assert result.packet.source_refs
    assert result.receipt.source_ref_count == len(result.packet.source_refs)


def test_packet_model_dump_validates_against_schema(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("hello\n", encoding="utf-8")
    result = _compiler().compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    schema = json.loads(PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result.packet.model_dump(mode="json"), schema=schema)


def test_receipt_model_dump_validates_against_schema(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("hello\n", encoding="utf-8")
    result = _compiler().compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=result.receipt.model_dump(mode="json"), schema=schema)


def test_source_ordering_is_deterministic(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "z.md").write_text("z\n", encoding="utf-8")
    (source_root / "a.md").write_text("a\n", encoding="utf-8")
    (source_root / "m.md").write_text("m\n", encoding="utf-8")

    result = _compiler().compile(
        _mission_envelope(),
        source_roots=[source_root],
        created_at="2026-05-14T12:30:00+00:00",
    )

    assert [ref.path for ref in result.packet.source_refs] == [
        str(source_root / "a.md"),
        str(source_root / "m.md"),
        str(source_root / "z.md"),
    ]


def test_packet_fingerprint_is_stable_across_repeated_runs(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("hello\n", encoding="utf-8")
    compiler = _compiler()
    first = compiler.compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    second = compiler.compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    assert first.packet.fingerprint == second.packet.fingerprint
    assert first.receipt.packet_sha256 == second.receipt.packet_sha256


def test_changed_source_bytes_change_packet_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("hello\n", encoding="utf-8")
    compiler = _compiler()
    first = compiler.compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    source.write_text("goodbye\n", encoding="utf-8")
    second = compiler.compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )
    assert first.packet.fingerprint != second.packet.fingerprint
    assert first.receipt.packet_sha256 != second.receipt.packet_sha256


def test_outside_allow_list_paths_are_ignored_with_blocker(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()
    inside = allowed_root / "inside.md"
    outside = outside_root / "outside.md"
    inside.write_text("inside\n", encoding="utf-8")
    outside.write_text("outside\n", encoding="utf-8")

    result = _compiler().compile(
        _mission_envelope(),
        source_paths=[inside, outside],
        source_roots=[allowed_root],
        created_at="2026-05-14T12:30:00+00:00",
    )

    assert [ref.path for ref in result.packet.source_refs] == [str(inside)]
    assert result.blockers
    assert any(blocker.kind == "outside_allow_list" for blocker in result.blockers)


def test_compiler_does_not_embed_forbidden_raw_fields(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("hello\n", encoding="utf-8")
    result = _compiler().compile(
        _mission_envelope(),
        source_paths=[source],
        created_at="2026-05-14T12:30:00+00:00",
    )

    forbidden = {
        "stdout",
        "stderr",
        "content",
        "chunk_text",
        "old_text",
        "new_text",
        "diff",
        "patch",
        "prompt",
        "secret",
        "argv",
    }
    assert forbidden.isdisjoint(result.packet.model_dump(mode="json"))
    assert forbidden.isdisjoint(result.receipt.model_dump(mode="json"))


def test_compiler_rejects_extra_fields_on_packet_and_receipt_models() -> None:
    with pytest.raises(ValidationError):
        MissionContextPacket.model_validate({
            "schema_version": "rig.mission_context_packet.v1",
            "packet_id": "packet",
            "mission_id": "mission",
            "title": "title",
            "created_at": "2026-05-14T12:30:00+00:00",
            "repo_root": "/tmp",
            "branch": "main",
            "head": "abc",
            "mission_envelope": None,
            "source_refs": [],
            "dirty_file_states": [],
            "required_checks": [],
            "warnings": [],
            "blockers": [],
            "allowed_paths": [],
            "protected_paths": [],
            "instruction_paths": [],
            "acceptance_checks": [],
            "content_policy": "content_light",
            "handoff_required": True,
            "unexpected": True,
        })

    with pytest.raises(ValidationError):
        MissionContextPacketReceipt.model_validate({
            "schema_version": "rig.mission_context_packet_receipt.v1",
            "packet_id": "packet",
            "mission_id": "mission",
            "mission_envelope_sha256": "sha256:" + "0" * 64,
            "packet_fingerprint": "sha256:" + "1" * 64,
            "packet_sha256": "sha256:" + "2" * 64,
            "index_backend": "python",
            "duckdb_cache_path": None,
            "source_ref_count": 0,
            "dirty_file_count": 0,
            "required_check_count": 0,
            "warning_count": 0,
            "blocker_count": 0,
            "created_at": "2026-05-14T12:30:00+00:00",
            "warnings": [],
            "blockers": [],
            "unexpected": True,
        })

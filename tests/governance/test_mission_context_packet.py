from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.governance.mission_context_packet import (
    MissionContextBlocker,
    MissionContextDirtyFileState,
    MissionContextPacket,
    MissionContextPacketReceipt,
    MissionContextRequiredCheck,
    MissionContextSourceRef,
    MissionContextWarning,
    MissionEnvelopeLink,
    build_mission_context_packet_receipt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKET_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.mission_context_packet.v1.schema.json"
)
RECEIPT_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.mission_context_packet_receipt.v1.schema.json"
)



pytestmark = [pytest.mark.integration]

def _packet(**overrides: object) -> MissionContextPacket:
    base: dict[str, object] = dict(
        packet_id="packet-2026-05-14-minimal-context",
        mission_id="mission-2026-05-14-context-packet-spine",
        title="Compile minimal mission context packet",
        created_at="2026-05-14T12:30:00+00:00",
        repo_root="/Users/user/Developer/GitHub/rig-relay",
        branch="main",
        head="61b46b8",
        allowed_paths=["docs/governance", "docs/schemas"],
        protected_paths=["/Users/user/.rig/relay"],
        instruction_paths=["AGENTS.md"],
        acceptance_checks=[
            "uv run pytest tests/governance/test_mission_context_packet.py -q"
        ],
        handoff_required=True,
        source_refs=[
            MissionContextSourceRef(
                path="docs/governance/mission-envelope.md",
                sha256="sha256:" + "0" * 64,
                kind="doc",
            )
        ],
        dirty_file_states=[
            MissionContextDirtyFileState(
                path="docs/governance/mission-envelope.md",
                status="modified",
                before_sha256="sha256:" + "1" * 64,
                after_sha256="sha256:" + "2" * 64,
                byte_count=1234,
                protected=False,
            )
        ],
        required_checks=[
            MissionContextRequiredCheck(
                name="schema",
                command="uv run python scripts/rig_relay_validate_schemas.py",
                required=True,
            )
        ],
        warnings=[MissionContextWarning(kind="inferred", message="mission-only mode")],
        blockers=[MissionContextBlocker(kind="none", message="none")],
        content_policy="content_light",
        mission_envelope=MissionEnvelopeLink(
            mission_id="mission-2026-05-14-context-packet-spine",
            fingerprint="sha256:" + "3" * 64,
        ),
    )
    return MissionContextPacket.model_validate({**base, **overrides})


def test_minimal_packet_validates() -> None:
    packet = _packet(
        mission_envelope=None,
        source_refs=[],
        dirty_file_states=[],
        required_checks=[],
        warnings=[],
        blockers=[],
    )
    assert packet.mission_id == "mission-2026-05-14-context-packet-spine"
    assert packet.mission_envelope is None


def test_packet_with_mission_envelope_linkage_validates() -> None:
    packet = _packet()
    assert packet.mission_envelope is not None
    assert packet.mission_envelope.mission_id == packet.mission_id


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MissionContextPacket.model_validate({
            **_packet().model_dump(mode="json"),
            "unexpected": True,
        })


def test_missing_required_fields_fail() -> None:
    payload = _packet().model_dump(mode="json")
    del payload["title"]
    with pytest.raises(ValidationError):
        MissionContextPacket.model_validate(payload)


def test_deterministic_serialization_is_stable() -> None:
    packet = _packet()
    assert packet.canonical_json() == packet.canonical_json()


def test_fingerprint_is_stable_for_identical_data() -> None:
    assert _packet().fingerprint == _packet().fingerprint


def test_fingerprint_changes_when_meaningful_fields_change() -> None:
    assert _packet().fingerprint != _packet(head="fedcba").fingerprint


def test_ordering_is_preserved() -> None:
    packet = _packet(
        allowed_paths=["a", "b", "c"],
        protected_paths=["x", "y"],
        instruction_paths=["AGENTS.md", "docs/governance/mission-envelope.md"],
        acceptance_checks=["check-1", "check-2"],
    )
    assert packet.allowed_paths == ["a", "b", "c"]
    assert packet.protected_paths == ["x", "y"]
    assert packet.instruction_paths == [
        "AGENTS.md",
        "docs/governance/mission-envelope.md",
    ]
    assert packet.acceptance_checks == ["check-1", "check-2"]


def test_forbidden_raw_content_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MissionContextPacket.model_validate({
            **_packet().model_dump(mode="json"),
            "raw_prompt_text": "secret",
        })


def test_receipt_validates() -> None:
    receipt = build_mission_context_packet_receipt(
        _packet(), created_at="2026-05-14T12:31:00+00:00"
    )
    assert isinstance(receipt, MissionContextPacketReceipt)
    assert receipt.packet_id == "packet-2026-05-14-minimal-context"


def test_schema_validates_packet() -> None:
    schema = json.loads(PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=_packet().model_dump(mode="json"), schema=schema)


def test_schema_validates_receipt() -> None:
    schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    receipt = build_mission_context_packet_receipt(
        _packet(), created_at="2026-05-14T12:31:00+00:00"
    )
    jsonschema.validate(instance=receipt.model_dump(mode="json"), schema=schema)

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.governance.mission_envelope import MissionEnvelope

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "rig.mission_envelope.v1.schema.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _sample_envelope(**overrides: object) -> MissionEnvelope:
    data = {
        "mission_id": "mission-2026-05-14-context-packet-spine",
        "title": "Wire minimal mission context packet spine",
        "created_at": "2026-05-14T12:00:00+00:00",
        "repo_root": "/Users/user/Developer/GitHub/rig-relay",
        "branch": "main",
        "head": "384e486",
        "dirty_summary": {
            "tracked_modified_count": 3,
            "untracked_count": 2,
            "protected_dirty_count": 1,
        },
        "allowed_paths": ["docs/", "rig_relay/"],
        "protected_paths": ["docs/governance/mission-envelope.md"],
        "instruction_paths": ["AGENTS.md"],
        "acceptance_checks": ["pytest -q tests/governance/test_mission_envelope.py"],
        "handoff_required": True,
    }
    data.update(overrides)
    return MissionEnvelope.model_validate(data)


def test_mission_only_mode_validates() -> None:
    env = _sample_envelope()
    assert env.adr_id is None
    assert env.sprint_id is None


def test_adr_and_sprint_do_not_change_mission_id() -> None:
    base = _sample_envelope()
    enriched = _sample_envelope(adr_id="adr-001", sprint_id="sprint-001")
    assert enriched.mission_id == base.mission_id
    assert enriched.adr_id == "adr-001"
    assert enriched.sprint_id == "sprint-001"


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        MissionEnvelope.model_validate({
            "mission_id": "m",
            "title": "t",
            "created_at": "2026-05-14T12:00:00+00:00",
            "repo_root": "/repo",
            "branch": "main",
            "head": "abc",
            "dirty_summary": {
                "tracked_modified_count": 0,
                "untracked_count": 0,
                "protected_dirty_count": 0,
            },
            "allowed_paths": [],
            "protected_paths": [],
            "instruction_paths": [],
            "acceptance_checks": [],
            "handoff_required": False,
            "extra": "nope",
        })


def test_missing_required_fields_fail_validation() -> None:
    with pytest.raises(ValidationError):
        MissionEnvelope.model_validate({
            "title": "t",
            "created_at": "2026-05-14T12:00:00+00:00",
            "repo_root": "/repo",
            "branch": "main",
            "head": "abc",
            "dirty_summary": {
                "tracked_modified_count": 0,
                "untracked_count": 0,
                "protected_dirty_count": 0,
            },
            "allowed_paths": [],
            "protected_paths": [],
            "instruction_paths": [],
            "acceptance_checks": [],
            "handoff_required": False,
        })


def test_serialization_is_stable_across_repeated_calls() -> None:
    env = _sample_envelope()
    assert env.canonical_json() == env.canonical_json()


def test_fingerprint_is_stable_for_identical_data() -> None:
    assert _sample_envelope().fingerprint == _sample_envelope().fingerprint


def test_fingerprint_changes_for_meaningful_changes() -> None:
    assert _sample_envelope().fingerprint != _sample_envelope(head="fedcba").fingerprint


def test_list_order_is_preserved() -> None:
    env = _sample_envelope(
        allowed_paths=["b", "a"],
        protected_paths=["p1", "p2"],
        instruction_paths=["i1", "i2"],
        acceptance_checks=["c1", "c2"],
    )
    dumped = env.model_dump(mode="json")
    assert dumped["allowed_paths"] == ["b", "a"]
    assert dumped["protected_paths"] == ["p1", "p2"]
    assert dumped["instruction_paths"] == ["i1", "i2"]
    assert dumped["acceptance_checks"] == ["c1", "c2"]


def test_schema_validates_model_dump() -> None:
    env = _sample_envelope()
    jsonschema.validate(instance=env.model_dump(mode="json"), schema=_schema())


def test_schema_rejects_unknown_fields() -> None:
    schema = _schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={
                "schema_version": "rig.mission_envelope.v1",
                "mission_id": "m",
                "title": "t",
                "created_at": "2026-05-14T12:00:00+00:00",
                "repo_root": "/repo",
                "branch": "main",
                "head": "abc",
                "dirty_summary": {
                    "tracked_modified_count": 0,
                    "untracked_count": 0,
                    "protected_dirty_count": 0,
                },
                "allowed_paths": [],
                "protected_paths": [],
                "instruction_paths": [],
                "acceptance_checks": [],
                "handoff_required": False,
                "extra": "nope",
            },
            schema=schema,
        )

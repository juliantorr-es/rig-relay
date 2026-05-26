"""A2A artifact model tests — C1 domain model validation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.protocols.a2a._artifacts import (
    A2AArtifact,
    A2AArtifactKind,
    A2AArtifactRef,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance: dict, name: str) -> None:
    jsonschema.validate(instance, _load(name))


class TestA2AArtifactKind:
    def test_all_kinds_are_strings(self):
        for kind in A2AArtifactKind:
            assert isinstance(kind.value, str)

    def test_proposed_scope_exists(self):
        assert A2AArtifactKind.PROPOSED_SCOPE.value == "proposed_scope"

    def test_refusal_evidence_exists(self):
        assert A2AArtifactKind.REFUSAL_EVIDENCE.value == "refusal_evidence"

    def test_discovered_risk_exists(self):
        assert A2AArtifactKind.DISCOVERED_RISK.value == "discovered_risk"

    def test_task_result_exists(self):
        assert A2AArtifactKind.TASK_RESULT.value == "task_result"


class TestA2AArtifact:
    def test_minimal_artifact(self):
        artifact = A2AArtifact(
            artifact_id="art-1", artifact_kind=A2AArtifactKind.PROPOSED_SCOPE
        )
        assert artifact.artifact_id == "art-1"
        assert artifact.content_light is True
        assert artifact.schema_version == "rig.relay.a2a.artifact.v1"

    def test_full_artifact(self):
        artifact = A2AArtifact(
            artifact_id="art-2",
            artifact_kind=A2AArtifactKind.TASK_RESULT,
            description="Task completed successfully",
            content_hash="c" * 64,
            byte_size=1024,
            content_type="application/json",
            task_id="task-1",
            trace_id="trace-1",
            producer_trust_tier="internal_governed_agent",
            required_capability="evidence_verification",
        )
        assert artifact.description == "Task completed successfully"
        assert artifact.byte_size == 1024
        assert artifact.task_id == "task-1"


class TestA2AArtifactRef:
    def test_minimal_ref(self):
        ref = A2AArtifactRef(
            artifact_id="art-1", artifact_kind=A2AArtifactKind.PROPOSED_SCOPE
        )
        d = ref.to_dict()
        assert d["artifact_id"] == "art-1"
        assert d["artifact_kind"] == "proposed_scope"

    def test_full_ref_to_dict(self):
        ref = A2AArtifactRef(
            artifact_id="art-2",
            artifact_kind=A2AArtifactKind.TASK_RESULT,
            content_hash="c" * 64,
            description="Result",
            generated_at="2026-01-01T00:00:00Z",
        )
        d = ref.to_dict()
        assert d["content_hash"] == "c" * 64
        assert d["description"] == "Result"
        assert "generated_at" in d

    def test_ref_is_lightweight(self):
        ref = A2AArtifactRef(
            artifact_id="art-1", artifact_kind=A2AArtifactKind.PROPOSED_SCOPE
        )
        d = ref.to_dict()
        assert "byte_size" not in d
        assert "content_type" not in d
        assert "task_id" not in d


class TestArtifactSchemaValidation:
    def test_valid_artifact_validates(self):
        artifact = {
            "schema_version": "rig.relay.a2a.artifact.v1",
            "artifact_id": "art-1",
            "artifact_kind": "proposed_scope",
            "description": "A proposal",
            "content_hash": "c" * 64,
            "byte_size": 1024,
            "content_type": "application/json",
            "task_id": "task-1",
            "trace_id": "trace-1",
            "producer_trust_tier": "internal_governed_agent",
            "required_capability": "discovery_only",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        _v(artifact, "rig.relay.a2a.artifact.v1.schema.json")

    def test_artifact_rejects_invalid_kind(self):
        schema = _load("rig.relay.a2a.artifact.v1.schema.json")
        artifact = {
            "schema_version": "rig.relay.a2a.artifact.v1",
            "artifact_id": "art-1",
            "artifact_kind": "full_source_code_dump",
            "content_light": True,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(artifact, schema)

    def test_artifact_requires_content_light(self):
        schema = _load("rig.relay.a2a.artifact.v1.schema.json")
        artifact = {
            "schema_version": "rig.relay.a2a.artifact.v1",
            "artifact_id": "art-1",
            "artifact_kind": "proposed_scope",
            "content_light": False,
            "generated_at": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(artifact, schema)

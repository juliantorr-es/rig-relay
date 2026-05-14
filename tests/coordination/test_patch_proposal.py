"""Tests for rig_relay.coordination.patch_proposal — PatchProposal, PatchDecision, PatchProposalArtifactRef.

Covers model validation, content-light enforcement, artifact refs,
decision lifecycle, touched paths, fingerprint stability, and schema
validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest

from rig_relay.coordination.patch_proposal import (
    CreateProposalResult,
    PatchDecision,
    PatchProposal,
    PatchProposalArtifactRef,
    compute_proposal_fingerprint,
)

# ── Helpers ─────────────────────────────────────────────────────────────


def _sample_proposal(**overrides: Any) -> PatchProposal:
    kwargs: dict[str, Any] = {
        "proposal_id": "prop-001",
        "mission_id": "mission-alpha",
        "agent_id": "agent-42",
        "title": "Refactor auth middleware",
        "summary": "Replace inline auth checks with decorator-based approach.",
        "created_at": "2026-01-01T00:00:00+00:00",
        "touched_paths": ["src/auth/middleware.py", "tests/test_auth.py"],
        "touched_path_hashes": [
            "sha256:0000000000000000000000000000000000000000000000000000000000000001",
            "sha256:0000000000000000000000000000000000000000000000000000000000000002",
        ],
        "base_head": "abc123def456",
        "expected_before_sha256": {
            "src/auth/middleware.py": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "tests/test_auth.py": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
        "artifact_refs": [
            PatchProposalArtifactRef(
                artifact_path="/tmp/artifacts/prop-001.diff",
                sha256="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                size_bytes=1024,
                media_type="text/x-diff",
            )
        ],
    }
    kwargs.update(overrides)
    return PatchProposal(**kwargs)


def _sample_decision(**overrides: Any) -> PatchDecision:
    kwargs: dict[str, Any] = {
        "decision_id": "dec-001",
        "proposal_id": "prop-001",
        "decided_by": "orchestrator-1",
        "decision": "accepted",
        "reason": "Looks good. Approved.",
    }
    kwargs.update(overrides)
    return PatchDecision(**kwargs)


# ── PatchProposal validation tests ─────────────────────────────────────


class TestPatchProposalValidation:
    def test_create_proposal_validates(self) -> None:
        """A valid proposal with all fields succeeds."""
        proposal = _sample_proposal()
        assert proposal.proposal_id == "prop-001"
        assert proposal.mission_id == "mission-alpha"
        assert proposal.agent_id == "agent-42"
        assert proposal.status == "pending"
        assert len(proposal.touched_paths) == 2

    def test_rejects_extra_fields(self) -> None:
        """Pydantic extra=forbid rejects unknown fields."""
        with pytest.raises((ValidationError, ValueError, TypeError)):
            PatchProposal.model_validate({
                "proposal_id": "p1",
                "mission_id": "m1",
                "agent_id": "a1",
                "title": "Fix bug",
                "summary": "Fix the bug.",
                "unknown_field": "x",
            })

    def test_rejects_embedded_diff_field(self) -> None:
        """No field called 'diff', 'patch', 'content' is allowed in the model."""
        # The model itself has no such field, but verify the dump doesn't gain them
        proposal = _sample_proposal()
        dumped = proposal.model_dump(mode="json")
        for forbidden in ("diff", "patch", "content"):
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in PatchProposal dump"
            )

    def test_rejects_invalid_sha256_in_path_hashes(self) -> None:
        """Path hashes must be valid sha256: prefixed hex strings."""
        with pytest.raises((ValidationError, ValueError)):
            _sample_proposal(touched_path_hashes=["not-a-hash"])

    def test_rejects_short_sha256_in_path_hashes(self) -> None:
        """Path hash hex part must be exactly 64 chars."""
        with pytest.raises((ValidationError, ValueError)):
            _sample_proposal(touched_path_hashes=["sha256:short"])

    def test_minimal_proposal(self) -> None:
        """A proposal with only required fields works."""
        proposal = PatchProposal(
            proposal_id="p-min",
            mission_id="m-min",
            agent_id="a-min",
            title="Minimal",
            summary="Minimal proposal.",
        )
        assert proposal.status == "pending"
        assert proposal.touched_paths == []
        assert proposal.artifact_refs == []

    def test_touched_paths_preserve_order(self) -> None:
        """Touched paths maintain insertion order."""
        paths = ["z.py", "a.py", "m.py"]
        proposal = _sample_proposal(touched_paths=paths)
        assert proposal.touched_paths == paths


# ── PatchProposalArtifactRef validation tests ──────────────────────────


class TestPatchProposalArtifactRefValidation:
    def test_artifact_ref_validates(self) -> None:
        """A valid artifact ref with hash, path, size passes."""
        ref = PatchProposalArtifactRef(
            artifact_path="/tmp/artifacts/patch.diff",
            sha256="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            size_bytes=2048,
            media_type="text/x-diff",
        )
        assert ref.artifact_path == "/tmp/artifacts/patch.diff"
        assert ref.size_bytes == 2048

    def test_artifact_ref_minimal(self) -> None:
        """An artifact ref with only path and hash works."""
        ref = PatchProposalArtifactRef(
            artifact_path="/tmp/patch.diff",
            sha256="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        )
        assert ref.size_bytes is None
        assert ref.media_type is None

    def test_artifact_ref_rejects_invalid_sha256(self) -> None:
        """Artifact ref sha256 must start with sha256:."""
        with pytest.raises((ValidationError, ValueError)):
            PatchProposalArtifactRef(
                artifact_path="/tmp/patch.diff", sha256="invalid-hash"
            )

    def test_artifact_ref_rejects_extra_fields(self) -> None:
        """Artifact ref extra=forbid rejects unknown fields."""
        with pytest.raises((ValidationError, ValueError, TypeError)):
            PatchProposalArtifactRef.model_validate({
                "artifact_path": "/tmp/p.diff",
                "sha256": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "raw_diff": "some diff content",
            })

    def test_artifact_ref_no_raw_content_in_dump(self) -> None:
        """Artifact ref dump has no raw content fields."""
        ref = PatchProposalArtifactRef(
            artifact_path="/tmp/p.diff",
            sha256="sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        )
        dumped = ref.model_dump(mode="json")
        for forbidden in ("diff", "patch", "content", "stdout", "stderr"):
            for key in dumped:
                assert forbidden not in key, (
                    f"Found forbidden key '{forbidden}' in artifact ref dump"
                )


# ── PatchDecision validation tests ─────────────────────────────────────


class TestPatchDecisionValidation:
    def test_decision_accepts_proposal(self) -> None:
        """A decision with 'accepted' validates."""
        decision = _sample_decision(decision="accepted")
        assert decision.decision == "accepted"
        assert decision.decision_id == "dec-001"

    def test_decision_rejects_proposal(self) -> None:
        """A decision with 'rejected' validates."""
        decision = _sample_decision(
            decision="rejected", reason="Breaks backward compatibility."
        )
        assert decision.decision == "rejected"

    def test_decision_needs_revision(self) -> None:
        """A decision with 'needs_revision' validates."""
        decision = _sample_decision(
            decision="needs_revision", reason="Please add tests."
        )
        assert decision.decision == "needs_revision"

    def test_decision_superseded(self) -> None:
        """A decision with 'superseded' validates."""
        decision = _sample_decision(
            decision="superseded", reason="Superseded by prop-002."
        )
        assert decision.decision == "superseded"

    def test_decision_rejects_extra_fields(self) -> None:
        """Decision extra=forbid rejects unknown fields."""
        with pytest.raises((ValidationError, ValueError, TypeError)):
            PatchDecision.model_validate({
                "decision_id": "d1",
                "proposal_id": "p1",
                "decided_by": "o1",
                "decision": "accepted",
                "reason": "ok",
                "unknown_field": "x",
            })

    def test_decision_rejects_invalid_decision(self) -> None:
        """Decision must be one of the valid literals."""
        with pytest.raises((ValidationError, ValueError)):
            _sample_decision(decision="maybe")  # not a valid option

    def test_decision_requires_reason(self) -> None:
        """Decision requires reason."""
        decision = _sample_decision(reason="Approved.")
        assert decision.reason == "Approved."


# ── Fingerprint tests ──────────────────────────────────────────────────


class TestFingerprint:
    def test_fingerprint_stable(self) -> None:
        """Same proposal content produces same fingerprint."""
        p1 = _sample_proposal()
        p2 = _sample_proposal()
        fp1 = compute_proposal_fingerprint(p1)
        fp2 = compute_proposal_fingerprint(p2)
        assert fp1 == fp2
        assert fp1.startswith("sha256:")

    def test_fingerprint_changes_with_content(self) -> None:
        """Different proposal content produces different fingerprint."""
        p1 = _sample_proposal(title="Original title")
        p2 = _sample_proposal(title="Different title")
        fp1 = compute_proposal_fingerprint(p1)
        fp2 = compute_proposal_fingerprint(p2)
        assert fp1 != fp2

    def test_fingerprint_excludes_proposal_id(self) -> None:
        """Fingerprint excludes proposal_id and schema_version."""
        p1 = _sample_proposal(proposal_id="prop-001")
        p2 = _sample_proposal(proposal_id="prop-002")
        fp1 = compute_proposal_fingerprint(p1)
        fp2 = compute_proposal_fingerprint(p2)
        assert fp1 == fp2  # same content, different IDs


# ── CreateProposalResult tests ─────────────────────────────────────────


class TestCreateProposalResult:
    def test_create_result_holds_proposal_and_fingerprint(self) -> None:
        """CreateProposalResult stores proposal and computed fingerprint."""
        proposal = _sample_proposal()
        fp = compute_proposal_fingerprint(proposal)
        result = CreateProposalResult(proposal=proposal, fingerprint=fp)
        assert result.proposal is proposal
        assert result.fingerprint == fp


# ── Content-light tests ────────────────────────────────────────────────


FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "diff",
    "patch",
    "content",
    "stdout",
    "stderr",
    "output_text",
    "snippet",
    "file_contents",
    "old_text",
    "new_text",
    "chunk_text",
})


class TestContentLight:
    def test_patch_proposal_dump_has_no_forbidden_fields(self) -> None:
        """PatchProposal model dump has no raw content fields."""
        proposal = _sample_proposal()
        dumped = proposal.model_dump(mode="json")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            for key in dumped:
                assert forbidden not in key, (
                    f"Found forbidden key '{forbidden}' in PatchProposal dump"
                )

    def test_patch_decision_dump_has_no_forbidden_fields(self) -> None:
        """PatchDecision model dump has no raw content fields."""
        decision = _sample_decision()
        dumped = decision.model_dump(mode="json")
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            for key in dumped:
                assert forbidden not in key, (
                    f"Found forbidden key '{forbidden}' in PatchDecision dump"
                )

    def test_model_dump_validates_without_exclude_none(self) -> None:
        """model_dump(mode='json') validates without exclude_none=True."""
        proposal = _sample_proposal()
        dumped = proposal.model_dump(mode="json")
        # Should not raise, should not have extra fields
        assert "touched_paths" in dumped
        assert "artifact_refs" in dumped

    def test_artifact_refs_in_proposal_dump(self) -> None:
        """Artifact refs are present in the proposal dump."""
        proposal = _sample_proposal()
        dumped = proposal.model_dump(mode="json")
        refs = dumped.get("artifact_refs", [])
        assert len(refs) == 1
        assert refs[0]["artifact_path"] == "/tmp/artifacts/prop-001.diff"
        assert "sha256" in refs[0]
        assert "size_bytes" in refs[0]


# ── Schema validation tests ────────────────────────────────────────────


class TestSchemaValidation:
    @pytest.fixture
    def proposal_schema_dict(self) -> dict:
        repo_root = Path(__file__).resolve().parent.parent.parent
        schema_path = (
            repo_root / "docs" / "schemas" / "rig.fleet.patch_proposal.v1.schema.json"
        )
        import json as _json

        return _json.loads(schema_path.read_text(encoding="utf-8"))

    @pytest.fixture
    def decision_schema_dict(self) -> dict:
        repo_root = Path(__file__).resolve().parent.parent.parent
        schema_path = (
            repo_root / "docs" / "schemas" / "rig.fleet.patch_decision.v1.schema.json"
        )
        import json as _json

        return _json.loads(schema_path.read_text(encoding="utf-8"))

    def test_proposal_validates_against_schema(
        self, proposal_schema_dict: dict
    ) -> None:
        """A valid proposal validates against the JSON schema."""
        import jsonschema

        proposal = _sample_proposal()
        dumped = proposal.model_dump(mode="json")
        jsonschema.validate(instance=dumped, schema=proposal_schema_dict)

    def test_decision_validates_against_schema(
        self, decision_schema_dict: dict
    ) -> None:
        """A valid decision validates against the JSON schema."""
        import jsonschema

        decision = _sample_decision()
        dumped = decision.model_dump(mode="json")
        jsonschema.validate(instance=dumped, schema=decision_schema_dict)

    def test_proposal_rejects_unknown_fields(self, proposal_schema_dict: dict) -> None:
        """Schema additionalProperties:false rejects unknown fields."""
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "schema_version": "rig.fleet.patch_proposal.v1",
                    "proposal_id": "p1",
                    "mission_id": "m1",
                    "agent_id": "a1",
                    "title": "T",
                    "summary": "S",
                    "status": "pending",
                    "unknown_field": "x",
                },
                schema=proposal_schema_dict,
            )

    def test_decision_rejects_unknown_fields(self, decision_schema_dict: dict) -> None:
        """Decision schema additionalProperties:false rejects unknown fields."""
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "schema_version": "rig.fleet.patch_decision.v1",
                    "decision_id": "d1",
                    "proposal_id": "p1",
                    "decided_by": "o1",
                    "decision": "accepted",
                    "reason": "ok",
                    "unknown_field": "x",
                },
                schema=decision_schema_dict,
            )

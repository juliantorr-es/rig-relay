"""ContextAssemblyPlan contract spine tests."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from rig_relay.context.assembly_plan import (
    CacheTier,
    CandidateKind,
    CandidateRelation,
    CandidateSource,
    ContextAssemblyPlan,
    ContextBudgetLedger,
    ContextCandidate,
    ContextOmission,
    ContextSelection,
    IncludeMode,
    RiskFlag,
    TrustTier,
    _build_candidate_id,
)


class TestContextCandidate:
    def test_candidate_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ContextCandidate.model_validate({
                "path": "x",
                "kind": "source",
                "source": "repo_map",
                "relation": "direct",
                "estimated_tokens": 10,
                "extra": "no",
            })

    def test_candidate_id_deterministic(self) -> None:
        a = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        b = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        assert a.candidate_id == b.candidate_id

    def test_candidate_id_changes_with_path(self) -> None:
        a = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        b = ContextCandidate(
            path="src/b.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        assert a.candidate_id != b.candidate_id

    def test_candidate_id_changes_with_kind(self) -> None:
        a = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        b = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.test,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        assert a.candidate_id != b.candidate_id

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextCandidate(
                path="x",
                kind=CandidateKind.source,
                source=CandidateSource.repo_map,
                relation=CandidateRelation.direct,
                estimated_tokens=-1,
            )

    def test_explicit_candidate_id_respected(self) -> None:
        c = ContextCandidate(
            candidate_id="my-custom-id",
            path="x",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        assert c.candidate_id == "my-custom-id"

    def test_json_roundtrip(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=100,
            priority=5,
            risk_flags=[RiskFlag.dirty],
            trust_tier=TrustTier.repo_content,
            cache_tier=CacheTier.semi_stable,
        )
        d = c.model_dump(mode="json")
        assert d["kind"] == "source"
        parsed = ContextCandidate.model_validate(json.loads(json.dumps(d)))
        assert parsed.candidate_id == c.candidate_id

    def test_no_raw_content_fields(self) -> None:
        """Source guard: raw content field names are not in the model."""
        field_names = set(ContextCandidate.model_fields.keys())
        forbidden = {
            "content",
            "raw_text",
            "stdout",
            "stderr",
            "env",
            "cwd",
            "token",
            "output",
            "file_contents",
            "snippet",
            "prompt",
        }
        assert not (field_names & forbidden), (
            f"Forbidden fields: {field_names & forbidden}"
        )


class TestContextSelection:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ContextSelection.model_validate({
                "candidate_id": "x",
                "selected_tokens": 10,
                "include_mode": "full",
                "extra": "no",
            })


class TestContextOmission:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ContextOmission.model_validate({
                "candidate_id": "x",
                "omission_reason": "budget_exceeded",
                "estimated_tokens": 10,
                "extra": "no",
            })


class TestContextAssemblyPlan:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ContextAssemblyPlan.model_validate({"extra": "no"})

    def test_plan_hash_deterministic(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        s = ContextSelection(
            candidate_id=c.candidate_id,
            selected_tokens=10,
            include_mode=IncludeMode.full,
        )
        plan1 = ContextAssemblyPlan(candidates=[c], selections=[s])
        plan2 = ContextAssemblyPlan(candidates=[c], selections=[s])
        assert plan1.plan_sha256 == plan2.plan_sha256

    def test_generated_at_excluded_from_hash(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        s = ContextSelection(
            candidate_id=c.candidate_id,
            selected_tokens=10,
            include_mode=IncludeMode.full,
        )
        plan1 = ContextAssemblyPlan(candidates=[c], selections=[s])
        plan1.generated_at = "2026-01-01T00:00:00Z"
        plan2 = ContextAssemblyPlan(candidates=[c], selections=[s])
        plan2.generated_at = "2026-06-01T00:00:00Z"
        assert plan1.plan_sha256 == plan2.plan_sha256, (
            "Plan hash must be independent of generated_at"
        )

    def test_selection_hash_deterministic(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        s = ContextSelection(
            candidate_id=c.candidate_id,
            selected_tokens=10,
            include_mode=IncludeMode.full,
        )
        plan1 = ContextAssemblyPlan(candidates=[c], selections=[s])
        plan2 = ContextAssemblyPlan(candidates=[c], selections=[s])
        assert plan1.selection_sha256 == plan2.selection_sha256

    def test_json_roundtrip(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        s = ContextSelection(
            candidate_id=c.candidate_id,
            selected_tokens=10,
            include_mode=IncludeMode.full,
        )
        plan = ContextAssemblyPlan(candidates=[c], selections=[s])
        hash_before = plan.plan_sha256
        d = plan.model_dump(mode="json")
        d.pop("plan_sha256", None)
        d.pop("selection_sha256", None)
        parsed = ContextAssemblyPlan.model_validate(d)
        assert parsed.plan_sha256 == hash_before

    def test_plan_id_derives_from_hash(self) -> None:
        c = ContextCandidate(
            path="src/a.py",
            kind=CandidateKind.source,
            source=CandidateSource.repo_map,
            relation=CandidateRelation.direct,
            estimated_tokens=10,
        )
        plan = ContextAssemblyPlan(candidates=[c])
        assert plan.plan_id
        assert plan.plan_id in plan.plan_sha256

    def test_no_raw_content_fields_on_plan(self) -> None:
        field_names = set(ContextAssemblyPlan.model_fields.keys())
        forbidden = {
            "content",
            "raw_text",
            "stdout",
            "stderr",
            "env",
            "cwd",
            "token",
            "output",
            "file_contents",
            "snippet",
            "prompt",
        }
        assert not (field_names & forbidden), (
            f"Forbidden fields: {field_names & forbidden}"
        )


class TestCanonicalHash:
    def test_deterministic_candidate_id_across_python_versions(self) -> None:
        """Ids are sha256-based, stable across Python versions."""
        id1 = _build_candidate_id("x", "source", "repo_map", "direct")
        id2 = _build_candidate_id("x", "source", "repo_map", "direct")
        assert id1 == id2
        assert id1.startswith("sha256:")


class TestBudgetLedger:
    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextBudgetLedger(requested_tokens=-1, used_tokens=0, remaining_tokens=0)

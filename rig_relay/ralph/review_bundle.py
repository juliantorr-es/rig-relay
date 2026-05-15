"""Ralph review bundle — sealed evidence package from a completed lane.

Collects lane state, commits, changed files, validation results,
and adoption recommendation into a deterministic reviewable bundle.
Content-light: hashes for large artifacts, inline summaries for small ones.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

BUNDLE_VERSION = "rig.ralph_review_bundle.v1"


class RalphReviewBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = BUNDLE_VERSION
    bundle_id: str = ""
    lane_id: str = ""
    branch_name: str = ""
    base_head: str = ""
    head_sha: str = ""
    commit_shas: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
    why: str = ""
    evidence_refs: list[dict[str, str]] = Field(default_factory=list)
    validation_results: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    adoption_recommendation: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    bundle_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"bundle_sha256", "created_at"},
            exclude_none=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_review_bundle(
    lane: Any,
    execution_result: dict[str, Any] | None = None,
    source_findings: list[str] | None = None,
    objective: str = "",
) -> RalphReviewBundle:
    bundle = RalphReviewBundle(
        bundle_id=f"bundle_{lane.lane_id}",
        lane_id=lane.lane_id,
        branch_name=getattr(lane, "branch_name", ""),
        base_head=getattr(lane, "base_head", ""),
        head_sha=getattr(lane, "latest_commit_sha", "") or "",
        commit_shas=list((execution_result or {}).get("commit_shas", [])),
        changed_files=list((execution_result or {}).get("changed_files", [])),
        summary=f"Ralph lane completed: {objective[:120]}" if objective else "Ralph lane completed",
        why=f"Triggered by findings: {', '.join(source_findings or [])[:120]}" if source_findings else "",
        evidence_refs=[
            {"kind": "finding", "id": fid} for fid in (source_findings or [])
        ],
        validation_results=list((execution_result or {}).get("validation_results", [])),
        adoption_recommendation={
            "target_kind": "user_review",
            "confidence": "medium",
            "reason": "Ralph completed lane work — review recommended",
        },
    )
    bundle.bundle_sha256 = bundle.compute_sha256()
    return bundle


class ReviewSessionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ui.ralph_review_session.v1"
    session_id: str = ""
    pending_lane_count: int = 0
    bundles: list[dict[str, Any]] = Field(default_factory=list)
    adoption_proposals: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    execution_enabled: bool = False
    merge_enabled: bool = False
    available_actions: list[dict[str, str | bool]] = Field(default_factory=lambda: [
        {"action": "review_accept", "label": "Accept for review", "requires_confirmation": True},
        {"action": "review_reject", "label": "Reject", "requires_confirmation": True},
        {"action": "review_defer", "label": "Defer", "requires_confirmation": False},
    ])


def build_review_projection(
    bundles: list[Any],
    proposals: list[Any] | None = None,
) -> ReviewSessionProjection:
    return ReviewSessionProjection(
        session_id=f"review_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        pending_lane_count=len(bundles),
        bundles=[b.model_dump(mode="json") if hasattr(b, 'model_dump') else b for b in bundles],
        adoption_proposals=[p.model_dump(mode="json") if hasattr(p, 'model_dump') else p for p in (proposals or [])],
        summary=f"{len(bundles)} completed Ralph lanes awaiting review",
        execution_enabled=False,
        merge_enabled=False,
    )


__all__ = [
    "RalphReviewBundle",
    "ReviewSessionProjection",
    "build_review_bundle",
    "build_review_projection",
]

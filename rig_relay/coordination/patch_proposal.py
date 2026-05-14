"""PatchProposal, PatchProposalArtifactRef, PatchDecision — Fleet Patch Proposal Workflow Phase 0.

Defines the artifact models for the proposal workflow:
- Agents submit PatchProposals describing intended mutations.
- An orchestrator reviews and issues PatchDecisions.
- Apply logic is deferred (orchestrator-only, future phase).

Content boundary:
- PatchProposal metadata is content-light (no raw diffs/patches/content).
- Diffs are referenced via PatchProposalArtifactRef (hash, path, size, media_type).
- Raw diff content is never embedded in coordination events or proposal models.

Design principle (fleet rule 1):
Agents propose; orchestrator disposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Constants ─────────────────────────────────────────────────────────────

_SHA256_HEX_LEN = 64
"""Number of hex characters in a SHA256 digest."""

_SCHEMA_VERSION_PROPOSAL = "rig.fleet.patch_proposal.v1"
_SCHEMA_VERSION_DECISION = "rig.fleet.patch_decision.v1"
_SCHEMA_VERSION_ARTIFACT_REF = "rig.fleet.patch_proposal_artifact_ref.v1"


# ── Artifact reference (content-light boundary) ────────────────────────


class PatchProposalArtifactRef(BaseModel):
    """Reference to an external diff/patch artifact.

    Content-light: never contains raw diff/patch/content text.
    Only metadata: hash, path, size, and media type.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_ARTIFACT_REF
    artifact_path: str
    sha256: str
    size_bytes: int | None = None
    media_type: str | None = None

    @field_validator("sha256")
    @classmethod
    def _sha256_must_be_valid(cls, v: str) -> str:
        if not v.startswith("sha256:"):
            raise ValueError("sha256 must start with 'sha256:'")
        hex_part = v[7:]
        if len(hex_part) != _SHA256_HEX_LEN:
            raise ValueError(
                f"sha256 hex part must be {_SHA256_HEX_LEN} chars, got {len(hex_part)}"
            )
        int(hex_part, 16)  # validates hex
        return v


# ── Patch proposal ─────────────────────────────────────────────────────


class PatchProposal(BaseModel):
    """A proposed mutation to one or more files.

    Content-light: no embedded diffs, patches, file contents, or secrets.
    Diffs are referenced via artifact_refs only.

    An agent creates a PatchProposal and submits it. The orchestrator
    reviews it and issues a PatchDecision. Patch application is deferred
    to a future phase.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_PROPOSAL
    proposal_id: str
    mission_id: str
    agent_id: str
    title: str
    summary: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: Literal[
        "pending", "accepted", "rejected", "needs_revision", "superseded"
    ] = "pending"

    # ── File-level metadata ─────────────────────────────────────────
    touched_paths: list[str] = Field(default_factory=list)
    touched_path_hashes: list[str] = Field(default_factory=list)
    base_head: str | None = None
    expected_before_sha256: dict[str, str] = Field(default_factory=dict)

    # ── Artifact references (content-light boundary) ────────────────
    artifact_refs: list[PatchProposalArtifactRef] = Field(default_factory=list)

    @field_validator("touched_path_hashes")
    @classmethod
    def _hashes_must_be_sha256(cls, v: list[str]) -> list[str]:
        for h in v:
            if not h.startswith("sha256:"):
                raise ValueError(f"Path hash must start with 'sha256:', got {h!r}")
            hex_part = h[7:]
            if len(hex_part) != _SHA256_HEX_LEN:
                raise ValueError(
                    f"Path hash hex part must be {_SHA256_HEX_LEN} chars, "
                    f"got {len(hex_part)}"
                )
            int(hex_part, 16)
        return v


# ── Patch decision ─────────────────────────────────────────────────────


class PatchDecision(BaseModel):
    """The orchestrator's decision on a PatchProposal.

    Only the orchestrator creates PatchDecisions.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_DECISION
    decision_id: str
    proposal_id: str
    decided_by: str
    decision: Literal["accepted", "rejected", "needs_revision", "superseded"]
    reason: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ── Stable fingerprint helper ──────────────────────────────────────────


def compute_proposal_fingerprint(proposal: PatchProposal) -> str:
    """Compute a deterministic SHA256 fingerprint for a PatchProposal.

    Uses sorted canonical JSON of all fields except proposal_id and
    schema_version. Stable across serialization.
    """
    excluded = {"proposal_id", "schema_version"}
    raw = proposal.model_dump(mode="json", exclude=excluded)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Dataclass for create-proposal return ───────────────────────────────


@dataclass
class CreateProposalResult:
    """Result of creating a PatchProposal.

    Returns the created proposal and its fingerprint for verification.
    """

    proposal: PatchProposal
    fingerprint: str


__all__ = [
    "CreateProposalResult",
    "PatchDecision",
    "PatchProposal",
    "PatchProposalArtifactRef",
    "compute_proposal_fingerprint",
]

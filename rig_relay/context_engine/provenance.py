"""Provenance and classification model for the context engine.

Defines the four-category information model:
  - Source-derived structural facts (from parsers/indexers)
  - Evidence-derived operational facts (from K0 investigations)
  - Generated semantic interpretations (proposed, not fact)
  - Developer-approved public content (explicitly approved)

Every fact or claim carries provenance, approval status, and privacy disposition.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FactOrigin(StrEnum):
    SOURCE_DERIVED = "source_derived"
    EVIDENCE_DERIVED = "evidence_derived"
    GENERATED = "generated"
    APPROVED = "approved"


class ApprovalStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PrivacyDisposition(StrEnum):
    PUBLIC_SAFE = "public_safe"
    INTERNAL_ONLY = "internal_only"
    REDACTED = "redacted"
    WITHHELD = "withheld"


class SourceDerivedFact(BaseModel):
    """A structural fact derived deterministically from repository content.

    Provenance traces back to a specific source file and extraction method.
    Never model-asserted.
    """

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    category: str = Field(
        description="language, framework, build_system, test_framework, etc."
    )
    value: str
    source_path: str = Field(description="Relative path to source file.")
    source_kind: str = Field(
        description="pyproject.toml, package.json, Cargo.toml, etc."
    )
    extraction_method: str = Field(
        description="parser, manifest_reader, regex, directory_scan, etc."
    )
    confidence: str = Field(default="high", description="high, medium, or low")
    provenance: FactOrigin = FactOrigin.SOURCE_DERIVED
    privacy_disposition: PrivacyDisposition = PrivacyDisposition.INTERNAL_ONLY


class EvidenceDerivedFact(BaseModel):
    """A fact derived from K0 investigation or proposal evidence.

    References investigation evidence by hash. Available only when
    K0 has released investigation evidence through a typed fixture
    or live boundary.
    """

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    category: str
    value: str
    evidence_ref: str = Field(description="K0 investigation evidence hash reference.")
    confidence: str = Field(default="medium", description="high, medium, or low")
    provenance: FactOrigin = FactOrigin.EVIDENCE_DERIVED
    privacy_disposition: PrivacyDisposition = PrivacyDisposition.INTERNAL_ONLY


class GeneratedClaim(BaseModel):
    """A semantic interpretation generated from structural or evidence facts.

    Explicitly marked as proposed — not fact, not approved.
    Requires developer approval before becoming authoritative public content.
    Must carry basis_facts for traceability.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    category: str = Field(
        description="project_description, capability_label, page_section_suggestion, etc."
    )
    narrative: str
    basis_facts: list[str] = Field(
        default_factory=list, description="fact_ids this claim is based on."
    )
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED
    provenance: FactOrigin = FactOrigin.GENERATED
    privacy_disposition: PrivacyDisposition = PrivacyDisposition.PUBLIC_SAFE


class ApprovedContent(BaseModel):
    """Content that has been explicitly approved by the developer.

    Only this category may become authoritative public-page material.
    Originates from proposed claims that passed developer review.
    """

    model_config = ConfigDict(extra="forbid")

    content_id: str
    category: str
    value: str
    approved_at: datetime
    provenance: FactOrigin = FactOrigin.APPROVED
    privacy_disposition: PrivacyDisposition = PrivacyDisposition.PUBLIC_SAFE


__all__ = [
    "ApprovalStatus",
    "ApprovedContent",
    "EvidenceDerivedFact",
    "FactOrigin",
    "GeneratedClaim",
    "PrivacyDisposition",
    "SourceDerivedFact",
]

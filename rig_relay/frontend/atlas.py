"""Frontend Systems Atlas — transcript-grounded design principle ingestion.

The Atlas accepts Pixelgrid UI transcripts (or any design-research corpus)
and extracts structured, traceable frontend design principles. Each principle
carries provenance, visual/interaction grammar implications, and explicit
applicability to Rig Relay's three frontend surfaces.

No principle is promoted to canonical product truth until implemented and proven.
Every extracted claim must remain traceable to its transcript source.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SurfaceTarget(StrEnum):
    GRIDLINE = "gridline"
    PROJECT_PAGE = "project_page"
    PORTFOLIO_SITE = "portfolio_site"


class ApplicabilityClass(StrEnum):
    NOW = "now"
    LATER = "later"
    REFERENCE = "reference"


class PrincipleKind(StrEnum):
    VISUAL_GRAMMAR = "visual_grammar"
    INTERACTION_GRAMMAR = "interaction_grammar"
    COMPONENT_PRIMITIVE = "component_primitive"
    TOKEN_SYSTEM = "token_system"
    LAYOUT_STRATEGY = "layout_strategy"
    TYPOGRAPHY_RHYTHM = "typography_rhythm"
    MOTION_PATTERN = "motion_pattern"
    ACCESSIBILITY_RULE = "accessibility_rule"
    INFORMATION_ARCHITECTURE = "information_architecture"
    CONTENT_PRESENTATION = "content_presentation"
    NATIVE_SURFACE = "native_surface"


class VisualGrammarImplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spacing: list[str] = Field(default_factory=list)
    typography: list[str] = Field(default_factory=list)
    hierarchy: list[str] = Field(default_factory=list)
    grid: list[str] = Field(default_factory=list)
    density: list[str] = Field(default_factory=list)
    surface_layering: list[str] = Field(default_factory=list)
    iconography: list[str] = Field(default_factory=list)
    color_semantics: list[str] = Field(default_factory=list)


class InteractionGrammarImplication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progressive_disclosure: list[str] = Field(default_factory=list)
    selection: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    navigation: list[str] = Field(default_factory=list)
    contextual_actions: list[str] = Field(default_factory=list)
    loading_states: list[str] = Field(default_factory=list)
    error_states: list[str] = Field(default_factory=list)
    refusal_states: list[str] = Field(default_factory=list)
    motion_interaction: list[str] = Field(default_factory=list)


class SurfaceApplicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: SurfaceTarget
    applicable: bool = False
    rationale: str = ""
    tension_notes: list[str] = Field(default_factory=list)
    implementation_class: ApplicabilityClass = ApplicabilityClass.REFERENCE


class SourceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal[
        "youtube_transcript",
        "design_doc",
        "reference_implementation",
        "research_paper",
        "manual_audit",
        "user_feedback",
    ]
    channel_or_author: str = "Pixelgrid UI"
    video_id: str = ""
    video_title: str | None = None
    transcript_file: str = ""
    transcript_sha256: str = ""
    retrieval_date: str = ""


class TranscriptDigestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceIdentity
    raw_transcript_text: str
    transcript_character_count: int


class AtlasPrinciple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principle_id: str
    source: SourceIdentity
    principle_kind: PrincipleKind
    principle_statement: str
    visual_grammar: VisualGrammarImplication = Field(
        default_factory=VisualGrammarImplication
    )
    interaction_grammar: InteractionGrammarImplication = Field(
        default_factory=InteractionGrammarImplication
    )
    component_implications: list[str] = Field(default_factory=list)
    token_implications: list[str] = Field(default_factory=list)
    projection_implications: list[str] = Field(default_factory=list)
    schema_implications: list[str] = Field(default_factory=list)
    surface_applicability: list[SurfaceApplicability] = Field(default_factory=list)
    tension_with_rig_relay_requirements: list[str] = Field(default_factory=list)
    extracted_at: datetime | None = None
    principle_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.source.source_kind}:{self.source.video_id}:"
            f"{self.principle_kind.value}:{self.principle_statement}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"

    def is_applicable_to(self, target: SurfaceTarget) -> bool:
        for s in self.surface_applicability:
            if s.target == target and s.applicable:
                return True
        return False


class AtlasDigestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.frontend_atlas_digest.v1"
    digest_id: str
    input_source: SourceIdentity
    principles_extracted: list[AtlasPrinciple] = Field(default_factory=list)
    extraction_note: str = ""
    content_light: bool = True
    generated_at: datetime | None = None


def compute_atlas_digest_id(source: SourceIdentity) -> str:
    body = f"{source.source_kind}:{source.video_id}:{source.transcript_sha256}"
    return f"atlas_digest_{sha256(body.encode()).hexdigest()[:16]}"


def principle_is_traceable(principle: AtlasPrinciple) -> bool:
    return (
        bool(principle.source.video_id)
        and bool(principle.source.transcript_sha256)
        and bool(principle.principle_digest)
    )


def validate_surface_distinction(
    principles: list[AtlasPrinciple],
) -> dict[SurfaceTarget, int]:
    """Count principles applicable per surface to confirm distinction exists."""
    counts: dict[SurfaceTarget, int] = {t: 0 for t in SurfaceTarget}
    for p in principles:
        for s in p.surface_applicability:
            if s.applicable:
                counts[s.target] += 1
    return counts


__all__ = [
    "ApplicabilityClass",
    "AtlasDigestResult",
    "AtlasPrinciple",
    "InteractionGrammarImplication",
    "PrincipleKind",
    "SourceIdentity",
    "SurfaceApplicability",
    "SurfaceTarget",
    "TranscriptDigestInput",
    "VisualGrammarImplication",
    "compute_atlas_digest_id",
    "principle_is_traceable",
    "validate_surface_distinction",
]

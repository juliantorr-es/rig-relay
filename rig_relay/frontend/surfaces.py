"""Three-surface frontend architecture model.

Defines the three distinct application surfaces that Rig Relay's frontend must
eventually serve:

1. Gridline Interface — native desktop main-bridge operator UI.
2. Per-Repository Project Page — GitHub Pages static publication for one project.
3. Developer Repository Portfolio Site — GitHub Pages static publication across projects.

These surfaces share design tokens, rendering primitives, and evidence-card
vocabulary but have distinct reader goals, navigation, projection inputs,
and publication policies.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FrontendSurfaceKind(StrEnum):
    GRIDLINE = "gridline"
    PROJECT_PAGE = "project_page"
    PORTFOLIO_SITE = "portfolio_site"


class ReaderGoal(StrEnum):
    OPERATE = "operate"
    REVIEW = "review"
    EVALUATE = "evaluate"
    NAVIGATE = "navigate"
    VERIFY = "verify"
    DISCOVER = "discover"
    MONITOR = "monitor"
    CRITIQUE = "critique"


class PrivacyClass(StrEnum):
    PUBLIC_SAFE = "public_safe"
    CONTENT_LIGHT = "content_light"
    INTERNAL_ONLY = "internal_only"


class EvidenceStatus(StrEnum):
    PROVEN = "proven"
    CLAIMED = "claimed"
    PLANNED = "planned"
    NARRATIVE = "narrative"
    REDACTED = "redacted"


class RequiredSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str
    purpose: str
    required: bool = True
    projection_input_key: str = ""


class SurfaceSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_kind: FrontendSurfaceKind
    reader_goals: list[ReaderGoal]
    required_sections: list[RequiredSection]
    privacy_class: PrivacyClass
    static_or_live: Literal["live", "static"]
    publication_safe: bool
    can_expose_canonical_evidence: bool
    description: str = ""
    projection_source_roots: list[str] = Field(default_factory=list)


class SharedArchitectureElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_name: str
    element_kind: str
    surfaces_using: list[FrontendSurfaceKind]
    specification_digest: str = ""


class ThreeSurfaceArchitecture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.frontend_three_surface_architecture.v1"
    architecture_id: str
    surfaces: dict[FrontendSurfaceKind, SurfaceSpecification]
    shared_elements: list[SharedArchitectureElement]
    distinct_elements: list[str]
    content_light: bool = True
    generated_at: datetime | None = None

    def compute_architecture_digest(self) -> str:
        parts: list[str] = []
        for kind in FrontendSurfaceKind:
            spec = self.surfaces[kind]
            parts.append(f"{kind.value}:{spec.privacy_class.value}")
        body = "|".join(sorted(parts))
        return f"sha256:{sha256(body.encode()).hexdigest()}"


def build_gridline_specification() -> SurfaceSpecification:
    return SurfaceSpecification(
        surface_kind=FrontendSurfaceKind.GRIDLINE,
        reader_goals=[
            ReaderGoal.OPERATE,
            ReaderGoal.MONITOR,
            ReaderGoal.REVIEW,
            ReaderGoal.VERIFY,
        ],
        required_sections=[
            RequiredSection(
                section_id="chat_console",
                title="Chat Console",
                purpose="Chat-first operator flow for agent interaction",
                projection_input_key="chat_state",
            ),
            RequiredSection(
                section_id="evidence_rail",
                title="Evidence Rail",
                purpose="Progressive disclosure of receipts, audits, refusals",
                projection_input_key="integrity",
            ),
            RequiredSection(
                section_id="safety_state",
                title="Safety State",
                purpose="Current safety-mode status and active restrictions",
                projection_input_key="current_state",
            ),
            RequiredSection(
                section_id="provider_diagnostics",
                title="Provider Diagnostics",
                purpose="Provider health, token usage, refusal rates",
                projection_input_key="providers",
            ),
            RequiredSection(
                section_id="lane_status",
                title="Lane Status",
                purpose="Active mission lanes, deferred work, coordination state",
                projection_input_key="current_state",
            ),
            RequiredSection(
                section_id="storage_budget",
                title="Storage Budget",
                purpose="Local storage consumption and budget status",
                projection_input_key="storage",
            ),
            RequiredSection(
                section_id="disclosure_history",
                title="Disclosure History",
                purpose="Disclosure transition log for governed data flows",
                projection_input_key="disclosure",
            ),
            RequiredSection(
                section_id="capability_admission",
                title="Capability Admission",
                purpose="Runtime constraint capability status",
                projection_input_key="capability",
            ),
            RequiredSection(
                section_id="operational_snapshot",
                title="Operational Snapshot",
                purpose="Runtime outcome projection and recovery status",
                projection_input_key="operational",
            ),
        ],
        privacy_class=PrivacyClass.INTERNAL_ONLY,
        static_or_live="live",
        publication_safe=False,
        can_expose_canonical_evidence=True,
        description="Native desktop main-bridge operator UI — interactive, chat-first, progressively disclosed, evidence-aware",
        projection_source_roots=[
            "current_state",
            "providers",
            "storage",
            "integrity",
            "chat_state",
            "release_gate",
            "operational",
            "capability",
            "disclosure",
        ],
    )


def build_project_page_specification() -> SurfaceSpecification:
    return SurfaceSpecification(
        surface_kind=FrontendSurfaceKind.PROJECT_PAGE,
        reader_goals=[
            ReaderGoal.EVALUATE,
            ReaderGoal.VERIFY,
            ReaderGoal.REVIEW,
            ReaderGoal.NAVIGATE,
        ],
        required_sections=[
            RequiredSection(
                section_id="project_identity",
                title="Project Identity",
                purpose="Project purpose, product identity, current milestone",
                projection_input_key="project_identity",
            ),
            RequiredSection(
                section_id="status_overview",
                title="Status Overview",
                purpose="What is implemented versus planned — evidence-backed",
                projection_input_key="status_overview",
            ),
            RequiredSection(
                section_id="accomplishments",
                title="Accomplishments",
                purpose="Evidence-backed accomplishments with receipt references",
                projection_input_key="accomplishments",
            ),
            RequiredSection(
                section_id="released_boundaries",
                title="Released Boundaries",
                purpose="Published architectural boundaries and open seams",
                projection_input_key="released_boundaries",
            ),
            RequiredSection(
                section_id="mission_timeline",
                title="Mission Timeline",
                purpose="Mission and lane timeline with completion status",
                projection_input_key="mission_timeline",
            ),
            RequiredSection(
                section_id="architecture_overview",
                title="Architecture Overview",
                purpose="System architecture, major subsystems, component map",
                projection_input_key="architecture_overview",
            ),
            RequiredSection(
                section_id="capability_views",
                title="Capability Views",
                purpose="Provider, runtime, and governance capability status",
                projection_input_key="capability_views",
            ),
            RequiredSection(
                section_id="audit_proof_reader",
                title="Audit & Proof Reader",
                purpose="Browseable audit artifacts and proof chains",
                projection_input_key="audit_proofs",
            ),
            RequiredSection(
                section_id="changelog",
                title="Changelog & Checkpoint Progression",
                purpose="Checkpoint commit progression and changelog",
                projection_input_key="changelog",
            ),
            RequiredSection(
                section_id="screenshots_demos",
                title="Screenshots & Demos",
                purpose="Product demonstrations and screenshots when available",
                projection_input_key="screenshots_demos",
                required=False,
            ),
        ],
        privacy_class=PrivacyClass.PUBLIC_SAFE,
        static_or_live="static",
        publication_safe=True,
        can_expose_canonical_evidence=False,
        description="GitHub Pages static evidence portal for one repository — what is this project, what has been built, what is proven, what remains open",
        projection_source_roots=[
            "project_identity",
            "status_overview",
            "accomplishments",
            "released_boundaries",
            "mission_timeline",
            "architecture_overview",
            "capability_views",
            "audit_proofs",
            "changelog",
            "screenshots_demos",
        ],
    )


def build_portfolio_site_specification() -> SurfaceSpecification:
    return SurfaceSpecification(
        surface_kind=FrontendSurfaceKind.PORTFOLIO_SITE,
        reader_goals=[
            ReaderGoal.DISCOVER,
            ReaderGoal.EVALUATE,
            ReaderGoal.NAVIGATE,
            ReaderGoal.CRITIQUE,
        ],
        required_sections=[
            RequiredSection(
                section_id="developer_identity",
                title="Developer Identity",
                purpose="Developer-level identity and engineering thesis",
                projection_input_key="developer_identity",
            ),
            RequiredSection(
                section_id="project_catalogue",
                title="Project Catalogue",
                purpose="Featured systems and project inventory with status",
                projection_input_key="project_catalogue",
            ),
            RequiredSection(
                section_id="case_studies",
                title="Case Studies",
                purpose="Evidence-backed case studies assembled from published project evidence",
                projection_input_key="case_studies",
            ),
            RequiredSection(
                section_id="technology_capability_map",
                title="Technology & Capability Map",
                purpose="Technology stack and engineering capabilities demonstrated across projects",
                projection_input_key="technology_capability_map",
            ),
            RequiredSection(
                section_id="engineering_milestones",
                title="Engineering Milestones",
                purpose="Milestones and proof-backed achievements across projects",
                projection_input_key="engineering_milestones",
            ),
            RequiredSection(
                section_id="screenshots_demonstrations",
                title="Screenshots & Demonstrations",
                purpose="Screenshots, demos, and polished narrative pages",
                projection_input_key="screenshots_demonstrations",
                required=False,
            ),
            RequiredSection(
                section_id="cross_project_themes",
                title="Cross-Project Themes",
                purpose="Cross-project comparisons or recurring engineering themes",
                projection_input_key="cross_project_themes",
                required=False,
            ),
            RequiredSection(
                section_id="project_links",
                title="Project Links",
                purpose="Clear links into each project's dedicated project page",
                projection_input_key="project_links",
            ),
        ],
        privacy_class=PrivacyClass.PUBLIC_SAFE,
        static_or_live="static",
        publication_safe=True,
        can_expose_canonical_evidence=False,
        description="GitHub Pages static portfolio/case-study publication across projects — what systems have been built, what engineering capabilities are demonstrated, why the developer is credible",
        projection_source_roots=[
            "developer_identity",
            "project_catalogue",
            "case_studies",
            "technology_capability_map",
            "engineering_milestones",
            "screenshots_demonstrations",
            "cross_project_themes",
            "project_links",
        ],
    )


def build_shared_architecture_elements() -> list[SharedArchitectureElement]:
    return [
        SharedArchitectureElement(
            element_name="design_tokens",
            element_kind="token_system",
            surfaces_using=[
                FrontendSurfaceKind.GRIDLINE,
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="typography_rhythm_scale",
            element_kind="typography",
            surfaces_using=[
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="content_light_evidence_card",
            element_kind="component",
            surfaces_using=[
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="timeline_primitive",
            element_kind="component",
            surfaces_using=[
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="capability_badge",
            element_kind="component",
            surfaces_using=[
                FrontendSurfaceKind.GRIDLINE,
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="static_rendering_primitives",
            element_kind="rendering_infrastructure",
            surfaces_using=[
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="evidence_status_vocabulary",
            element_kind="vocabulary",
            surfaces_using=[
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
        SharedArchitectureElement(
            element_name="accessibility_rules",
            element_kind="accessibility",
            surfaces_using=[
                FrontendSurfaceKind.GRIDLINE,
                FrontendSurfaceKind.PROJECT_PAGE,
                FrontendSurfaceKind.PORTFOLIO_SITE,
            ],
        ),
    ]


def build_three_surface_architecture() -> ThreeSurfaceArchitecture:
    surfaces = {
        FrontendSurfaceKind.GRIDLINE: build_gridline_specification(),
        FrontendSurfaceKind.PROJECT_PAGE: build_project_page_specification(),
        FrontendSurfaceKind.PORTFOLIO_SITE: build_portfolio_site_specification(),
    }
    arch = ThreeSurfaceArchitecture(
        architecture_id=_compute_arch_id(surfaces),
        surfaces=surfaces,
        shared_elements=build_shared_architecture_elements(),
        distinct_elements=[
            "reader_goals",
            "projection_source_roots",
            "navigation_and_information_architecture",
            "disclosure_defaults",
            "privacy_and_publication_policy",
            "static_vs_live_rendering",
            "project_branding_vs_developer_identity",
            "canonical_evidence_exposure_rules",
        ],
    )
    arch.compute_architecture_digest()
    return arch


def _compute_arch_id(surfaces: dict[FrontendSurfaceKind, SurfaceSpecification]) -> str:
    parts: list[str] = []
    for kind in sorted(surfaces.keys(), key=lambda k: k.value):
        spec = surfaces[kind]
        parts.append(f"{kind.value}:{spec.privacy_class.value}")
    body = "|".join(parts)
    return f"arch_{sha256(body.encode()).hexdigest()[:12]}"


def surface_specifications_are_distinct() -> bool:
    """Falsify check: project-page and portfolio-site must remain distinct."""
    pp = build_project_page_specification()
    ps = build_portfolio_site_specification()
    pp_goals = {g.value for g in pp.reader_goals}
    ps_goals = {g.value for g in ps.reader_goals}
    if not (pp_goals - ps_goals) or not (ps_goals - pp_goals):
        return False
    pp_roots = set(pp.projection_source_roots)
    ps_roots = set(ps.projection_source_roots)
    if pp_roots == ps_roots:
        return False
    pp_sections = {s.section_id for s in pp.required_sections}
    ps_sections = {s.section_id for s in ps.required_sections}
    return bool(pp_sections - ps_sections) and bool(ps_sections - pp_sections)


__all__ = [
    "EvidenceStatus",
    "FrontendSurfaceKind",
    "PrivacyClass",
    "ReaderGoal",
    "RequiredSection",
    "SharedArchitectureElement",
    "SurfaceSpecification",
    "ThreeSurfaceArchitecture",
    "build_gridline_specification",
    "build_portfolio_site_specification",
    "build_project_page_specification",
    "build_shared_architecture_elements",
    "build_three_surface_architecture",
    "surface_specifications_are_distinct",
]

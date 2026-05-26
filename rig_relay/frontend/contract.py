"""Surface specification and publication projection contract.

Provides the typed, deterministic, content-light contracts that a future
static publication compiler and desktop projection consumer can wire against.

Defines:
  - PublicationProjection: dual-output contract distinguishing project-page
    from portfolio-site compilation inputs.
  - SurfaceSpecificationContract: the compiler-facing specification that
    makes the three-surface distinction machine-legible.
  - Sample fixtures for deterministic validation of the distinction.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.frontend.surfaces import (
    EvidenceStatus,
    FrontendSurfaceKind,
    PrivacyClass,
    ReaderGoal,
    SurfaceSpecification,
    build_portfolio_site_specification,
    build_project_page_specification,
)


class PublicationSurfaceKind(StrEnum):
    PROJECT_PAGE = "project_page"
    PORTFOLIO_SITE = "portfolio_site"


class ProjectIdentitySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "project_identity"
    project_name: str
    tagline: str
    current_milestone: str = ""
    product_identity_blurb: str = ""


class StatusOverviewSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "status_overview"
    implemented_count: int = 0
    planned_count: int = 0
    overall_status: str = "alpha"
    evidence_backed: bool = True


class AccomplishmentsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "accomplishments"
    items: list[dict[str, str]] = Field(default_factory=list)
    total_receipts_referenced: int = 0


class MissionTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    title: str
    status: EvidenceStatus = EvidenceStatus.PLANNED
    completed_at: datetime | None = None


class MissionTimelineSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "mission_timeline"
    entries: list[MissionTimelineEntry] = Field(default_factory=list)


class ReleasedBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary_name: str
    release_status: EvidenceStatus
    consuming_surfaces: list[str] = Field(default_factory=list)


class ReleasedBoundariesSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "released_boundaries"
    boundaries: list[ReleasedBoundary] = Field(default_factory=list)


class ProjectPagePublicationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.publication_projection.v1"
    publication_surface: Literal[PublicationSurfaceKind.PROJECT_PAGE] = (
        PublicationSurfaceKind.PROJECT_PAGE
    )
    projection_id: str
    project_identity: ProjectIdentitySection
    status_overview: StatusOverviewSection
    accomplishments: AccomplishmentsSection
    released_boundaries: ReleasedBoundariesSection
    mission_timeline: MissionTimelineSection
    architecture_overview: dict[str, str] = Field(default_factory=dict)
    capability_views: dict[str, str] = Field(default_factory=dict)
    audit_proofs: list[str] = Field(default_factory=list)
    changelog: list[dict[str, str]] = Field(default_factory=list)
    screenshots_demos: list[str] = Field(default_factory=list)
    content_light_guarantee: bool = True
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC_SAFE
    generated_at: datetime | None = None
    projection_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.projection_id}:"
            f"{self.project_identity.project_name}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class DeveloperIdentitySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "developer_identity"
    developer_name: str
    engineering_thesis: str = ""
    public_contact: str = ""


class ProjectCatalogueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    project_url: str
    status: str
    description: str
    featured: bool = False


class ProjectCatalogueSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "project_catalogue"
    entries: list[ProjectCatalogueEntry] = Field(default_factory=list)


class CaseStudy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str
    title: str
    source_project: str
    summary: str
    evidence_references: list[str] = Field(default_factory=list)


class CaseStudiesSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = "case_studies"
    studies: list[CaseStudy] = Field(default_factory=list)


class PortfolioSitePublicationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.publication_projection.v1"
    publication_surface: Literal[PublicationSurfaceKind.PORTFOLIO_SITE] = (
        PublicationSurfaceKind.PORTFOLIO_SITE
    )
    projection_id: str
    developer_identity: DeveloperIdentitySection
    project_catalogue: ProjectCatalogueSection
    case_studies: CaseStudiesSection
    technology_capability_map: dict[str, list[str]] = Field(default_factory=dict)
    engineering_milestones: list[dict[str, str]] = Field(default_factory=list)
    screenshots_demonstrations: list[str] = Field(default_factory=list)
    content_light_guarantee: bool = True
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC_SAFE
    generated_at: datetime | None = None
    projection_digest: str = ""

    def compute_digest(self) -> str:
        canonical = (
            f"{self.schema_version}:{self.projection_id}:"
            f"{self.developer_identity.developer_name}"
        )
        return f"sha256:{sha256(canonical.encode()).hexdigest()}"


class SurfaceSpecificationContract(BaseModel):
    """Compiler-facing contract that makes the three-surface distinction machine-legible.

    This is the production boundary: a future static compiler or desktop projection
    consumer reads this contract to understand which surfaces exist, what their
    required sections are, what projection inputs they consume, and what privacy
    and publication rules apply.

    It is NOT a sample website, a mock UI, or a design document. It is a typed,
    deterministic, content-light specification.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.frontend_surface_specification_contract.v1"
    contract_id: str
    surfaces: dict[FrontendSurfaceKind, SurfaceSpecification]
    distinct_projection_roots: dict[FrontendSurfaceKind, list[str]]
    shared_rendering_primitives: list[str]
    distinct_reader_goals: dict[FrontendSurfaceKind, list[str]]
    publication_safety_rules: list[str]
    content_light_rules: list[str]
    deterministic_digest: str = ""
    generated_at: datetime | None = None


def build_surface_specification_contract() -> SurfaceSpecificationContract:
    gridline = SurfaceSpecification(
        surface_kind=FrontendSurfaceKind.GRIDLINE,
        reader_goals=[
            ReaderGoal.OPERATE,
            ReaderGoal.MONITOR,
            ReaderGoal.REVIEW,
            ReaderGoal.VERIFY,
        ],
        required_sections=[],
        privacy_class=PrivacyClass.INTERNAL_ONLY,
        static_or_live="live",
        publication_safe=False,
        can_expose_canonical_evidence=True,
        description="Native desktop main-bridge operator UI",
        projection_source_roots=[
            "current_state",
            "providers",
            "storage",
            "integrity",
            "chat_state",
            "operational",
            "capability",
            "disclosure",
        ],
    )
    project_page = build_project_page_specification()
    portfolio_site = build_portfolio_site_specification()

    contract = SurfaceSpecificationContract(
        contract_id=_compute_contract_id(gridline, project_page, portfolio_site),
        surfaces={
            FrontendSurfaceKind.GRIDLINE: gridline,
            FrontendSurfaceKind.PROJECT_PAGE: project_page,
            FrontendSurfaceKind.PORTFOLIO_SITE: portfolio_site,
        },
        distinct_projection_roots={
            FrontendSurfaceKind.GRIDLINE: gridline.projection_source_roots,
            FrontendSurfaceKind.PROJECT_PAGE: project_page.projection_source_roots,
            FrontendSurfaceKind.PORTFOLIO_SITE: portfolio_site.projection_source_roots,
        },
        shared_rendering_primitives=[
            "design_tokens",
            "evidence_card",
            "timeline_primitive",
            "capability_badge",
            "status_indicator",
            "definition_list",
            "section_header",
            "footer_nav",
        ],
        distinct_reader_goals={
            FrontendSurfaceKind.GRIDLINE: [g.value for g in gridline.reader_goals],
            FrontendSurfaceKind.PROJECT_PAGE: [
                g.value for g in project_page.reader_goals
            ],
            FrontendSurfaceKind.PORTFOLIO_SITE: [
                g.value for g in portfolio_site.reader_goals
            ],
        },
        publication_safety_rules=[
            "no_raw_secrets_or_tokens",
            "no_private_repository_contents",
            "no_unreviewed_runtime_payloads",
            "no_protected_source_content",
            "no_raw_prompts_or_model_outputs",
            "no_unrestricted_local_paths",
            "all_claims_traceable_to_published_evidence_or_marked_narrative",
            "content_light_guarantee_enforced_on_all_public_projections",
        ],
        content_light_rules=[
            "sha256_hashes_for_content_derived_references",
            "no_raw_file_contents",
            "no_raw_prompts_or_model_outputs",
            "no_stdout_stderr_bodies",
            "no_private_paths",
            "counts_and_statuses_only",
        ],
    )
    contract.deterministic_digest = _compute_deterministic_digest(contract)
    return contract


def _compute_contract_id(
    gridline: SurfaceSpecification,
    project_page: SurfaceSpecification,
    portfolio_site: SurfaceSpecification,
) -> str:
    body = (
        f"{gridline.surface_kind.value}:{gridline.privacy_class.value}|"
        f"{project_page.surface_kind.value}:{project_page.privacy_class.value}|"
        f"{portfolio_site.surface_kind.value}:{portfolio_site.privacy_class.value}"
    )
    return f"ssc_{sha256(body.encode()).hexdigest()[:12]}"


def _compute_deterministic_digest(contract: SurfaceSpecificationContract) -> str:
    roots: list[str] = []
    for kind in sorted(
        contract.distinct_projection_roots.keys(), key=lambda k: k.value
    ):
        roots.append(
            f"{kind.value}:{','.join(sorted(contract.distinct_projection_roots[kind]))}"
        )
    body = "|".join(roots)
    return f"sha256:{sha256(body.encode()).hexdigest()}"


def contract_surfaces_are_distinct(contract: SurfaceSpecificationContract) -> bool:
    pp_roots = set(contract.distinct_projection_roots[FrontendSurfaceKind.PROJECT_PAGE])
    ps_roots = set(
        contract.distinct_projection_roots[FrontendSurfaceKind.PORTFOLIO_SITE]
    )
    if pp_roots == ps_roots:
        return False
    pp_goals = set(contract.distinct_reader_goals[FrontendSurfaceKind.PROJECT_PAGE])
    ps_goals = set(contract.distinct_reader_goals[FrontendSurfaceKind.PORTFOLIO_SITE])
    return bool(pp_goals - ps_goals) and bool(ps_goals - pp_goals)


def build_project_page_sample_projection(
    project_name: str = "Rig Relay",
) -> ProjectPagePublicationProjection:
    projection = ProjectPagePublicationProjection(
        projection_id=f"proj_{project_name.lower().replace(' ', '_')}_page",
        project_identity=ProjectIdentitySection(
            project_name=project_name,
            tagline=f"{project_name} — governed local control-plane with desktop cockpit",
            current_milestone="Alpha v0.1.0a1",
            product_identity_blurb=(
                f"{project_name} is a governed local server/control-plane with a desktop "
                "cockpit frontend for coordinating agent work, observing runtime behavior, "
                "and producing structured evidence."
            ),
        ),
        status_overview=StatusOverviewSection(
            implemented_count=87,
            planned_count=23,
            overall_status="alpha",
            evidence_backed=True,
        ),
        accomplishments=AccomplishmentsSection(
            items=[
                {
                    "title": "Desktop WebSocket Projection Server",
                    "receipt_ref": "sha256:...",
                },
                {"title": "Governed Checkpoint Commits", "receipt_ref": "sha256:..."},
                {"title": "Fleet Coordination Plane", "receipt_ref": "sha256:..."},
            ],
            total_receipts_referenced=42,
        ),
        released_boundaries=ReleasedBoundariesSection(
            boundaries=[
                ReleasedBoundary(
                    boundary_name="disclosure_query_service",
                    release_status=EvidenceStatus.PROVEN,
                    consuming_surfaces=["gridline"],
                ),
                ReleasedBoundary(
                    boundary_name="provider_evidence_query_service",
                    release_status=EvidenceStatus.PROVEN,
                    consuming_surfaces=["gridline"],
                ),
                ReleasedBoundary(
                    boundary_name="capability_admission_service",
                    release_status=EvidenceStatus.PROVEN,
                    consuming_surfaces=["gridline"],
                ),
                ReleasedBoundary(
                    boundary_name="frontend_surface_specification_contract",
                    release_status=EvidenceStatus.CLAIMED,
                    consuming_surfaces=["project_page", "portfolio_site", "gridline"],
                ),
            ]
        ),
        mission_timeline=MissionTimelineSection(
            entries=[
                MissionTimelineEntry(
                    mission_id="lane_e0",
                    title="Frontend Systems Atlas and Dual Surface Architecture",
                    status=EvidenceStatus.CLAIMED,
                ),
                MissionTimelineEntry(
                    mission_id="lane_d2",
                    title="Native JSON Schema Enforcement",
                    status=EvidenceStatus.PROVEN,
                ),
                MissionTimelineEntry(
                    mission_id="lane_c5",
                    title="Canonical Provider Evidence Ledger",
                    status=EvidenceStatus.PROVEN,
                ),
                MissionTimelineEntry(
                    mission_id="lane_b6",
                    title="Runtime Outcome Projection",
                    status=EvidenceStatus.PROVEN,
                ),
            ]
        ),
        architecture_overview={
            "subsystems": "Desktop, Governance, Recovery, Providers, Analytics, Coordination",
            "protocol_surfaces": "ACP, MCP (server + client), WebSocket, A2A",
            "frontend": "pywebview native desktop + vanilla JS frontend",
        },
        capability_views={
            "providers": "DeepSeek, OpenAI, Anthropic, Google, Mistral, OpenRouter",
            "runtime_enforcement": "Native JSON Schema, Grammar GBNF",
            "governance": "Dirty-file guard, checkpoint commits, receipt-backed evidence",
        },
        changelog=[
            {
                "version": "f03a11d7",
                "description": "Claim-adversary checks for OpenCode prompts",
            },
            {"version": "d8c636b9", "description": "v2 disclosure transition recovery"},
        ],
    )
    projection.projection_digest = projection.compute_digest()
    return projection


def build_portfolio_site_sample_projection(
    developer_name: str = "Julian Torres",
) -> PortfolioSitePublicationProjection:
    projection = PortfolioSitePublicationProjection(
        projection_id="proj_developer_portfolio",
        developer_identity=DeveloperIdentitySection(
            developer_name=developer_name,
            engineering_thesis=(
                "Building governed, evidence-backed software systems with "
                "desktop-native control planes, fleet orchestration, and "
                "structured agent safety guarantees."
            ),
        ),
        project_catalogue=ProjectCatalogueSection(
            entries=[
                ProjectCatalogueEntry(
                    project_name="Rig Relay",
                    project_url="https://github.com/juliantorr-es/rig-relay",
                    status="alpha",
                    description="Governed local server/control-plane with desktop cockpit",
                    featured=True,
                )
            ]
        ),
        case_studies=CaseStudiesSection(
            studies=[
                CaseStudy(
                    study_id="cs_rig_relay_governance",
                    title="Governed Agent Tool Safety in Rig Relay",
                    source_project="Rig Relay",
                    summary=(
                        "How Rig Relay implements 28-field environment scrubbing, "
                        "binary rejection, symlink protection, and bash rerouting "
                        "to achieve bounded tool safety for coding agents."
                    ),
                    evidence_references=["receipt_sha256:...", "receipt_sha256:..."],
                ),
                CaseStudy(
                    study_id="cs_rig_relay_fleet",
                    title="Fleet Coordination Plane: Multi-Session Orchestration",
                    source_project="Rig Relay",
                    summary=(
                        "Design and implementation of a file-backed coordination "
                        "plane supporting task claims, path reservations, handoffs, "
                        "and compact state projections across parallel agent sessions."
                    ),
                    evidence_references=["receipt_sha256:...", "receipt_sha256:..."],
                ),
            ]
        ),
        technology_capability_map={
            "languages": ["Python 3.12+", "TypeScript", "CSS", "HTML"],
            "frameworks": ["Pydantic", "DuckDB", "pywebview", "Jinja2"],
            "protocols": ["WebSocket", "ACP", "MCP", "A2A", "OAuth 2.0"],
            "testing": ["pytest", "pytest-asyncio", "pytest-xdist", "respx"],
        },
        engineering_milestones=[
            {"milestone": "Desktop Cockpit Launch", "status": "proven", "date": "2025"},
            {
                "milestone": "Fleet Coordination Plane",
                "status": "proven",
                "date": "2026-05",
            },
            {
                "milestone": "Frontend Systems Atlas",
                "status": "claimed",
                "date": "2026-05",
            },
        ],
    )
    projection.projection_digest = projection.compute_digest()
    return projection


def publication_projections_are_distinct(
    project_proj: ProjectPagePublicationProjection,
    portfolio_proj: PortfolioSitePublicationProjection,
) -> bool:
    pp = json.loads(project_proj.model_dump_json())
    ps = json.loads(portfolio_proj.model_dump_json())
    _excluded = {
        "schema_version",
        "content_light_guarantee",
        "privacy_class",
        "generated_at",
        "projection_digest",
    }
    pp_keys = {k for k in pp if not k.startswith("_") and k not in _excluded}
    ps_keys = {k for k in ps if not k.startswith("_") and k not in _excluded}
    return bool(pp_keys - ps_keys) and bool(ps_keys - pp_keys)


def projection_is_content_light(data: dict) -> bool:
    forbidden = {
        "raw_file_contents",
        "raw_prompt_text",
        "model_output_text",
        "stdout_bodies",
        "stderr_bodies",
        "secrets",
        "raw_private_code",
    }
    flat = json.dumps(data)
    return not any(f in flat.lower() for f in forbidden)


__all__ = [
    "AccomplishmentsSection",
    "CaseStudiesSection",
    "CaseStudy",
    "DeveloperIdentitySection",
    "MissionTimelineEntry",
    "MissionTimelineSection",
    "PortfolioSitePublicationProjection",
    "ProjectCatalogueEntry",
    "ProjectCatalogueSection",
    "ProjectIdentitySection",
    "ProjectPagePublicationProjection",
    "PublicationSurfaceKind",
    "ReleasedBoundariesSection",
    "ReleasedBoundary",
    "StatusOverviewSection",
    "SurfaceSpecificationContract",
    "build_portfolio_site_sample_projection",
    "build_project_page_sample_projection",
    "build_surface_specification_contract",
    "contract_surfaces_are_distinct",
    "projection_is_content_light",
    "publication_projections_are_distinct",
]

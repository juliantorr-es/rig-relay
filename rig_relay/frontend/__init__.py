"""Lane E — Frontend Systems Atlas and Dual Static-Site Surface Architecture.

Owns:
  - Transcript-grounded design principle ingestion (atlas)
  - Three-surface architecture model (surfaces)
  - Surface specification/publication projection contract (contract)

Does NOT own:
  - Desktop runtime wiring (desktop/ package)
  - Static site renderer implementation (site_renderer/, docs_renderer/)
  - AgentLoop, telemetry, provider backends, recovery/disclosure authority
  - Any other lane's domain files
"""

from __future__ import annotations

from rig_relay.frontend.atlas import (
    ApplicabilityClass,
    AtlasDigestResult,
    AtlasPrinciple,
    InteractionGrammarImplication,
    PrincipleKind,
    SourceIdentity,
    SurfaceApplicability,
    SurfaceTarget,
    TranscriptDigestInput,
    VisualGrammarImplication,
    compute_atlas_digest_id,
    principle_is_traceable,
    validate_surface_distinction,
)
from rig_relay.frontend.contract import (
    AccomplishmentsSection,
    CaseStudiesSection,
    CaseStudy,
    DeveloperIdentitySection,
    MissionTimelineEntry,
    MissionTimelineSection,
    PortfolioSitePublicationProjection,
    ProjectCatalogueEntry,
    ProjectCatalogueSection,
    ProjectIdentitySection,
    ProjectPagePublicationProjection,
    PublicationSurfaceKind,
    ReleasedBoundariesSection,
    ReleasedBoundary,
    StatusOverviewSection,
    SurfaceSpecificationContract,
    build_portfolio_site_sample_projection,
    build_project_page_sample_projection,
    build_surface_specification_contract,
    contract_surfaces_are_distinct,
    projection_is_content_light,
    publication_projections_are_distinct,
)
from rig_relay.frontend.surfaces import (
    EvidenceStatus,
    FrontendSurfaceKind,
    PrivacyClass,
    ReaderGoal,
    RequiredSection,
    SharedArchitectureElement,
    SurfaceSpecification,
    ThreeSurfaceArchitecture,
    build_gridline_specification,
    build_portfolio_site_specification,
    build_project_page_specification,
    build_shared_architecture_elements,
    build_three_surface_architecture,
    surface_specifications_are_distinct,
)

__all__ = [
    # contract
    "AccomplishmentsSection",
    # atlas
    "ApplicabilityClass",
    "AtlasDigestResult",
    "AtlasPrinciple",
    "CaseStudiesSection",
    "CaseStudy",
    "DeveloperIdentitySection",
    # surfaces
    "EvidenceStatus",
    "FrontendSurfaceKind",
    "InteractionGrammarImplication",
    "MissionTimelineEntry",
    "MissionTimelineSection",
    "PortfolioSitePublicationProjection",
    "PrincipleKind",
    "PrivacyClass",
    "ProjectCatalogueEntry",
    "ProjectCatalogueSection",
    "ProjectIdentitySection",
    "ProjectPagePublicationProjection",
    "PublicationSurfaceKind",
    "ReaderGoal",
    "ReleasedBoundariesSection",
    "ReleasedBoundary",
    "RequiredSection",
    "SharedArchitectureElement",
    "SourceIdentity",
    "StatusOverviewSection",
    "SurfaceApplicability",
    "SurfaceSpecification",
    "SurfaceSpecificationContract",
    "SurfaceTarget",
    "ThreeSurfaceArchitecture",
    "TranscriptDigestInput",
    "VisualGrammarImplication",
    "build_gridline_specification",
    "build_portfolio_site_sample_projection",
    "build_portfolio_site_specification",
    "build_project_page_sample_projection",
    "build_project_page_specification",
    "build_shared_architecture_elements",
    "build_surface_specification_contract",
    "build_three_surface_architecture",
    "compute_atlas_digest_id",
    "contract_surfaces_are_distinct",
    "principle_is_traceable",
    "projection_is_content_light",
    "publication_projections_are_distinct",
    "surface_specifications_are_distinct",
    "validate_surface_distinction",
]

"""Developer Studio Gateway — Lane S2 (hardened from O0).

Backend bridge corridor consuming published J0/K0/L0/M0 application
services and exposing a single typed frontend-safe projection and
intent protocol for P0 (web frontend) and N1 (WebKit host).

Now evidence-backed: provenance is counted by walking projection trees;
content-light enforcement runs on every projection; idempotency keys
protect mutating intents from duplicate effects; explicit authority
states classify each consumed service from canonical evidence.
"""

from __future__ import annotations

from rig_relay.desktop.gateway._authority import (
    AuthorityEvidence,
    GatewayAuthorityReport,
    ServiceAuthority,
)
from rig_relay.desktop.gateway._intents import (
    execute_gateway_intent,
    get_gateway_service,
    is_gateway_intent,
    reset_gateway_service,
)
from rig_relay.desktop.gateway._models import (
    DeveloperStudioProjection,
    GatewayError,
    GatewayErrorKind,
    J0ConnectionProjection,
    J0RepositoryProjection,
    J0WorkspaceProjection,
    K0OperatorProjection,
    K0SessionProjection,
    L0ContextProjection,
    L0IntakeStatusProjection,
    L0StudyProjection,
    M0DraftEntry,
    M0InferenceProjection,
    M0RefusalEntry,
    M0TaskSuitabilityEntry,
    ProvenanceClass,
    StudioProvenanceSummary,
    StudioServiceHealth,
    TrustState,
)
from rig_relay.desktop.gateway._models_surfaces import (
    ConnectSurfaceProjection,
    EstateChangeEntry,
    EstateCorruptionEntry,
    EstateRepositoryEntry,
    InferenceStudioSurfaceProjection,
    ProviderConnectionEntry,
    PublishPreviewEvidenceSummary,
    PublishPreviewRefusalEntry,
    PublishPreviewSurfaceProjection,
    RepositoryEstateSurfaceProjection,
    TimelineEventEntry,
    TimelineSurfaceProjection,
)
from rig_relay.desktop.gateway._projection import (
    J0_PROJECTION_BUILDER,
    K0_PROJECTION_BUILDER,
    L0_PROJECTION_BUILDER,
    M0_PROJECTION_BUILDER,
)
from rig_relay.desktop.gateway._projection_surfaces import (
    CONNECT_SURFACE_PROJECTION_BUILDER,
    INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER,
    PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER,
    REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER,
    TIMELINE_SURFACE_PROJECTION_BUILDER,
)
from rig_relay.desktop.gateway._service import DeveloperStudioGatewayService

__all__ = [
    "CONNECT_SURFACE_PROJECTION_BUILDER",
    "INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER",
    "J0_PROJECTION_BUILDER",
    "K0_PROJECTION_BUILDER",
    "L0_PROJECTION_BUILDER",
    "M0_PROJECTION_BUILDER",
    "PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER",
    "REPOSITORY_ESTATE_SURFACE_PROJECTION_BUILDER",
    "TIMELINE_SURFACE_PROJECTION_BUILDER",
    "AuthorityEvidence",
    "ConnectSurfaceProjection",
    "DeveloperStudioGatewayService",
    "DeveloperStudioProjection",
    "EstateChangeEntry",
    "EstateCorruptionEntry",
    "EstateRepositoryEntry",
    "GatewayAuthorityReport",
    "GatewayError",
    "GatewayErrorKind",
    "InferenceStudioSurfaceProjection",
    "J0ConnectionProjection",
    "J0RepositoryProjection",
    "J0WorkspaceProjection",
    "K0OperatorProjection",
    "K0SessionProjection",
    "L0ContextProjection",
    "L0IntakeStatusProjection",
    "L0StudyProjection",
    "M0DraftEntry",
    "M0InferenceProjection",
    "M0RefusalEntry",
    "M0TaskSuitabilityEntry",
    "ProvenanceClass",
    "ProviderConnectionEntry",
    "PublishPreviewEvidenceSummary",
    "PublishPreviewRefusalEntry",
    "PublishPreviewSurfaceProjection",
    "RepositoryEstateSurfaceProjection",
    "ServiceAuthority",
    "StudioProvenanceSummary",
    "StudioServiceHealth",
    "TimelineEventEntry",
    "TimelineSurfaceProjection",
    "TrustState",
    "execute_gateway_intent",
    "get_gateway_service",
    "is_gateway_intent",
    "reset_gateway_service",
]

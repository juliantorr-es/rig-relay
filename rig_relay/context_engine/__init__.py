"""Lane L0 — Context Engine and Developer Knowledge Assembly Corridor.

Transforms governed repository intake and investigation evidence into:
  - ProjectUnderstandingProjection (private, operator-facing)
  - PublishableProjectProfileCandidate (public-safe, awaiting approval)
  - DeveloperCorpusIndex (private, for portfolio synthesis)
  - SanitizedContextPacket (bounded, provenance-rich context payload)

Consumes E0 frontend contracts and J0/K0 typed fixtures.
Does not own GitHub authentication, AgentLoop tools, local-model transport,
or UI rendering.
"""

from __future__ import annotations

from rig_relay.context_engine.assembler import ProjectContextAssemblyService
from rig_relay.context_engine.context_packet import build_sanitized_context_packet
from rig_relay.context_engine.extractor import SourceDerivedStructuralExtractor
from rig_relay.context_engine.fixtures import (
    IntakeFixture,
    InvestigationEvidenceFixture,
)
from rig_relay.context_engine.gridline_projection import (
    GridlineProjectUnderstandingProjection,
    build_gridline_project_understanding_projection,
)
from rig_relay.context_engine.models import (
    DeveloperCorpusIndex,
    ProjectPageCandidate,
    ProjectUnderstandingProjection,
    PublishableProjectProfileCandidate,
    SanitizedContextPacket,
)
from rig_relay.context_engine.provenance import (
    ApprovalStatus,
    EvidenceDerivedFact,
    FactOrigin,
    GeneratedClaim,
    PrivacyDisposition,
    SourceDerivedFact,
)
from rig_relay.context_engine.redaction import ProjectRedactionEngine

__all__ = [
    "ApprovalStatus",
    "DeveloperCorpusIndex",
    "EvidenceDerivedFact",
    "FactOrigin",
    "GeneratedClaim",
    "GridlineProjectUnderstandingProjection",
    "IntakeFixture",
    "InvestigationEvidenceFixture",
    "PrivacyDisposition",
    "ProjectContextAssemblyService",
    "ProjectPageCandidate",
    "ProjectRedactionEngine",
    "ProjectUnderstandingProjection",
    "PublishableProjectProfileCandidate",
    "SanitizedContextPacket",
    "SourceDerivedFact",
    "SourceDerivedStructuralExtractor",
    "build_gridline_project_understanding_projection",
    "build_sanitized_context_packet",
]

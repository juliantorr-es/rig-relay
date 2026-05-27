"""Repository Estate — operational repository registry and observation service.

Typed application service boundary for the Repository Estate product surface.
Registers local repositories, observes operational facts with identity-match
enforcement, emits canonical append-only content-light evidence, and produces
deterministic projections with explicit corruption degradation for PostgreSQL
materialization and Gridline consumption.

Public API:
    RepositoryEstateService — typed application service.
    RegistryError — domain validation failure.
    build_repository_estate_projection — produce a projection from a service.

Exported models (content-light, schema-backed):
    RegisteredRepository, RepositoryObservation, RepositoryObservationChange,
    RepositoryEstateProjection, RegisteredRepositorySummary, RecentChangeEvent,
    CorruptionEvent, GitIdentityBundle, DirtyCounts, InstructionFilePresence,
    RemoteRecord, ObservationStatus, ChangeKind, RepositoryKind, ProvenanceClass,
    AuthorityState.
"""

from __future__ import annotations

from rig_relay.repository_estate._digest_utils import (
    digest_path,
    digest_text,
    sha256_prefix,
)
from rig_relay.repository_estate._models import (
    AuthorityState,
    ChangeKind,
    CorruptionEvent,
    DirtyCounts,
    GitIdentityBundle,
    InstructionFilePresence,
    ObservationStatus,
    ProvenanceClass,
    RecentChangeEvent,
    RegisteredRepository,
    RegisteredRepositorySummary,
    RemoteRecord,
    RepositoryEstateProjection,
    RepositoryKind,
    RepositoryObservation,
    RepositoryObservationChange,
)
from rig_relay.repository_estate._projection import build_repository_estate_projection
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore
from rig_relay.repository_estate._service import RegistryError, RepositoryEstateService

__all__ = [
    "AuthorityState",
    "ChangeKind",
    "CorruptionEvent",
    "DirtyCounts",
    "GitIdentityBundle",
    "InstructionFilePresence",
    "ObservationStatus",
    "ProvenanceClass",
    "RecentChangeEvent",
    "RegisteredRepository",
    "RegisteredRepositorySummary",
    "RegistryError",
    "RemoteRecord",
    "RepositoryEstateProjection",
    "RepositoryEstateRegistryStore",
    "RepositoryEstateService",
    "RepositoryKind",
    "RepositoryObservation",
    "RepositoryObservationChange",
    "build_repository_estate_projection",
    "digest_path",
    "digest_text",
    "sha256_prefix",
]

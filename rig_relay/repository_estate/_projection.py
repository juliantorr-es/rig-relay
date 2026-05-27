"""Projection builder wrapper for RepositoryEstateService.

Produce a content-light RepositoryEstateProjection from canonical evidence
via the service's internal ProjectionBuilder collaborator.
"""

from __future__ import annotations

from rig_relay.repository_estate._models import RepositoryEstateProjection
from rig_relay.repository_estate._service import RepositoryEstateService


def build_repository_estate_projection(
    service: RepositoryEstateService,
) -> RepositoryEstateProjection:
    """Build a deterministic, content-light projection from evidence.

    Reconstructable from append-only registration and observation evidence.
    Suitable for PostgreSQL materialization and Gridline consumption.
    """
    return service.build_projection()


__all__ = ["build_repository_estate_projection"]

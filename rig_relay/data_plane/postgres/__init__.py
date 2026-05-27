"""PostgreSQL Operational Projection Store — T2 Data Plane Foundation.

Usage:
    from rig_relay.data_plane.postgres import PostgresOperationalProjectionStore

    store = PostgresOperationalProjectionStore(config)
    await store.ensure_migrated()
    receipt = await store.ingest_evidence(evidence_record)
    projection = await store.build_projection("session_summary")
"""

from __future__ import annotations

from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._models import (
    EvidenceSource,
    EvidenceSourceKind,
    IngestionCheckpoint,
    IngestionReceipt,
    MigrationRecord,
    ProjectionBuildReceipt,
    RebuildReceipt,
    SchemaVersionRecord,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore

__all__ = [
    "EvidenceSource",
    "EvidenceSourceKind",
    "IngestionCheckpoint",
    "IngestionReceipt",
    "MigrationRecord",
    "PostgresConnectionConfig",
    "PostgresOperationalProjectionStore",
    "ProjectionBuildReceipt",
    "RebuildReceipt",
    "SchemaVersionRecord",
]

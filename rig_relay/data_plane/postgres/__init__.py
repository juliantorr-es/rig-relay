"""PostgreSQL Operational Projection Store — Data Plane Foundation.

Provides a PostgreSQL-backed operational state plane that transactionally
materializes Repository Estate, Investigation Timeline, and publication-history
projections from published canonical evidence boundaries.

Usage:
    from rig_relay.data_plane.postgres import (
        PostgresOperationalProjectionStore,
        PostgresConnectionConfig,
        RepositoryEstateMaterializer,
        TimelineMaterializer,
        PublicationMaterializer,
        PostgresBackupService,
    )

    store = PostgresOperationalProjectionStore(config)
    store.ensure_migrated()
"""

from __future__ import annotations

from rig_relay.data_plane.postgres._backup_restore import PostgresBackupService
from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
from rig_relay.data_plane.postgres._materialization_input import (
    MaterializationInputStatus,
    PublicationMaterializationInput,
    RepositoryEstateMaterializationInput,
    TimelineMaterializationInput,
)
from rig_relay.data_plane.postgres._materialize_publication import (
    PublicationMaterializer,
)
from rig_relay.data_plane.postgres._materialize_repository_estate import (
    RepositoryEstateMaterializer,
)
from rig_relay.data_plane.postgres._materialize_timeline import TimelineMaterializer
from rig_relay.data_plane.postgres._models import (
    BackupReceipt,
    EvidenceSource,
    EvidenceSourceKind,
    IngestionCheckpoint,
    IngestionReceipt,
    MaterializationReceipt,
    MigrationRecord,
    MigrationUpgradeReceipt,
    ProjectionBuildReceipt,
    RebuildReceipt,
    RestoreReceipt,
    SchemaVersionRecord,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore

__all__ = [
    "BackupReceipt",
    "EvidenceSource",
    "EvidenceSourceKind",
    "IngestionCheckpoint",
    "IngestionReceipt",
    "MaterializationInputStatus",
    "MaterializationReceipt",
    "MigrationRecord",
    "MigrationUpgradeReceipt",
    "PostgresBackupService",
    "PostgresConnectionConfig",
    "PostgresOperationalProjectionStore",
    "ProjectionBuildReceipt",
    "PublicationMaterializationInput",
    "PublicationMaterializer",
    "RebuildReceipt",
    "RepositoryEstateMaterializationInput",
    "RepositoryEstateMaterializer",
    "RestoreReceipt",
    "SchemaVersionRecord",
    "TimelineMaterializationInput",
    "TimelineMaterializer",
]

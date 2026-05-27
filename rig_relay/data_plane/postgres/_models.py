"""Pydantic models for the PostgreSQL operational data plane.

All models follow content-light principles: no raw file contents, prompts,
model outputs, secrets, paths, or credentials in stored rows.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSourceKind(StrEnum):
    """Kind of canonical evidence source ingested into PostgreSQL."""

    COORDINATION_EVENT = "coordination_event"
    SESSION_OBSERVABILITY = "session_observability"
    GOVERNANCE_DECISION = "governance_decision"
    TOOL_CALL = "tool_call"
    CHECKPOINT = "checkpoint"
    ARTIFACT = "artifact"
    FINDING = "finding"
    PROJECTION = "projection"
    REPOSITORY_REGISTRATION = "repository_registration"
    REPOSITORY_OBSERVATION = "repository_observation"
    TIMELINE_EVENT = "timeline_event"
    PUBLICATION_PREVIEW_RECEIPT = "publication_preview_receipt"
    UNKNOWN = "unknown"


class EvidenceSource(BaseModel):
    """A content-light reference to a canonical evidence record.

    This is what gets stored in PostgreSQL — a digest-based identity,
    not the evidence payload itself. The canonical evidence ledger
    remains the authority.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        description="Unique identifier derived from canonical evidence content hash"
    )
    evidence_kind: EvidenceSourceKind = Field(description="Kind of evidence source")
    evidence_sha256: str = Field(
        description="SHA256 digest of the canonical evidence payload"
    )
    source_ledger_path_hash: str = Field(
        default="",
        description="Salted SHA256 hash of the source ledger path (content-light)",
    )
    source_schema_version: str = Field(
        default="", description="Schema version of the canonical evidence artifact"
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of ingestion"
    )
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Content-light provenance metadata (session_id, task_id, etc.)",
    )

    def digest_identity(self) -> str:
        """Return the digest identity used for idempotent deduplication."""
        return self.evidence_id


class MigrationRecord(BaseModel):
    """A single schema migration record.

    Migrations are ordered by index, idempotent where appropriate,
    transactional, and evidence-emitting.
    """

    model_config = ConfigDict(extra="forbid")

    migration_index: int = Field(ge=0, description="Ordered migration index")
    migration_id: str = Field(
        description="Unique migration identifier (e.g. '001_initial_schema')"
    )
    description: str = Field(
        default="", description="Human-readable migration description"
    )
    applied_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="UTC timestamp when migration was applied",
    )
    sql_hash: str = Field(description="SHA256 digest of the migration SQL")
    status: str = Field(
        default="applied", description="Migration status: applied, failed, rolled_back"
    )
    error_message: str | None = Field(
        default=None, description="Error message if migration failed"
    )


class SchemaVersionRecord(BaseModel):
    """Current schema version record — single-row table."""

    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(
        default="operational", description="PostgreSQL schema name"
    )
    current_version: int = Field(
        default=0, ge=0, description="Current migration index (0 = uninitialized)"
    )
    last_migration_id: str | None = Field(
        default=None, description="Last applied migration identifier"
    )
    last_applied_at: datetime | None = Field(
        default=None, description="When the last migration was applied"
    )
    schema_hash: str = Field(
        default="",
        description="SHA256 digest of all applied migration SQL (for integrity check)",
    )


class IngestionCheckpoint(BaseModel):
    """Records progress through a canonical evidence ledger for incremental ingestion."""

    model_config = ConfigDict(extra="forbid")

    ledger_path_hash: str = Field(description="Salted SHA256 hash of ledger path")
    last_sequence: int = Field(
        default=0, ge=0, description="Last ingested sequence number"
    )
    last_event_id: str = Field(default="", description="Last ingested event ID")
    records_ingested: int = Field(
        default=0, ge=0, description="Total records ingested from this ledger"
    )
    last_ingested_at: datetime | None = Field(
        default=None, description="UTC timestamp of last ingestion"
    )


class IngestionReceipt(BaseModel):
    """Receipt for a single evidence ingestion operation."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    evidence_id: str = Field(description="Evidence record identity")
    evidence_kind: EvidenceSourceKind = Field(description="Kind of evidence ingested")
    status: str = Field(
        default="ingested",
        description="Ingestion status: ingested, duplicate, refused, failed",
    )
    refusal_reason: str | None = Field(
        default=None, description="Reason if ingestion was refused"
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of ingestion"
    )
    projection_rows_created: int = Field(
        default=0, ge=0, description="Number of projection rows created"
    )


class ProjectionBuildReceipt(BaseModel):
    """Receipt for a projection materialization operation."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    projection_name: str = Field(description="Name of the projection built")
    source_evidence_count: int = Field(
        default=0, ge=0, description="Number of evidence sources consumed"
    )
    rows_built: int = Field(
        default=0, ge=0, description="Number of projection rows built"
    )
    built_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="UTC timestamp of projection build",
    )
    evidence_source_sha256: str = Field(
        default="",
        description="SHA256 digest of the combined evidence sources consumed",
    )


class RebuildReceipt(BaseModel):
    """Receipt for a complete projection rebuild operation."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    projection_name: str = Field(description="Name of the projection rebuilt")
    rows_before: int = Field(default=0, ge=0, description="Rows before rebuild")
    rows_after: int = Field(default=0, ge=0, description="Rows after rebuild")
    rebuilt_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of rebuild"
    )
    deterministic: bool = Field(
        default=False,
        description="Whether rows_before == rows_after (deterministic rebuild)",
    )


class MaterializationReceipt(BaseModel):
    """Receipt for a domain materialization operation.

    Records that a domain materializer successfully materialized
    rows from canonical evidence into the operational PostgreSQL tables.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    domain: str = Field(
        description="Domain materialized (repository_estate, timeline, publication)"
    )
    source_evidence_count: int = Field(
        default=0, ge=0, description="Canonical evidence records consumed"
    )
    rows_materialized: int = Field(
        default=0, ge=0, description="Rows inserted into domain tables"
    )
    corrupt_rows: int = Field(
        default=0, ge=0, description="Corrupt evidence rows refused"
    )
    duplicate_rows: int = Field(
        default=0, ge=0, description="Duplicate evidence rows skipped"
    )
    built_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="UTC timestamp of materialization",
    )
    evidence_source_sha256: str = Field(
        default="", description="SHA256 digest of combined evidence sources"
    )
    deterministic: bool = Field(
        default=False,
        description="Whether rebuild from same evidence produces identical rows",
    )


class BackupReceipt(BaseModel):
    """Content-light receipt for a PostgreSQL backup operation.

    Records what was backed up, how secrets were excluded,
    and the backup artifact identity. Never contains raw
    connection strings, passwords, or backup file contents.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    backup_method: str = Field(default="pg_dump", description="Backup method used")
    database_name: str = Field(default="", description="Database name (content-light)")
    schema_name: str = Field(default="", description="Schema name backed up")
    format: str = Field(
        default="custom", description="Backup format (custom, plain, tar, directory)"
    )
    backup_sha256: str = Field(
        default="", description="SHA256 digest of the backup artifact"
    )
    backup_size_bytes: int = Field(
        default=0, ge=0, description="Backup artifact size in bytes"
    )
    table_count: int = Field(default=0, ge=0, description="Number of tables in backup")
    migration_version: int = Field(
        default=0, ge=0, description="Schema version at backup time"
    )
    secrets_excluded: bool = Field(
        default=True, description="Whether secrets were excluded"
    )
    exclusion_method: str = Field(
        default="", description="How secrets were excluded (e.g. --exclude-table-data)"
    )
    backed_up_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of backup"
    )
    verified: bool = Field(
        default=False, description="Whether backup was verified after creation"
    )


class RestoreReceipt(BaseModel):
    """Content-light receipt for a PostgreSQL restore operation.

    Records restore outcome and equivalence to canonical evidence.
    Never contains raw connection strings or restore file contents.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    backup_receipt_id: str = Field(
        default="", description="Reference to the BackupReceipt used"
    )
    backup_sha256: str = Field(
        default="", description="SHA256 digest of the backup artifact restored"
    )
    restore_method: str = Field(default="pg_restore", description="Restore method used")
    restored_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of restore"
    )
    tables_restored: int = Field(
        default=0, ge=0, description="Number of tables restored"
    )
    rows_restored: int = Field(default=0, ge=0, description="Total rows restored")
    migration_version_restored: int = Field(
        default=0, ge=0, description="Schema version after restore"
    )
    canonical_equivalence_verified: bool = Field(
        default=False,
        description=(
            "DEPRECATED: use verified_equivalence_level instead. "
            "Set to True when schema_migration_metadata verification passes. "
            "Does NOT prove full product-state equivalence."
        ),
    )
    verified_equivalence_level: str = Field(
        default="none",
        description=(
            "Level of equivalence verification: 'none', 'schema_migration_metadata', "
            "or 'full_product_state'. Only 'full_product_state' proves domain table "
            "content equivalence via digest comparison."
        ),
    )
    verification_method: str = Field(
        default="", description="How equivalence was verified"
    )
    errors: list[str] = Field(
        default_factory=list, description="Restore errors encountered"
    )


class MigrationUpgradeReceipt(BaseModel):
    """Receipt for a schema version upgrade operation."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(description="Unique receipt identifier")
    from_version: int = Field(
        default=0, ge=0, description="Schema version before upgrade"
    )
    to_version: int = Field(default=0, ge=0, description="Schema version after upgrade")
    migrations_applied: int = Field(
        default=0, ge=0, description="Number of new migrations applied"
    )
    migration_ids: list[str] = Field(
        default_factory=list, description="Migration IDs applied"
    )
    schema_hash_before: str = Field(
        default="", description="Schema hash before upgrade"
    )
    schema_hash_after: str = Field(default="", description="Schema hash after upgrade")
    upgraded_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="UTC timestamp of upgrade"
    )
    success: bool = Field(
        default=False, description="Whether upgrade completed successfully"
    )
    rollback_available: bool = Field(
        default=False, description="Whether rollback is possible"
    )
    error_message: str | None = Field(
        default=None, description="Error message if upgrade failed"
    )


def compute_sha256(content: str) -> str:
    """Compute a SHA256 hex digest for a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_receipt_id(prefix: str, identity: str, timestamp: datetime) -> str:
    """Generate a deterministic receipt ID."""
    raw = f"{prefix}:{identity}:{timestamp.isoformat()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"

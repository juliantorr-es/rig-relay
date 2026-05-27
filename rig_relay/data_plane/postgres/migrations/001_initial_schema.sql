-- Migration 001: Initial operational projection schema
-- Creates the foundation tables for the PostgreSQL operational data plane.
--
-- Tables:
--   _schema_version       — Single-row schema version authority
--   _migrations           — Ordered migration record ledger
--   evidence_sources       — Content-light canonical evidence references
--   ingestion_checkpoints  — Ledger ingestion progress
--   ingestion_receipts     — Per-evidence ingestion receipts
--   projection_builds      — Projection materialization records
--   rebuild_receipts       — Projection rebuild receipts
--   operational_snapshots  — Service authority/degradation snapshots
--   notify_channels        — Registered notification channels (if LISTEN/NOTIFY used)
--
-- Content-light: no raw file contents, prompts, model outputs, secrets, paths.
-- All JSONB columns store structured operational metadata, not raw evidence payloads.

BEGIN;

-- Schema creation
CREATE SCHEMA IF NOT EXISTS {schema_name};

SET search_path TO {schema_name};

-- ── Schema version authority (single row) ──────────────────────────

CREATE TABLE _schema_version (
    schema_name     TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL DEFAULT 0,
    last_migration_id TEXT,
    last_applied_at TIMESTAMPTZ,
    schema_hash     TEXT NOT NULL DEFAULT ''
);

-- ── Migration record ledger (append-only) ──────────────────────────

CREATE TABLE _migrations (
    migration_index INTEGER NOT NULL,
    migration_id    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sql_hash        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'applied',
    error_message   TEXT,
    PRIMARY KEY (migration_index, migration_id)
);

-- ── Content-light evidence references ──────────────────────────────

CREATE TABLE evidence_sources (
    evidence_id              TEXT PRIMARY KEY,
    evidence_kind            TEXT NOT NULL,
    evidence_sha256          TEXT NOT NULL,
    source_ledger_path_hash  TEXT NOT NULL DEFAULT '',
    source_schema_version    TEXT NOT NULL DEFAULT '',
    ingested_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance               JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_evidence_sources_kind ON evidence_sources (evidence_kind);
CREATE INDEX idx_evidence_sources_sha256 ON evidence_sources (evidence_sha256);
CREATE INDEX idx_evidence_sources_ingested_at ON evidence_sources (ingested_at);
-- Expression index for common provenance lookups (session_id)
CREATE INDEX idx_evidence_sources_session
    ON evidence_sources ((provenance ->> 'session_id'))
    WHERE provenance ? 'session_id';

-- ── Ingestion checkpoints (one per ledger) ─────────────────────────

CREATE TABLE ingestion_checkpoints (
    ledger_path_hash TEXT PRIMARY KEY,
    last_sequence    INTEGER NOT NULL DEFAULT 0,
    last_event_id    TEXT NOT NULL DEFAULT '',
    records_ingested INTEGER NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ
);

-- ── Ingestion receipts (append-only) ───────────────────────────────

CREATE TABLE ingestion_receipts (
    receipt_id               TEXT PRIMARY KEY,
    evidence_id              TEXT NOT NULL,
    evidence_kind            TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'ingested',
    refusal_reason           TEXT,
    ingested_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    projection_rows_created  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (evidence_id) REFERENCES evidence_sources (evidence_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_ingestion_receipts_status ON ingestion_receipts (status);
CREATE INDEX idx_ingestion_receipts_ingested_at ON ingestion_receipts (ingested_at);

-- ── Projection build records ───────────────────────────────────────

CREATE TABLE projection_builds (
    receipt_id              TEXT PRIMARY KEY,
    projection_name         TEXT NOT NULL,
    source_evidence_count   INTEGER NOT NULL DEFAULT 0,
    rows_built              INTEGER NOT NULL DEFAULT 0,
    built_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence_source_sha256  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_projection_builds_name ON projection_builds (projection_name);
CREATE INDEX idx_projection_builds_built_at ON projection_builds (built_at);

-- ── Rebuild receipts ───────────────────────────────────────────────

CREATE TABLE rebuild_receipts (
    receipt_id      TEXT PRIMARY KEY,
    projection_name TEXT NOT NULL,
    rows_before     INTEGER NOT NULL DEFAULT 0,
    rows_after      INTEGER NOT NULL DEFAULT 0,
    rebuilt_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deterministic   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_rebuild_receipts_name ON rebuild_receipts (projection_name);
CREATE INDEX idx_rebuild_receipts_rebuilt_at ON rebuild_receipts (rebuilt_at);

-- ── Operational snapshots (service authority/degradation) ──────────

CREATE TABLE operational_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    snapshot_kind   TEXT NOT NULL,
    snapshot_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ttl_seconds     INTEGER NOT NULL DEFAULT 3600
);

CREATE INDEX idx_operational_snapshots_kind ON operational_snapshots (snapshot_kind);
CREATE INDEX idx_operational_snapshots_captured_at ON operational_snapshots (captured_at);

-- ── Notification channels registry ─────────────────────────────────

CREATE TABLE notify_channels (
    channel_name    TEXT PRIMARY KEY,
    description     TEXT NOT NULL DEFAULT '',
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_notified_at TIMESTAMPTZ
);

-- ── Initialize schema version ──────────────────────────────────────

INSERT INTO _schema_version (schema_name, current_version, last_migration_id, last_applied_at, schema_hash)
VALUES ('{schema_name}', 1, '001_initial_schema', now(), '{sql_hash}');

COMMIT;

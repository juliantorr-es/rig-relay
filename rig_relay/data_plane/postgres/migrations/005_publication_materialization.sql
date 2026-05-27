-- Migration 005: Publication History Materialization Tables
--
-- Creates operational PostgreSQL tables for materializing Publication
-- (T1.2) preview evidence. Materializes preview receipts and reconstruction
-- status from the append-only publication_preview_evidence.v1.jsonl ledger.
--
-- Tables:
--   publication_preview_receipts  — Materialized preview evidence receipts
--   publication_reconstruction    — Ledger reconstruction state
--   publication_builds            — Materialization build receipts
--
-- Content-light: SHA256 digests only. No raw HTML, file contents, or secrets.
-- Deployment readiness is always tracked as false for preview-only evidence.
-- Authority: PostgreSQL is a disposable read-side projection.

BEGIN;

SET search_path TO {schema_name};

-- ── Publication preview receipts ─────────────────────────────────────

CREATE TABLE publication_preview_receipts (
    receipt_id               TEXT PRIMARY KEY,
    compiled_at              TIMESTAMPTZ NOT NULL,
    compilation_successful   BOOLEAN NOT NULL DEFAULT FALSE,
    profile_candidate_digest TEXT NOT NULL DEFAULT '',
    result_digest            TEXT NOT NULL DEFAULT '',
    refusal_code             TEXT,
    refusal_reasons          TEXT[] NOT NULL DEFAULT '{}',
    safety_passed            BOOLEAN NOT NULL DEFAULT FALSE,
    deployment_ready         BOOLEAN NOT NULL DEFAULT FALSE,
    preview_only             BOOLEAN NOT NULL DEFAULT TRUE,
    evidence_digest          TEXT NOT NULL DEFAULT '',
    operation_id             TEXT NOT NULL DEFAULT '',
    source_event_id          TEXT NOT NULL DEFAULT '',
    source_event_digest      TEXT NOT NULL DEFAULT '',
    provenance_class         TEXT NOT NULL DEFAULT 'canonical_fact'
        CHECK (provenance_class IN (
            'canonical_fact', 'derived_projection', 'corrupt_untrusted',
            'refused', 'missing'
        )),
    authority_state          TEXT NOT NULL DEFAULT 'canonical_live'
        CHECK (authority_state IN (
            'canonical_live', 'degraded', 'controlled_boundary',
            'missing', 'corrupt', 'stale', 'refused'
        )),
    content_light_guarantee  BOOLEAN NOT NULL DEFAULT TRUE,
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pub_preview_success
    ON publication_preview_receipts (compilation_successful, compiled_at DESC);

CREATE INDEX idx_pub_preview_refusal
    ON publication_preview_receipts (refusal_code)
    WHERE refusal_code IS NOT NULL;

CREATE INDEX idx_pub_preview_safety
    ON publication_preview_receipts (safety_passed, compiled_at DESC);

CREATE INDEX idx_pub_preview_operation
    ON publication_preview_receipts (operation_id)
    WHERE operation_id != '';

CREATE INDEX idx_pub_preview_compiled
    ON publication_preview_receipts (compiled_at DESC);

-- ── Publication reconstruction state ─────────────────────────────────

CREATE TABLE publication_reconstruction (
    ledger_path_hash         TEXT PRIMARY KEY,
    total_rows               INTEGER NOT NULL DEFAULT 0,
    valid_rows               INTEGER NOT NULL DEFAULT 0,
    corrupt_rows             INTEGER NOT NULL DEFAULT 0,
    corrupt_lines            INTEGER[] NOT NULL DEFAULT '{}',
    corruption_detected      BOOLEAN NOT NULL DEFAULT FALSE,
    authoritative            BOOLEAN NOT NULL DEFAULT FALSE,
    reconstruction_refused   BOOLEAN NOT NULL DEFAULT FALSE,
    last_reconstructed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reconstruction_warnings  TEXT[] NOT NULL DEFAULT '{}',
    source_schema_version    TEXT NOT NULL DEFAULT '',
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Publication build receipts ───────────────────────────────────────

CREATE TABLE publication_builds (
    receipt_id               TEXT PRIMARY KEY,
    source_receipt_count      INTEGER NOT NULL DEFAULT 0,
    receipts_built           INTEGER NOT NULL DEFAULT 0,
    successful_count          INTEGER NOT NULL DEFAULT 0,
    refused_count             INTEGER NOT NULL DEFAULT 0,
    safety_failed_count       INTEGER NOT NULL DEFAULT 0,
    corrupt_receipt_count     INTEGER NOT NULL DEFAULT 0,
    reconstruction_healthy    BOOLEAN NOT NULL DEFAULT FALSE,
    built_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence_source_sha256    TEXT NOT NULL DEFAULT '',
    deterministic             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_pub_builds_time
    ON publication_builds (built_at DESC);

-- ── Bump schema version ──────────────────────────────────────────────

UPDATE _schema_version
SET current_version = 5,
    last_migration_id = '005_publication_materialization',
    last_applied_at = now(),
    schema_hash = '{sql_hash}'
WHERE schema_name = '{schema_name}';

COMMIT;

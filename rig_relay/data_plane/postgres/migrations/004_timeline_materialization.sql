-- Migration 004: Investigation Timeline Materialization Table
--
-- Creates the operational PostgreSQL table for materializing Investigation
-- Timeline (T4.2) events. Follows the typed PostgresTimelineProjection
-- contract published by T4.2 (rig_relay/investigation_timeline/_pg_contract.py).
--
-- Table:
--   timeline_events  — Normalized timeline events with degradation tracking
--
-- Content-light: SHA256 digests only. No raw prompts, file contents,
-- secrets, or raw paths. All rows rebuildable from canonical evidence
-- (observability.jsonl, events.jsonl, publication_preview_evidence.v1.jsonl,
-- etc.).
--
-- Authority: PostgreSQL is a disposable read-side projection. Canonical
-- evidence ledgers remain the sole authority.

BEGIN;

SET search_path TO {schema_name};

-- ── Investigation timeline events ────────────────────────────────────

CREATE TABLE timeline_events (
    event_id                 TEXT PRIMARY KEY,
    timeline_sequence        INTEGER NOT NULL,
    observed_at              TIMESTAMPTZ NOT NULL,
    event_kind               TEXT NOT NULL,
    source_domain            TEXT NOT NULL,
    source_event_id          TEXT NOT NULL DEFAULT '',
    source_digest            TEXT NOT NULL DEFAULT '',
    source_sequence          INTEGER,
    authority_classification TEXT NOT NULL DEFAULT 'canonical_live'
        CHECK (authority_classification IN (
            'canonical_live', 'canonical_degraded', 'controlled_boundary',
            'fixture_deferred', 'missing', 'stale', 'corrupt', 'contradictory'
        )),
    degradation_detail       TEXT NOT NULL DEFAULT '',
    session_id               TEXT NOT NULL DEFAULT '',
    project_id               TEXT NOT NULL DEFAULT '',
    investigation_id         TEXT NOT NULL DEFAULT '',
    parent_session_id        TEXT,
    task_id                  TEXT,
    operation_id             TEXT NOT NULL DEFAULT '',
    outcome                  TEXT NOT NULL DEFAULT '',
    status                   TEXT NOT NULL DEFAULT '',
    latency_ms               DOUBLE PRECISION,
    path_count               INTEGER,
    artifact_kind            TEXT,
    artifact_sha256          TEXT,
    commit_sha               TEXT,
    refusal_code             TEXT,
    producer_digest          TEXT NOT NULL DEFAULT '',
    producer_digest_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_class       TEXT NOT NULL DEFAULT 'parsed_unverified'
        CHECK (verification_class IN (
            'verified_canonical', 'parsed_unverified', 'canonical_degraded',
            'corrupt', 'unsupported', 'missing'
        )),
    content_light_guarantee  BOOLEAN NOT NULL DEFAULT TRUE,
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes (per T4.2 contract: 12 index requirements) ───────────────

CREATE INDEX idx_timeline_events_sequence
    ON timeline_events (timeline_sequence);

CREATE INDEX idx_timeline_events_observed_at
    ON timeline_events (observed_at DESC);

CREATE INDEX idx_timeline_events_event_kind
    ON timeline_events (event_kind);

CREATE INDEX idx_timeline_events_authority
    ON timeline_events (authority_classification);

CREATE INDEX idx_timeline_events_session
    ON timeline_events (session_id, observed_at DESC);

CREATE INDEX idx_timeline_events_investigation
    ON timeline_events (investigation_id, observed_at DESC)
    WHERE investigation_id != '';

CREATE INDEX idx_timeline_events_project
    ON timeline_events (project_id, observed_at DESC)
    WHERE project_id != '';

CREATE INDEX idx_timeline_events_outcome
    ON timeline_events (outcome)
    WHERE outcome != '';

CREATE INDEX idx_timeline_events_refusal
    ON timeline_events (refusal_code)
    WHERE refusal_code IS NOT NULL;

CREATE INDEX idx_timeline_events_verification
    ON timeline_events (verification_class);

CREATE INDEX idx_timeline_events_operation
    ON timeline_events (operation_id)
    WHERE operation_id != '';

CREATE INDEX idx_timeline_events_kind_time
    ON timeline_events (event_kind, observed_at DESC);

-- ── Timeline build receipts ──────────────────────────────────────────

CREATE TABLE timeline_builds (
    receipt_id               TEXT PRIMARY KEY,
    source_event_count        INTEGER NOT NULL DEFAULT 0,
    events_built             INTEGER NOT NULL DEFAULT 0,
    verified_canonical_count  INTEGER NOT NULL DEFAULT 0,
    canonical_degraded_count  INTEGER NOT NULL DEFAULT 0,
    corrupt_count             INTEGER NOT NULL DEFAULT 0,
    unsupported_count         INTEGER NOT NULL DEFAULT 0,
    missing_count             INTEGER NOT NULL DEFAULT 0,
    contradictory_count       INTEGER NOT NULL DEFAULT 0,
    stale_count               INTEGER NOT NULL DEFAULT 0,
    built_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence_source_sha256    TEXT NOT NULL DEFAULT '',
    deterministic             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_timeline_builds_time
    ON timeline_builds (built_at DESC);

-- ── Bump schema version ──────────────────────────────────────────────

UPDATE _schema_version
SET current_version = 4,
    last_migration_id = '004_timeline_materialization',
    last_applied_at = now(),
    schema_hash = '{sql_hash}'
WHERE schema_name = '{schema_name}';

COMMIT;

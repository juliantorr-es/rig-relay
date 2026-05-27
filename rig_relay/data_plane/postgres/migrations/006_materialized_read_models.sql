-- Migration 006: Materialized Read Models for Gridline Querying
--
-- Creates materialized views over the domain materialization tables as
-- nearest-useful PostgreSQL read models for future Gridline consumption.
--
-- Views:
--   mv_repository_estate_overview  — Aggregated repository estate summary
--   mv_workspace_status_summary    — Per-workspace-instance status
--   mv_verified_timeline_summary   — Verified/degraded timeline counts
--   mv_publication_preview_summary — Publication preview outcome summary
--
-- Refresh behavior:
--   These are NOT refreshed automatically. Callers must invoke
--   REFRESH MATERIALIZED VIEW with CONCURRENTLY if a unique index exists.
--   The views are disposable read-side projections — they can be dropped
--   and recreated from the underlying operational tables at any time.
--
-- Authority: Materialized views are never canonical evidence. They are
-- derived from the operational tables which are themselves derived from
-- canonical evidence ledgers. Rebuild equivalence is proven by comparing
-- view contents against the underlying operational rows.

BEGIN;

SET search_path TO {schema_name};

-- ── Repository estate overview ───────────────────────────────────────

CREATE MATERIALIZED VIEW mv_repository_estate_overview AS
SELECT
    r.repository_hash,
    r.repository_label,
    r.repository_kind,
    r.authority_state,
    r.latest_observation_at,
    COUNT(w.instance_id)                               AS workspace_instance_count,
    COUNT(w.instance_id) FILTER (
        WHERE (w.dirty_modified + w.dirty_staged + w.dirty_untracked
               + w.dirty_deleted + w.dirty_conflicted) > 0
    )                                                   AS dirty_workspace_count,
    COUNT(w.instance_id) FILTER (WHERE w.is_detached)   AS detached_workspace_count,
    COUNT(o.observation_id)                             AS total_observations,
    COUNT(o.observation_id) FILTER (
        WHERE o.provenance_class = 'corrupt_untrusted'
    )                                                   AS corrupt_observation_count,
    MAX(o.observed_at)                                  AS last_observation_at
FROM registered_repositories r
LEFT JOIN repository_workspace_instances w
    ON r.repository_hash = w.repository_hash
LEFT JOIN repository_observations o
    ON r.repository_hash = o.repository_hash
GROUP BY r.repository_hash, r.repository_label, r.repository_kind,
         r.authority_state, r.latest_observation_at;

CREATE UNIQUE INDEX idx_mv_repo_estate_overview_hash
    ON mv_repository_estate_overview (repository_hash);

-- ── Workspace status summary ─────────────────────────────────────────

CREATE MATERIALIZED VIEW mv_workspace_status_summary AS
SELECT
    w.instance_id,
    w.repository_hash,
    r.repository_label,
    w.workspace_kind,
    w.head_sha,
    w.branch,
    w.is_detached,
    w.is_github_backed,
    (w.dirty_modified + w.dirty_staged + w.dirty_untracked
     + w.dirty_deleted + w.dirty_conflicted)            AS total_dirty,
    w.tracked_file_count,
    w.remote_count,
    w.last_observed_at
FROM repository_workspace_instances w
LEFT JOIN registered_repositories r
    ON w.repository_hash = r.repository_hash;

CREATE UNIQUE INDEX idx_mv_workspace_status_instance
    ON mv_workspace_status_summary (instance_id);

CREATE INDEX idx_mv_workspace_status_repo
    ON mv_workspace_status_summary (repository_hash);

-- ── Verified/degraded timeline summary ───────────────────────────────

CREATE MATERIALIZED VIEW mv_verified_timeline_summary AS
SELECT
    authority_classification,
    verification_class,
    event_kind,
    source_domain,
    COUNT(*)                                            AS event_count,
    COUNT(*) FILTER (WHERE producer_digest_verified)     AS verified_count,
    COUNT(*) FILTER (WHERE NOT producer_digest_verified) AS unverified_count,
    MIN(observed_at)                                    AS first_event_at,
    MAX(observed_at)                                    AS last_event_at
FROM timeline_events
GROUP BY authority_classification, verification_class,
         event_kind, source_domain;

CREATE UNIQUE INDEX idx_mv_timeline_summary_composite
    ON mv_verified_timeline_summary (
        authority_classification, verification_class, event_kind, source_domain
    );

-- ── Publication preview summary ──────────────────────────────────────

CREATE MATERIALIZED VIEW mv_publication_preview_summary AS
SELECT
    compilation_successful,
    safety_passed,
    refusal_code,
    COUNT(*)                                            AS receipt_count,
    COUNT(*) FILTER (WHERE deployment_ready)             AS deployment_ready_count,
    MIN(compiled_at)                                    AS first_compiled_at,
    MAX(compiled_at)                                    AS last_compiled_at
FROM publication_preview_receipts
GROUP BY compilation_successful, safety_passed, refusal_code;

CREATE UNIQUE INDEX idx_mv_pub_preview_summary_composite
    ON mv_publication_preview_summary (
        compilation_successful, safety_passed, refusal_code
    );

-- ── Bump schema version ──────────────────────────────────────────────

UPDATE _schema_version
SET current_version = 6,
    last_migration_id = '006_materialized_read_models',
    last_applied_at = now(),
    schema_hash = '{sql_hash}'
WHERE schema_name = '{schema_name}';

COMMIT;

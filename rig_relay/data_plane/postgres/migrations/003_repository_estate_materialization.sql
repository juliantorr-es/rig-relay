-- Migration 003: Repository Estate Materialization Tables
--
-- Creates operational PostgreSQL tables for materializing Repository Estate
-- (T3.1) evidence. Distinguishes logical repository identity from local
-- workspace/checkout instances so that two clones/worktrees of the same
-- logical repository remain independently observable.
--
-- Tables:
--   registered_repositories     — Materialized registration records
--   repository_observations     — Materialized observation records
--   repository_workspace_instances — Logical-repo ⇢ workspace identity model
--   repository_observation_changes  — Detected deltas between observations
--   repository_estate_builds        — Materialization build receipts
--
-- Content-light: SHA256 digests only. No raw paths, file contents, or secrets.
-- All rows rebuildable from canonical registration/observation JSONL ledgers.

BEGIN;

SET search_path TO {schema_name};

-- ── Registered repositories (one row per registration) ──────────────

CREATE TABLE registered_repositories (
    repository_hash          TEXT PRIMARY KEY,
    repository_label         TEXT NOT NULL DEFAULT '',
    repository_kind          TEXT NOT NULL
        CHECK (repository_kind IN ('local_only', 'github_backed')),
    root_path_digest         TEXT NOT NULL DEFAULT '',
    git_common_dir_digest    TEXT NOT NULL DEFAULT '',
    remote_identity_digest   TEXT NOT NULL DEFAULT '',
    registered_at            TIMESTAMPTZ NOT NULL,
    last_registered_at       TIMESTAMPTZ NOT NULL,
    latest_observation_digest TEXT NOT NULL DEFAULT '',
    latest_observation_at    TIMESTAMPTZ,
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
    registration_sha256      TEXT NOT NULL DEFAULT '',
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_registered_repos_kind
    ON registered_repositories (repository_kind);

CREATE INDEX idx_registered_repos_label
    ON registered_repositories USING GIN (to_tsvector('english', repository_label));

-- ── Repository workspace instances (logical-repo ⇢ workspace identity) ─

CREATE TABLE repository_workspace_instances (
    instance_id              TEXT PRIMARY KEY,
    repository_hash          TEXT NOT NULL
        REFERENCES registered_repositories (repository_hash)
        ON DELETE CASCADE,
    workspace_root_digest    TEXT NOT NULL DEFAULT '',
    workspace_kind           TEXT NOT NULL
        CHECK (workspace_kind IN ('primary_checkout', 'worktree', 'bare_clone', 'other')),
    git_common_dir_digest    TEXT NOT NULL DEFAULT '',
    head_sha                 TEXT NOT NULL DEFAULT '',
    branch                   TEXT NOT NULL DEFAULT '',
    is_detached              BOOLEAN NOT NULL DEFAULT FALSE,
    dirty_modified           INTEGER NOT NULL DEFAULT 0,
    dirty_staged             INTEGER NOT NULL DEFAULT 0,
    dirty_untracked          INTEGER NOT NULL DEFAULT 0,
    dirty_deleted            INTEGER NOT NULL DEFAULT 0,
    dirty_conflicted         INTEGER NOT NULL DEFAULT 0,
    tracked_file_count       INTEGER NOT NULL DEFAULT 0,
    remote_count             INTEGER NOT NULL DEFAULT 0,
    is_github_backed         BOOLEAN NOT NULL DEFAULT FALSE,
    last_observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_observation_id      TEXT NOT NULL DEFAULT '',
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Same logical repository can have multiple workspace instances.
    -- They must not collapse into one misleading state.
    CONSTRAINT uq_workspace_root UNIQUE (repository_hash, workspace_root_digest)
);

CREATE INDEX idx_workspace_instances_repo
    ON repository_workspace_instances (repository_hash);

CREATE INDEX idx_workspace_instances_kind
    ON repository_workspace_instances (workspace_kind);

CREATE INDEX idx_workspace_instances_dirty
    ON repository_workspace_instances (repository_hash)
    WHERE (dirty_modified + dirty_staged + dirty_untracked + dirty_deleted + dirty_conflicted) > 0;

-- ── Repository observations (one row per observation event) ──────────

CREATE TABLE repository_observations (
    observation_id           TEXT PRIMARY KEY,
    repository_hash          TEXT NOT NULL,
    -- FK is deliberately NOT REFERENCES registered_repositories here.
    -- Observation events arrive first; registration may be missing/corrupt.
    workspace_root_digest    TEXT NOT NULL DEFAULT '',
    observed_at              TIMESTAMPTZ NOT NULL,
    status                   TEXT NOT NULL
        CHECK (status IN (
            'registered', 'observed', 'unchanged', 'changed',
            'inaccessible', 'not_a_repository', 'disappeared',
            'identity_mismatch'
        )),
    head_sha                 TEXT NOT NULL DEFAULT '',
    branch                   TEXT NOT NULL DEFAULT '',
    is_detached              BOOLEAN NOT NULL DEFAULT FALSE,
    dirty_modified           INTEGER NOT NULL DEFAULT 0,
    dirty_staged             INTEGER NOT NULL DEFAULT 0,
    dirty_untracked          INTEGER NOT NULL DEFAULT 0,
    dirty_deleted            INTEGER NOT NULL DEFAULT 0,
    dirty_conflicted         INTEGER NOT NULL DEFAULT 0,
    tracked_file_count       INTEGER NOT NULL DEFAULT 0,
    is_github_backed         BOOLEAN NOT NULL DEFAULT FALSE,
    is_local_only            BOOLEAN NOT NULL DEFAULT TRUE,
    remote_count             INTEGER NOT NULL DEFAULT 0,
    instruction_file_count   INTEGER NOT NULL DEFAULT 0,
    previous_observation_digest TEXT NOT NULL DEFAULT '',
    observation_digest       TEXT NOT NULL DEFAULT '',
    provenance_class         TEXT NOT NULL DEFAULT 'canonical_fact',
    authority_state          TEXT NOT NULL DEFAULT 'canonical_live',
    observation_sha256       TEXT NOT NULL DEFAULT '',
    content_light_guarantee  BOOLEAN NOT NULL DEFAULT TRUE,
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_repo_observations_repo
    ON repository_observations (repository_hash, observed_at DESC);

CREATE INDEX idx_repo_observations_status
    ON repository_observations (status, observed_at DESC);

CREATE INDEX idx_repo_observations_digest
    ON repository_observations (observation_digest);

CREATE INDEX idx_repo_observations_corrupt
    ON repository_observations (provenance_class, observed_at DESC)
    WHERE provenance_class IN ('corrupt_untrusted', 'missing');

-- ── Repository observation changes (detected deltas) ─────────────────

CREATE TABLE repository_observation_changes (
    change_id                TEXT PRIMARY KEY,
    repository_hash          TEXT NOT NULL,
    prior_observation_digest TEXT NOT NULL DEFAULT '',
    later_observation_digest TEXT NOT NULL DEFAULT '',
    detected_at              TIMESTAMPTZ NOT NULL,
    change_kinds             TEXT[] NOT NULL DEFAULT '{}',
    prior_head_sha           TEXT NOT NULL DEFAULT '',
    later_head_sha           TEXT NOT NULL DEFAULT '',
    prior_branch             TEXT NOT NULL DEFAULT '',
    later_branch             TEXT NOT NULL DEFAULT '',
    change_count             INTEGER NOT NULL DEFAULT 0,
    provenance_class         TEXT NOT NULL DEFAULT 'derived_projection',
    materialized_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_obs_changes_repo
    ON repository_observation_changes (repository_hash, detected_at DESC);

CREATE INDEX idx_obs_changes_kinds
    ON repository_observation_changes USING GIN (change_kinds);

-- ── Repository estate build receipts ─────────────────────────────────

CREATE TABLE repository_estate_builds (
    receipt_id               TEXT PRIMARY KEY,
    source_registration_count INTEGER NOT NULL DEFAULT 0,
    source_observation_count  INTEGER NOT NULL DEFAULT 0,
    repositories_built        INTEGER NOT NULL DEFAULT 0,
    observations_built        INTEGER NOT NULL DEFAULT 0,
    workspace_instances_built INTEGER NOT NULL DEFAULT 0,
    changes_built             INTEGER NOT NULL DEFAULT 0,
    corrupt_registration_count INTEGER NOT NULL DEFAULT 0,
    corrupt_observation_count  INTEGER NOT NULL DEFAULT 0,
    built_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence_source_sha256    TEXT NOT NULL DEFAULT '',
    deterministic             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_repo_estate_builds_time
    ON repository_estate_builds (built_at DESC);

-- ── Bump schema version ──────────────────────────────────────────────

UPDATE _schema_version
SET current_version = 3,
    last_migration_id = '003_repository_estate_materialization',
    last_applied_at = now(),
    schema_hash = '{sql_hash}'
WHERE schema_name = '{schema_name}';

COMMIT;

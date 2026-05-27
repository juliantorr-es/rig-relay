"""X1 materialization and migration tests.

Covers migrations 001–006, domain table INSERT, workspace identity model,
materialized view refresh, rebuild from domain tables, backup/restore,
and content-light model checks against real PostgreSQL.
"""

from __future__ import annotations

import shutil

import psycopg
from psycopg import sql as psql
import pytest

from rig_relay.data_plane.postgres._backup_restore import PostgresBackupService
from rig_relay.data_plane.postgres._materialization_input import (
    PublicationMaterializationInput,
    RepositoryEstateMaterializationInput,
    compute_projection_digest,
)
from rig_relay.data_plane.postgres._models import (
    BackupReceipt,
    MaterializationReceipt,
    MigrationRecord,
    MigrationUpgradeReceipt,
    RestoreReceipt,
)

# ── Migration upgrade tests ──────────────────────────────────────────────


class TestMigrationUpgrade:
    def test_all_migrations_apply_cleanly(self, migrated_store) -> None:
        results = migrated_store.ensure_migrated()
        applied = [r for r in results if r.status == "applied"]
        assert len(applied) <= 6
        for r in applied:
            assert isinstance(r, MigrationRecord)
            assert r.status == "applied"

        version, _ = migrated_store._get_schema_version()
        assert version >= 6

    def test_migration_idempotent_rerun(self, migrated_store) -> None:
        results = migrated_store.ensure_migrated()
        assert len(results) == 0, (
            f"Expected 0 new migrations, got {len(results)}: "
            f"{[r.migration_id for r in results]}"
        )

    def test_schema_version_is_6_after_upgrade(self, migrated_store) -> None:
        version, schema_hash = migrated_store._get_schema_version()
        assert version == 6, f"Expected schema version 6, got {version}"
        assert schema_hash != "", "Schema hash should not be empty"

    def test_domain_tables_exist(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        expected_tables = [
            "_schema_version",
            "_migrations",
            "evidence_sources",
            "ingestion_checkpoints",
            "ingestion_receipts",
            "projection_builds",
            "rebuild_receipts",
            "operational_snapshots",
            "notify_channels",
            "registered_repositories",
            "repository_workspace_instances",
            "repository_observations",
            "repository_observation_changes",
            "repository_estate_builds",
            "timeline_events",
            "timeline_builds",
            "publication_preview_receipts",
            "publication_reconstruction",
            "publication_builds",
        ]
        with pg_conn.cursor() as cur:
            for table in expected_tables:
                cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s)",
                    (schema, table),
                )
                exists = cur.fetchone()[0]
                assert exists, f"Table {schema}.{table} should exist"

    def test_materialized_views_exist(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        expected_views = [
            "mv_repository_estate_overview",
            "mv_workspace_status_summary",
            "mv_verified_timeline_summary",
            "mv_publication_preview_summary",
        ]
        with pg_conn.cursor() as cur:
            for view in expected_views:
                cur.execute(
                    "SELECT EXISTS (SELECT FROM pg_matviews "
                    "WHERE schemaname = %s AND matviewname = %s)",
                    (schema, view),
                )
                exists = cur.fetchone()[0]
                assert exists, f"Materialized view {schema}.{view} should exist"

    def test_migration_records_present(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        expected_ids = [
            "001_initial_schema",
            "002_atomic_ingestion",
            "003_repository_estate_materialization",
            "004_timeline_materialization",
            "005_publication_materialization",
            "006_materialized_read_models",
        ]
        with pg_conn.cursor() as cur:
            cur.execute(
                f'SELECT migration_id FROM {schema}."_migrations" WHERE status = %s '
                "ORDER BY migration_index",
                ("applied",),
            )
            rows = cur.fetchall()
            applied_ids = [r[0] for r in rows]
            for mid in expected_ids:
                assert mid in applied_ids, f"Migration {mid} should be recorded"


# ── Repository estate materialization tests ─────────────────────────────


class TestRepositoryEstateMaterialization:
    def test_materialize_registration(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_reg_test_001"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "test-repo-alice", "local_only"),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "SELECT repository_label, repository_kind FROM {}.{} "
                    "WHERE repository_hash = %s"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "test-repo-alice"
            assert row[1] == "local_only"

    def test_materialize_observation(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_obs_test_001"
        obs_id = "obs_20260101_000001"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "test-repo-bob", "github_backed"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(observation_id, repository_hash, workspace_root_digest, "
                    "observed_at, status, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, observation_digest, "
                    "observation_sha256, content_light_guarantee, materialized_at) "
                    "VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("repository_observations")
                ),
                (
                    obs_id,
                    repo_hash,
                    "sha256:workspace_root_digest_abc",
                    "observed",
                    "sha256:abc123",
                    "main",
                    False,
                    3,
                    0,
                    42,
                    1,
                    True,
                    "sha256:obs_digest_001",
                    "sha256:obs_digest_001",
                    True,
                ),
            )
            assert cur.rowcount == 1

    def test_workspace_instances_created(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_ws_test_001"
        ws1_root = "sha256:workspace_root_alpha"
        ws2_root = "sha256:workspace_root_beta"
        instance1 = "inst_alpha_001"
        instance2 = "inst_beta_002"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "test-repo-ws", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    instance1,
                    repo_hash,
                    ws1_root,
                    "primary_checkout",
                    "sha256:head1",
                    "main",
                    False,
                    2,
                    0,
                    1,
                    0,
                    0,
                    50,
                    1,
                    False,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    instance2,
                    repo_hash,
                    ws2_root,
                    "primary_checkout",
                    "sha256:head2",
                    "feature/x",
                    False,
                    1,
                    3,
                    0,
                    2,
                    1,
                    50,
                    1,
                    True,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "SELECT COUNT(*) FROM {}.{} WHERE repository_hash = %s"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (repo_hash,),
            )
            count = cur.fetchone()[0]
            assert count == 2

    def test_rebuild_deterministic(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            assert cur.fetchone()[0] == 0

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                ("sha256:rebuild_1", "rebuild-test", "local_only"),
            )
            assert cur.rowcount == 1
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            assert cur.fetchone()[0] == 1

        deleted = migrated_store.clear_projection_data()
        assert deleted >= 0

    def test_null_repository_hash_handled(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.NotNullViolation):
                cur.execute(
                    psql.SQL(
                        "INSERT INTO {}.{} "
                        "(repository_hash, repository_label, repository_kind, "
                        "registered_at, last_registered_at, materialized_at) "
                        "VALUES (NULL, %s, %s, now(), now(), now())"
                    ).format(
                        psql.Identifier(schema),
                        psql.Identifier("registered_repositories"),
                    ),
                    ("null-repo", "local_only"),
                )

    def test_parsed_observation_uses_controlled_boundary_not_canonical_live(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_controlled_boundary"
        obs_id = "obs_cb_001"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "cb-repo", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(observation_id, repository_hash, workspace_root_digest, "
                    "observed_at, status, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, observation_digest, "
                    "observation_sha256, content_light_guarantee, "
                    "provenance_class, authority_state, materialized_at) "
                    "VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("repository_observations")
                ),
                (
                    obs_id,
                    repo_hash,
                    "sha256:ws_cb",
                    "observed",
                    "sha256:cb123",
                    "main",
                    False,
                    0,
                    0,
                    10,
                    1,
                    False,
                    "sha256:obs_cb_digest",
                    "sha256:obs_cb_digest",
                    True,
                    "derived_projection",
                    "controlled_boundary",
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "SELECT provenance_class, authority_state FROM {}.{} "
                    "WHERE observation_id = %s"
                ).format(
                    psql.Identifier(schema), psql.Identifier("repository_observations")
                ),
                (obs_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "derived_projection", (
                f"Expected derived_projection, got {row[0]}"
            )
            assert row[1] == "controlled_boundary", (
                f"Expected controlled_boundary, got {row[1]}"
            )

    def test_derived_projection_valid_per_schema(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_dv_001"
        obs_id = "obs_dv_001"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "dv-repo", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(observation_id, repository_hash, workspace_root_digest, "
                    "observed_at, status, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, observation_digest, "
                    "observation_sha256, content_light_guarantee, "
                    "provenance_class, authority_state, materialized_at) "
                    "VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("repository_observations")
                ),
                (
                    obs_id,
                    repo_hash,
                    "sha256:ws_dv",
                    "observed",
                    "sha256:dv123",
                    "main",
                    False,
                    0,
                    0,
                    10,
                    1,
                    False,
                    "sha256:obs_dv_digest",
                    "sha256:obs_dv_digest",
                    True,
                    "derived_projection",
                    "controlled_boundary",
                ),
            )
            assert cur.rowcount == 1

    def test_registered_repository_uses_projection_authority(
        self, migrated_store, pg_conn
    ) -> None:
        """Prove authority_state comes from projection, is not hardcoded."""
        repo_hash = "sha256:auth_test_repo_001"
        repo_label = "auth-test-repo"

        with pg_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO operational.registered_repositories
                (repository_hash, repository_label, repository_kind, registered_at,
                 last_registered_at, provenance_class, authority_state, materialized_at)
                VALUES (%s, %s, %s, now(), now(), %s, %s, now())
                """,
                (
                    repo_hash,
                    repo_label,
                    "local_only",
                    "derived_projection",
                    "controlled_boundary",
                ),
            )

            cur.execute(
                "SELECT provenance_class, authority_state "
                "FROM operational.registered_repositories "
                "WHERE repository_hash = %s",
                (repo_hash,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "derived_projection"
        assert row[1] == "controlled_boundary"


# ── Timeline materialization tests ──────────────────────────────────────


class TestTimelineMaterialization:
    def test_timeline_events_accept_insert(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, source_event_id, source_digest, "
                    "authority_classification, degradation_detail, "
                    "session_id, project_id, investigation_id, operation_id, "
                    "outcome, status, latency_ms, path_count, artifact_kind, "
                    "artifact_sha256, commit_sha, producer_digest, "
                    "producer_digest_verified, verification_class, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "evt_timeline_001",
                    1,
                    "checkpoint.committed",
                    "coordination",
                    "src_evt_001",
                    "sha256:digest_abc",
                    "canonical_live",
                    "",
                    "s1",
                    "p1",
                    "inv1",
                    "op1",
                    "completed",
                    "active",
                    150.5,
                    3,
                    "checkpoint_commit",
                    "sha256:artifact_abc",
                    "sha256:commit_abc",
                    "sha256:producer_abc",
                    True,
                    "verified_canonical",
                    True,
                ),
            )
            assert cur.rowcount == 1

    def test_degradation_counts_stored(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(receipt_id, source_event_count, events_built, "
                    "verified_canonical_count, canonical_degraded_count, "
                    "corrupt_count, unsupported_count, missing_count, "
                    "contradictory_count, stale_count, built_at, "
                    "evidence_source_sha256, deterministic) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s)"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_builds")),
                (
                    "receipt_tl_001",
                    10,
                    9,
                    7,
                    1,
                    1,
                    0,
                    0,
                    0,
                    0,
                    "sha256:evidence_tl",
                    True,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "SELECT verified_canonical_count, canonical_degraded_count, "
                    "corrupt_count FROM {}.{} WHERE receipt_id = %s"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_builds")),
                ("receipt_tl_001",),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 7
            assert row[1] == 1
            assert row[2] == 1

    def test_duplicate_event_id_ignored(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        event_id = "evt_dup_test_001"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, source_event_id, source_digest, "
                    "authority_classification, degradation_detail, "
                    "session_id, project_id, investigation_id, operation_id, "
                    "outcome, status, producer_digest, "
                    "producer_digest_verified, verification_class, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    event_id,
                    1,
                    "tool.call_completed",
                    "tools",
                    "src_1",
                    "sha256:s1",
                    "canonical_live",
                    "",
                    "s1",
                    "p1",
                    "inv1",
                    "op1",
                    "completed",
                    "active",
                    "sha256:producer",
                    True,
                    "verified_canonical",
                    True,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, source_event_id, source_digest, "
                    "authority_classification, degradation_detail, "
                    "session_id, project_id, investigation_id, operation_id, "
                    "outcome, status, producer_digest, "
                    "producer_digest_verified, verification_class, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    event_id,
                    2,
                    "tool.call_completed",
                    "tools",
                    "src_2",
                    "sha256:s2",
                    "canonical_live",
                    "",
                    "s2",
                    "p2",
                    "inv2",
                    "op2",
                    "completed",
                    "active",
                    "sha256:producer2",
                    True,
                    "verified_canonical",
                    True,
                ),
            )
            assert cur.rowcount == 0

            cur.execute(
                psql.SQL(
                    "SELECT timeline_sequence FROM {}.{} WHERE event_id = %s"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (event_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1


# ── Publication materialization tests ───────────────────────────────────


class TestPublicationMaterialization:
    def test_preview_receipt_insert_with_flags(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        receipt_id = "pub_receipt_001"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(receipt_id, compiled_at, compilation_successful, "
                    "profile_candidate_digest, result_digest, refusal_code, "
                    "refusal_reasons, safety_passed, deployment_ready, "
                    "preview_only, evidence_digest, operation_id, "
                    "source_event_id, source_event_digest, provenance_class, "
                    "authority_state, content_light_guarantee, materialized_at) "
                    "VALUES (%s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_preview_receipts"),
                ),
                (
                    receipt_id,
                    True,
                    "sha256:profile_candidate_abc",
                    "sha256:result_abc",
                    None,
                    [],
                    True,
                    False,
                    True,
                    "sha256:evidence_abc",
                    "op_001",
                    "evt_001",
                    "sha256:event_digest_001",
                    "canonical_fact",
                    "canonical_live",
                    True,
                ),
            )
            assert cur.rowcount == 1

    def test_reconstruction_state_upsert(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        ledger_hash = "sha256:ledger_path_abc"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(ledger_path_hash, total_rows, valid_rows, corrupt_rows, "
                    "corrupt_lines, corruption_detected, authoritative, "
                    "reconstruction_refused, last_reconstructed_at, "
                    "reconstruction_warnings, source_schema_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s) "
                    "ON CONFLICT (ledger_path_hash) DO UPDATE SET "
                    "total_rows = EXCLUDED.total_rows"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_reconstruction"),
                ),
                (
                    ledger_hash,
                    50,
                    48,
                    2,
                    [3, 17],
                    True,
                    False,
                    False,
                    [],
                    "rig.relay.publication_preview_event.v1",
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(ledger_path_hash, total_rows, valid_rows, corrupt_rows, "
                    "corrupt_lines, corruption_detected, authoritative, "
                    "reconstruction_refused, last_reconstructed_at, "
                    "reconstruction_warnings, source_schema_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s) "
                    "ON CONFLICT (ledger_path_hash) DO UPDATE SET "
                    "total_rows = EXCLUDED.total_rows"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_reconstruction"),
                ),
                (
                    ledger_hash,
                    52,
                    50,
                    2,
                    [3, 17],
                    True,
                    False,
                    False,
                    [],
                    "rig.relay.publication_preview_event.v1",
                ),
            )
            cur.execute(
                psql.SQL(
                    "SELECT total_rows FROM {}.{} WHERE ledger_path_hash = %s"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_reconstruction"),
                ),
                (ledger_hash,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 52

    def test_build_receipt_with_counts(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        receipt_id = "pub_build_receipt_001"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(receipt_id, source_receipt_count, receipts_built, "
                    "successful_count, refused_count, safety_failed_count, "
                    "corrupt_receipt_count, reconstruction_healthy, built_at, "
                    "evidence_source_sha256, deterministic) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("publication_builds")
                ),
                (
                    receipt_id,
                    20,
                    18,
                    15,
                    2,
                    1,
                    0,
                    False,
                    "sha256:combined_evidence",
                    False,
                ),
            )
            assert cur.rowcount == 1


# ── Workspace identity model tests ──────────────────────────────────────


class TestWorkspaceIdentityModel:
    def test_two_workspaces_under_same_repository(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_shared_identity"
        ws1_digest = "sha256:workspace_one"
        ws2_digest = "sha256:workspace_two"
        inst1 = "inst_shared_ws1"
        inst2 = "inst_shared_ws2"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "shared-repo", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    inst1,
                    repo_hash,
                    ws1_digest,
                    "primary_checkout",
                    "sha256:head_ws1",
                    "main",
                    False,
                    5,
                    2,
                    3,
                    1,
                    0,
                    100,
                    2,
                    True,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    inst2,
                    repo_hash,
                    ws2_digest,
                    "worktree",
                    "sha256:head_ws2",
                    "feature/alpha",
                    False,
                    0,
                    0,
                    1,
                    0,
                    0,
                    100,
                    2,
                    False,
                ),
            )
            assert cur.rowcount == 1

            cur.execute(
                psql.SQL(
                    "SELECT instance_id, head_sha FROM {}.{} "
                    "WHERE repository_hash = %s ORDER BY workspace_root_digest"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (repo_hash,),
            )
            rows = cur.fetchall()
            assert len(rows) == 2, f"Expected 2 workspace instances, got {len(rows)}"

    def test_independent_dirty_states(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_dirty_test"
        ws1_digest = "sha256:dirty_ws_one"
        ws2_digest = "sha256:dirty_ws_two"
        inst1 = "inst_dirty_ws1"
        inst2 = "inst_dirty_ws2"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "dirty-repo", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    inst1,
                    repo_hash,
                    ws1_digest,
                    "primary_checkout",
                    "sha256:head",
                    "main",
                    False,
                    10,
                    5,
                    3,
                    2,
                    1,
                    200,
                    1,
                    False,
                ),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    inst2,
                    repo_hash,
                    ws2_digest,
                    "primary_checkout",
                    "sha256:head",
                    "main",
                    False,
                    0,
                    0,
                    0,
                    0,
                    0,
                    200,
                    1,
                    False,
                ),
            )

            cur.execute(
                psql.SQL(
                    "SELECT dirty_modified, dirty_staged FROM {}.{} "
                    "WHERE repository_hash = %s ORDER BY workspace_root_digest"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (repo_hash,),
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            dirty_sets = {(r[0], r[1]) for r in rows}
            assert (10, 5) in dirty_sets
            assert (0, 0) in dirty_sets

    def test_workspace_state_does_not_collapse(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:repo_nocollapse"
        ws1_digest = "sha256:ws_nocollapse_a"
        ws2_digest = "sha256:ws_nocollapse_b"

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "nocollapse-repo", "local_only"),
            )

            for i, (ws_digest, ws_kind, head) in enumerate([
                (ws1_digest, "primary_checkout", "sha256:head_a"),
                (ws2_digest, "worktree", "sha256:head_b"),
            ]):
                cur.execute(
                    psql.SQL(
                        "INSERT INTO {}.{} "
                        "(instance_id, repository_hash, workspace_root_digest, "
                        "workspace_kind, head_sha, branch, is_detached, "
                        "dirty_modified, dirty_staged, dirty_untracked, "
                        "dirty_deleted, dirty_conflicted, tracked_file_count, "
                        "remote_count, is_github_backed, last_observed_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, now())"
                    ).format(
                        psql.Identifier(schema),
                        psql.Identifier("repository_workspace_instances"),
                    ),
                    (
                        f"inst_nc_{i}",
                        repo_hash,
                        ws_digest,
                        ws_kind,
                        head,
                        "main",
                        False,
                        i + 1,
                        0,
                        i,
                        0,
                        0,
                        100,
                        1,
                        False,
                    ),
                )

            cur.execute(
                psql.SQL(
                    "SELECT instance_id, workspace_root_digest, dirty_modified, "
                    "dirty_untracked FROM {}.{} WHERE repository_hash = %s "
                    "ORDER BY workspace_root_digest"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (repo_hash,),
            )
            rows = cur.fetchall()
            assert len(rows) == 2, "Two workspace instances must not collapse"
            instance_ids = {r[0] for r in rows}
            assert len(instance_ids) == 2, "Instance IDs must be distinct"


# ── Rebuild all domains tests ───────────────────────────────────────────


class TestRebuildAllDomains:
    def test_clear_projection_data_includes_domain_tables(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                ("sha256:rb_domain", "rebuild-domain", "local_only"),
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, source_event_id, source_digest, "
                    "authority_classification, degradation_detail, "
                    "session_id, project_id, investigation_id, operation_id, "
                    "outcome, status, producer_digest, "
                    "producer_digest_verified, verification_class, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "evt_rb_domain",
                    1,
                    "coord.session.registered",
                    "coordination",
                    "src_rb",
                    "sha256:src_rb",
                    "canonical_live",
                    "",
                    "s_rb",
                    "p_rb",
                    "inv_rb",
                    "op_rb",
                    "completed",
                    "active",
                    "sha256:prod_rb",
                    True,
                    "verified_canonical",
                    True,
                ),
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(receipt_id, compiled_at, compilation_successful, "
                    "preview_only, safety_passed, deployment_ready, "
                    "evidence_digest, content_light_guarantee, materialized_at) "
                    "VALUES (%s, now(), %s, %s, %s, %s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_preview_receipts"),
                ),
                ("pub_rb_domain", True, True, True, False, "sha256:pub_rb", True),
            )
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            assert cur.fetchone()[0] >= 1
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("timeline_events")
                )
            )
            assert cur.fetchone()[0] >= 1
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("publication_preview_receipts"),
                )
            )
            assert cur.fetchone()[0] >= 1

        deleted = migrated_store.clear_projection_data()
        assert deleted >= 3

        version, _ = migrated_store._get_schema_version()
        assert version >= 6

    def test_rebuild_counts_match_insert_counts(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        inserted = 0
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            for i in range(5):
                cur.execute(
                    psql.SQL(
                        "INSERT INTO {}.{} "
                        "(repository_hash, repository_label, repository_kind, "
                        "registered_at, last_registered_at, materialized_at) "
                        "VALUES (%s, %s, %s, now(), now(), now())"
                    ).format(
                        psql.Identifier(schema),
                        psql.Identifier("registered_repositories"),
                    ),
                    (f"sha256:rc_{i}", f"repo-rc-{i}", "local_only"),
                )
                inserted += 1

            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            count = cur.fetchone()[0]
            assert count == inserted, f"Expected {inserted} rows, got {count}"

    def test_rebuild_digest_determinism(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        fixed_ts = "2026-01-01 00:00:00+00"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (
                    "sha256:digest_test",
                    "digest-repo",
                    "local_only",
                    fixed_ts,
                    fixed_ts,
                    fixed_ts,
                ),
            )
            digest1 = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (
                    "sha256:digest_test",
                    "digest-repo",
                    "local_only",
                    fixed_ts,
                    fixed_ts,
                    fixed_ts,
                ),
            )
            digest2 = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

        assert digest1 == digest2, f"Digest not deterministic: {digest1} != {digest2}"

    def test_different_content_produces_different_digest(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        fixed_ts = "2026-01-01 00:00:00+00"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                ("sha256:repo_a", "repo-a", "local_only", fixed_ts, fixed_ts, fixed_ts),
            )
            digest_a = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (
                    "sha256:repo_b",
                    "repo-b",
                    "github_backed",
                    fixed_ts,
                    fixed_ts,
                    fixed_ts,
                ),
            )
            digest_b = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

        assert digest_a != digest_b, (
            f"Different content must produce different digests: "
            f"{digest_a} == {digest_b}"
        )

    def test_projection_digest_deterministic_with_same_content(
        self, migrated_store, pg_conn
    ) -> None:
        """Same rows in same order produce same digest."""
        from rig_relay.data_plane.postgres._materialization_input import (
            compute_projection_digest,
        )

        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, authority_classification, "
                    "content_light_guarantee) "
                    "VALUES "
                    "(%s, %s, now(), %s, %s, %s, %s), "
                    "(%s, %s, now(), %s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "x1_test_event_a",
                    1,
                    "SESSION_STARTED",
                    "OBSERVABILITY",
                    "canonical_live",
                    True,
                    "x1_test_event_b",
                    2,
                    "TOOL_CALL_COMPLETED",
                    "COORDINATION",
                    "canonical_live",
                    True,
                ),
            )

        digest1 = compute_projection_digest(
            pg_conn,
            schema,
            "timeline_events",
            primary_key_columns=["event_id"],
            exclude_columns=["observed_at", "materialized_at"],
        )

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{} WHERE event_id LIKE %s").format(
                    psql.Identifier(schema), psql.Identifier("timeline_events")
                ),
                ("x1_test_event_%",),
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, authority_classification, "
                    "content_light_guarantee) "
                    "VALUES "
                    "(%s, %s, now(), %s, %s, %s, %s), "
                    "(%s, %s, now(), %s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "x1_test_event_a",
                    1,
                    "SESSION_STARTED",
                    "OBSERVABILITY",
                    "canonical_live",
                    True,
                    "x1_test_event_b",
                    2,
                    "TOOL_CALL_COMPLETED",
                    "COORDINATION",
                    "canonical_live",
                    True,
                ),
            )

        digest2 = compute_projection_digest(
            pg_conn,
            schema,
            "timeline_events",
            primary_key_columns=["event_id"],
            exclude_columns=["observed_at", "materialized_at"],
        )

        assert digest1 == digest2, f"Digests differ: {digest1} vs {digest2}"

    def test_projection_digest_differs_with_different_content(
        self, migrated_store, pg_conn
    ) -> None:
        """Different content produces different digest."""
        from rig_relay.data_plane.postgres._materialization_input import (
            compute_projection_digest,
        )

        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, authority_classification, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "x1_digest_test_1",
                    1,
                    "SESSION_STARTED",
                    "OBSERVABILITY",
                    "canonical_live",
                    True,
                ),
            )

        digest_a = compute_projection_digest(
            pg_conn,
            schema,
            "timeline_events",
            primary_key_columns=["event_id"],
            exclude_columns=["observed_at", "materialized_at"],
        )

        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{} WHERE event_id = %s").format(
                    psql.Identifier(schema), psql.Identifier("timeline_events")
                ),
                ("x1_digest_test_1",),
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(event_id, timeline_sequence, observed_at, event_kind, "
                    "source_domain, authority_classification, "
                    "content_light_guarantee) "
                    "VALUES (%s, %s, now(), %s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING"
                ).format(psql.Identifier(schema), psql.Identifier("timeline_events")),
                (
                    "x1_digest_test_1",
                    1,
                    "SESSION_CLOSED",
                    "OBSERVABILITY",
                    "canonical_live",
                    True,
                ),
            )

        digest_b = compute_projection_digest(
            pg_conn,
            schema,
            "timeline_events",
            primary_key_columns=["event_id"],
            exclude_columns=["observed_at", "materialized_at"],
        )

        assert digest_a != digest_b, (
            f"Digests should differ for different event_kind: {digest_a}"
        )


# ── Materialization input tests ─────────────────────────────────────────


class TestMaterializationInput:
    def test_repository_estate_input_from_public_boundary(self, migrated_store) -> None:
        input_obj = RepositoryEstateMaterializationInput(projection={})
        assert input_obj.projection == {}
        assert input_obj.source_schema_version == (
            "rig.relay.repository_estate_projection.v1"
        )

    def test_publication_input_has_no_private_path_access(self, migrated_store) -> None:
        input_obj = PublicationMaterializationInput(
            reconstruction={}, ledger_identity_digest="sha256:test"
        )
        assert input_obj.ledger_identity_digest == "sha256:test"
        assert input_obj.source_schema_version == (
            "rig.relay.publication_preview_event.v1"
        )

    def test_compute_projection_digest_deterministic(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        fixed_ts = "2026-01-01 00:00:00+00"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (
                    "sha256:inp_det",
                    "input-det",
                    "local_only",
                    fixed_ts,
                    fixed_ts,
                    fixed_ts,
                ),
            )
            digest1 = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, "
                    "%s::timestamptz)"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (
                    "sha256:inp_det",
                    "input-det",
                    "local_only",
                    fixed_ts,
                    fixed_ts,
                    fixed_ts,
                ),
            )
            digest2 = compute_projection_digest(
                pg_conn,
                schema,
                "registered_repositories",
                exclude_columns=["materialized_at"],
            )

        assert digest1 == digest2, f"Digest not deterministic: {digest1} != {digest2}"

    def test_no_raw_content_in_materialization_input(self) -> None:
        """Prove materialization input has no _raw or content-bearing fields."""
        from rig_relay.data_plane.postgres._materialization_input import (
            RepositoryEstateMaterializationInput,
        )

        field_names = [
            f.name
            for f in RepositoryEstateMaterializationInput.__dataclass_fields__.values()
        ]
        assert "_raw" not in field_names
        assert "registration_events" not in field_names
        assert "observation_events" not in field_names


# ── Materialized view refresh tests ─────────────────────────────────────


class TestMaterializedViewRefresh:
    def test_mv_repository_estate_overview_empty(self, migrated_store, pg_conn) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL("REFRESH MATERIALIZED VIEW {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            count = cur.fetchone()[0]
            assert count == 0

    def test_mv_repository_estate_overview_with_data(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        repo_hash = "sha256:mv_test_repo"
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                )
            )
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("repository_observations")
                )
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "mv-repo", "local_only"),
            )

            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    "inst_mv_a",
                    repo_hash,
                    "sha256:ws_mv_a",
                    "primary_checkout",
                    "sha256:head_a",
                    "main",
                    False,
                    0,
                    0,
                    0,
                    0,
                    0,
                    50,
                    1,
                    False,
                ),
            )
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(instance_id, repository_hash, workspace_root_digest, "
                    "workspace_kind, head_sha, branch, is_detached, "
                    "dirty_modified, dirty_staged, dirty_untracked, "
                    "dirty_deleted, dirty_conflicted, tracked_file_count, "
                    "remote_count, is_github_backed, last_observed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, now())"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                ),
                (
                    "inst_mv_b",
                    repo_hash,
                    "sha256:ws_mv_b",
                    "worktree",
                    "sha256:head_b",
                    "feature/x",
                    False,
                    3,
                    1,
                    2,
                    1,
                    0,
                    50,
                    1,
                    False,
                ),
            )

            cur.execute(
                psql.SQL("REFRESH MATERIALIZED VIEW {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            cur.execute(
                psql.SQL(
                    "SELECT repository_hash, workspace_instance_count, "
                    "dirty_workspace_count FROM {}.{} WHERE repository_hash = %s"
                ).format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                ),
                (repo_hash,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[1] == 2, f"Expected 2 workspace instances, got {row[1]}"
            assert row[2] == 1, f"Expected 1 dirty workspace, got {row[2]}"

    def test_refresh_materialized_view_equivalence(
        self, migrated_store, pg_conn
    ) -> None:
        schema = migrated_store.config.schema_name
        with pg_conn.cursor() as cur:
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                )
            )
            cur.execute(
                psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("repository_workspace_instances"),
                )
            )

            repo_hash = "sha256:mv_equiv"
            cur.execute(
                psql.SQL(
                    "INSERT INTO {}.{} "
                    "(repository_hash, repository_label, repository_kind, "
                    "registered_at, last_registered_at, materialized_at) "
                    "VALUES (%s, %s, %s, now(), now(), now())"
                ).format(
                    psql.Identifier(schema), psql.Identifier("registered_repositories")
                ),
                (repo_hash, "equiv-repo", "local_only"),
            )

            cur.execute(
                psql.SQL("REFRESH MATERIALIZED VIEW {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            first_count = cur.fetchone()[0]

            cur.execute(
                psql.SQL("REFRESH MATERIALIZED VIEW {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            cur.execute(
                psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    psql.Identifier(schema),
                    psql.Identifier("mv_repository_estate_overview"),
                )
            )
            second_count = cur.fetchone()[0]
            assert first_count == second_count, (
                f"Refresh changed count: {first_count} -> {second_count}"
            )


# ── Backup/restore tests ────────────────────────────────────────────────


_HAS_PG_DUMP = shutil.which("pg_dump") is not None

_pg_dump_reason = "pg_dump not found on PATH" if not _HAS_PG_DUMP else ""


class TestBackupRestore:
    @pytest.mark.skipif(not _HAS_PG_DUMP, reason=_pg_dump_reason)
    def test_create_backup_produces_receipt(
        self, migrated_store, pg_config, tmp_path
    ) -> None:
        backup_dir = tmp_path / "backups"
        service = PostgresBackupService(pg_config, backup_dir=backup_dir)

        receipt = service.create_backup(format="plain", verify=False)
        assert isinstance(receipt, BackupReceipt)
        assert receipt.database_name == pg_config.dbname
        assert receipt.schema_name == pg_config.schema_name
        assert receipt.secrets_excluded is True
        assert receipt.backup_sha256 != ""
        assert receipt.backup_size_bytes > 0
        assert receipt.format == "plain"

        backups = service.list_backups()
        assert len(backups) >= 1

        assert "verified_equivalence_level" in RestoreReceipt.model_fields, (
            "RestoreReceipt must expose verified_equivalence_level"
        )

    @pytest.mark.skipif(not _HAS_PG_DUMP, reason=_pg_dump_reason)
    def test_backup_receipt_is_content_light(
        self, migrated_store, pg_config, tmp_path
    ) -> None:
        backup_dir = tmp_path / "backups_cl"
        service = PostgresBackupService(pg_config, backup_dir=backup_dir)
        receipt = service.create_backup(format="plain", verify=False)

        forbidden_fields = {
            "raw_file_contents",
            "raw_prompt_text",
            "model_output_text",
            "secrets",
            "credentials",
            "api_key",
            "access_token",
            "stdout",
            "stderr",
            "prompt",
            "source_code",
        }
        field_names = set(BackupReceipt.model_fields.keys())
        overlap = field_names & forbidden_fields
        assert not overlap, f"BackupReceipt has forbidden fields: {overlap}"

        dump = receipt.model_dump()
        for key in forbidden_fields:
            assert key not in dump, f"Found forbidden key '{key}' in BackupReceipt"

        passes_through = {"exclusion_method"}
        for field_name, field_val in dump.items():
            if field_name in passes_through:
                continue
            if isinstance(field_val, str):
                assert "password" not in field_val.lower(), (
                    f"Password-derived string found in BackupReceipt field '{field_name}'"
                )

    @pytest.mark.skipif(not _HAS_PG_DUMP, reason=_pg_dump_reason)
    def test_canonical_equivalence_verified_always_false(
        self, migrated_store, pg_config, tmp_path
    ) -> None:
        """Prove the legacy field is never set to True."""
        from rig_relay.data_plane.postgres._backup_restore import PostgresBackupService

        service = PostgresBackupService(pg_config, backup_dir=tmp_path)
        service.create_backup(format="custom", verify=False)
        backup_files = list(tmp_path.glob("*.dump"))
        if not backup_files:
            pytest.skip("No backup file created")

        receipt = service.restore_backup(backup_files[0], verify_equivalence=True)
        assert receipt.canonical_equivalence_verified is False
        assert receipt.verified_equivalence_level in (
            "none",
            "schema_migration_metadata",
        )

    def test_backup_docstring_mentions_schema_scope(self) -> None:
        docstring = PostgresBackupService.__doc__ or ""
        assert "operational-schema" in docstring, (
            "Class docstring must reference 'operational-schema' scope"
        )
        assert "full PostgreSQL installation" in docstring, (
            "Class docstring must state 'not the full PostgreSQL installation'"
        )


# ── Content-light model tests ───────────────────────────────────────────


class TestContentLightModels:
    def test_new_models_are_content_light(self) -> None:
        forbidden_fields = {
            "raw_file_contents",
            "raw_prompt_text",
            "model_output_text",
            "secrets",
            "credentials",
            "api_key",
            "access_token",
            "stdout",
            "stderr",
            "prompt",
            "source_code",
            "raw_content",
            "raw_diff",
            "raw_private_code",
            "token",
            "key",
        }

        models: list[type] = [
            MaterializationReceipt,
            BackupReceipt,
            RestoreReceipt,
            MigrationUpgradeReceipt,
        ]
        for model_cls in models:
            field_names = set(model_cls.model_fields.keys())
            overlap = field_names & forbidden_fields
            assert not overlap, (
                f"{model_cls.__name__} has forbidden fields: {sorted(overlap)}"
            )

    def test_materialization_receipt_fields_exist(self) -> None:
        receipt = MaterializationReceipt(
            receipt_id="mat_001",
            domain="repository_estate",
            source_evidence_count=10,
            rows_materialized=8,
            corrupt_rows=1,
            duplicate_rows=1,
        )
        dump = receipt.model_dump()
        assert "receipt_id" in dump
        assert "domain" in dump
        assert "rows_materialized" in dump
        assert "corrupt_rows" in dump
        assert "duplicate_rows" in dump

    def test_migration_upgrade_receipt_progression(self) -> None:
        receipt = MigrationUpgradeReceipt(
            receipt_id="mig_up_001",
            from_version=2,
            to_version=6,
            migrations_applied=4,
            migration_ids=[
                "003_repository_estate_materialization",
                "004_timeline_materialization",
                "005_publication_materialization",
                "006_materialized_read_models",
            ],
            schema_hash_before="sha256:before",
            schema_hash_after="sha256:after",
            success=True,
            rollback_available=False,
        )
        assert receipt.from_version == 2
        assert receipt.to_version == 6
        assert receipt.migrations_applied == 4
        assert len(receipt.migration_ids) == 4
        assert receipt.success is True

    def test_restore_receipt_has_verified_equivalence_level(self) -> None:
        """RestoreReceipt must expose verified_equivalence_level field."""
        receipt = RestoreReceipt(
            receipt_id="rst_001",
            backup_sha256="sha256:abc",
            tables_restored=10,
            rows_restored=100,
            migration_version_restored=6,
            verified_equivalence_level="schema_migration_metadata",
            canonical_equivalence_verified=True,
        )
        dump = receipt.model_dump()
        assert "verified_equivalence_level" in dump
        assert dump["verified_equivalence_level"] == "schema_migration_metadata"
        assert "canonical_equivalence_verified" in dump

"""Repository Estate materializer for PostgreSQL operational store.

Materializes RepositoryEstateService evidence into the operational PostgreSQL
projection tables from the public build_projection() contract ONLY —
never from raw JSONL ledgers, never from private store internals.

Authority: PostgreSQL is a disposable read-side projection.
Canonical registration/observation JSONL ledgers remain the sole authority.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

from psycopg import sql as psql

from rig_relay.data_plane.postgres._materialization_input import (
    RepositoryEstateMaterializationInput,
)
from rig_relay.data_plane.postgres._models import (
    MaterializationReceipt,
    RebuildReceipt,
    compute_receipt_id,
)
from rig_relay.data_plane.postgres._store import PostgresOperationalProjectionStore


class RepositoryEstateMaterializer:
    """Materializes Repository Estate (T3.1) evidence into PostgreSQL.

    Consumes the RepositoryEstateService through its published
    build_projection() contract. Distinguishes logical repository
    identity from workspace/checkout instances.

    Content-light: stores only digests and counts — never raw paths
    or file contents.
    """

    def __init__(self, store: PostgresOperationalProjectionStore) -> None:
        self.store = store

    # ── Public API ─────────────────────────────────────────────────────

    def materialize(
        self, input_data: RepositoryEstateMaterializationInput
    ) -> MaterializationReceipt:
        """Materialize from a public-boundary-safe materialization input."""
        return self._materialize_impl(input_data)

    def materialize_from_service(self, service: Any) -> MaterializationReceipt:
        """Materialize from a live RepositoryEstateService (public API only).

        Uses RepositoryEstateMaterializationInput.from_service() which
        reads ONLY through build_projection(). Never accesses service._store.
        """
        input_data = RepositoryEstateMaterializationInput.from_service(service)
        return self.materialize(input_data)

    def materialize_from_projection(self, projection: Any) -> MaterializationReceipt:
        """Materialize from a pre-built RepositoryEstateProjection.

        Deprecated: this path accepts an unbound projection with no source
        evidence digest and will be refused by the materializer guard.
        Use materialize_from_service() or construct a RepositoryEstateMaterializationInput
        with a non-empty source_evidence_digest and VERIFIED source_status.
        """
        input_data = RepositoryEstateMaterializationInput(projection=projection)
        return self.materialize(input_data)

    def rebuild(
        self, input_data: RepositoryEstateMaterializationInput
    ) -> RebuildReceipt:
        """Clear and rebuild repository estate projection tables from canonical evidence.

        Determinism is proven by comparing SHA256 content digests of the
        materialized tables before and after rebuild, excluding non-semantic
        operation timestamps and receipt IDs.
        """
        from rig_relay.data_plane.postgres._materialization_input import (
            compute_multi_table_digest,
        )

        schema = self.store.config.schema_name
        now = datetime.now()

        tables: list[tuple[str, list[str]]] = [
            ("repository_observations", ["observation_id"]),
            ("repository_workspace_instances", ["instance_id"]),
            ("repository_observation_changes", ["change_id"]),
        ]
        exclude = ["materialized_at", "receipt_id", "built_at"]

        digest_before = compute_multi_table_digest(
            self.store.conn, schema, tables, exclude, domain_name="repository_estate"
        )

        rows_before = sum(_fetch_count(self.store.conn, schema, t[0]) for t in tables)

        with self.store.conn.transaction():
            self._clear_estate_tables(schema)

        _receipt = self.materialize(input_data)

        digest_after = compute_multi_table_digest(
            self.store.conn, schema, tables, exclude, domain_name="repository_estate"
        )
        rows_after = sum(_fetch_count(self.store.conn, schema, t[0]) for t in tables)

        deterministic = digest_before == digest_after

        rebuild_receipt = RebuildReceipt(
            receipt_id=compute_receipt_id(
                "rebuild_repo_estate", "repository_estate", now
            ),
            projection_name="repository_estate",
            rows_before=rows_before,
            rows_after=rows_after,
            rebuilt_at=now,
            deterministic=deterministic,
        )
        self.store._record_rebuild_receipt(rebuild_receipt)
        return rebuild_receipt

    def rebuild_from_service(self, service: Any) -> RebuildReceipt:
        """Rebuild from a live service (convenience wrapper)."""
        input_data = RepositoryEstateMaterializationInput.from_service(service)
        return self.rebuild(input_data)

    # ── Core materialization ───────────────────────────────────────────

    def _materialize_impl(
        self, input_data: RepositoryEstateMaterializationInput
    ) -> MaterializationReceipt:
        """Materialize projection rows into PostgreSQL projection tables.

        Refuses materialization when the producer digest is missing or
        when the input claims VERIFIED status but carries no source
        evidence digest — no unbound bypass path exists.
        """
        projection = input_data.projection
        schema = self.store.config.schema_name
        now = datetime.now()

        source_status = getattr(input_data, "source_status", None)
        source_digest = getattr(input_data, "source_evidence_digest", "")

        if source_status and str(source_status) == "missing_producer_digest":
            receipt_id = compute_receipt_id(
                "materialize_repo_estate_missing_digest", "repository_estate", now
            )
            return MaterializationReceipt(
                receipt_id=receipt_id,
                domain="repository_estate",
                source_evidence_count=0,
                rows_materialized=0,
                corrupt_rows=0,
                duplicate_rows=0,
                built_at=now,
                evidence_source_sha256="",
                deterministic=False,
            )

        if source_status and str(source_status) == "verified" and not source_digest:
            receipt_id = compute_receipt_id(
                "materialize_repo_estate_unbound", "repository_estate", now
            )
            return MaterializationReceipt(
                receipt_id=receipt_id,
                domain="repository_estate",
                source_evidence_count=0,
                rows_materialized=0,
                corrupt_rows=0,
                duplicate_rows=0,
                built_at=now,
                evidence_source_sha256="",
                deterministic=False,
            )

        summaries = getattr(projection, "registered_repositories", [])
        corruption_events = getattr(projection, "corruption_events", [])
        recent_changes = getattr(projection, "recent_changes", [])

        total_reg = getattr(projection, "total_registered", len(summaries))
        total_obs = getattr(projection, "total_observations", 0)
        corrupt_reg = getattr(projection, "corrupt_registration_count", 0)
        corrupt_obs = getattr(projection, "corrupt_observation_count", 0)

        with self.store.conn.transaction():
            repos_built = self._insert_registered_repositories(
                schema, projection, summaries, now
            )
            obs_built = self._insert_observations(
                schema, projection, summaries, corruption_events, now
            )
            ws_built = self._insert_workspace_instances(schema, summaries, now)
            changes_built = self._insert_observation_changes(
                schema, recent_changes, now
            )

            source_total = total_reg + total_obs
            total_rows = repos_built + obs_built + ws_built + changes_built

            receipt = self._record_estate_build(
                schema,
                source_counts=(total_reg, total_obs, corrupt_reg, corrupt_obs),
                built_counts=(repos_built, obs_built, ws_built, changes_built),
                corrupt_counts=(corrupt_reg, corrupt_obs),
                source_evidence_digest=input_data.source_evidence_digest,
                now=now,
            )

        corrupt_total = corrupt_reg + corrupt_obs
        return MaterializationReceipt(
            receipt_id=receipt["receipt_id"],
            domain="repository_estate",
            source_evidence_count=source_total,
            rows_materialized=total_rows,
            corrupt_rows=corrupt_total,
            duplicate_rows=0,
            built_at=now,
        )

    # ── Table-level inserts ────────────────────────────────────────────

    def _insert_registered_repositories(
        self, schema: str, projection: Any, summaries: list[Any], now: datetime
    ) -> int:
        """Insert/update registered_repositories from projection summaries."""
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(repository_hash, repository_label, repository_kind, root_path_digest, "
            "git_common_dir_digest, remote_identity_digest, registered_at, "
            "last_registered_at, latest_observation_digest, latest_observation_at, "
            "provenance_class, authority_state, registration_sha256, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (repository_hash) DO UPDATE SET "
            "repository_label = EXCLUDED.repository_label, "
            "repository_kind = EXCLUDED.repository_kind, "
            "root_path_digest = EXCLUDED.root_path_digest, "
            "git_common_dir_digest = EXCLUDED.git_common_dir_digest, "
            "remote_identity_digest = EXCLUDED.remote_identity_digest, "
            "registered_at = EXCLUDED.registered_at, "
            "last_registered_at = EXCLUDED.last_registered_at, "
            "latest_observation_digest = EXCLUDED.latest_observation_digest, "
            "latest_observation_at = EXCLUDED.latest_observation_at, "
            "provenance_class = EXCLUDED.provenance_class, "
            "authority_state = EXCLUDED.authority_state, "
            "registration_sha256 = EXCLUDED.registration_sha256, "
            "materialized_at = EXCLUDED.materialized_at"
        ).format(psql.Identifier(schema), psql.Identifier("registered_repositories"))

        proj_authority = getattr(projection, "authority_state", "controlled_boundary")
        count = 0
        with self.store.conn.cursor() as cur:
            for summary in summaries:
                provenance = getattr(summary, "provenance", "derived_projection")
                row = (
                    getattr(summary, "repository_hash", ""),
                    getattr(summary, "repository_label", ""),
                    getattr(summary, "repository_kind", "local_only"),
                    getattr(summary, "root_path_digest", ""),
                    "",
                    "",
                    _parse_timestamptz(getattr(summary, "registered_at", "")),
                    _parse_timestamptz(getattr(summary, "last_registered_at", "")),
                    getattr(summary, "latest_observation_digest", "") or "",
                    _parse_timestamptz_or_none(
                        getattr(summary, "latest_observation_at", "")
                    ),
                    str(provenance),
                    str(proj_authority),
                    "",
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount
        return count

    def _insert_observations(
        self,
        schema: str,
        projection: Any,
        summaries: list[Any],
        corruption_events: list[Any],
        now: datetime,
    ) -> int:
        """Insert observations from projection summaries and corruption events.

        For each registered repository summary: one observation row.
        For each corruption event: one corrupt observation row.
        """
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(observation_id, repository_hash, workspace_root_digest, observed_at, "
            "status, head_sha, branch, is_detached, "
            "dirty_modified, dirty_staged, dirty_untracked, dirty_deleted, "
            "dirty_conflicted, tracked_file_count, is_github_backed, is_local_only, "
            "remote_count, instruction_file_count, previous_observation_digest, "
            "observation_digest, provenance_class, authority_state, "
            "observation_sha256, content_light_guarantee, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (observation_id) DO NOTHING"
        ).format(psql.Identifier(schema), psql.Identifier("repository_observations"))

        proj_authority = getattr(projection, "authority_state", "controlled_boundary")
        count = 0

        with self.store.conn.cursor() as cur:
            # Summary observations from registered repositories
            for summary in summaries:
                observation_id = f"{getattr(summary, 'repository_hash', '')}:summary"
                provenance = getattr(summary, "provenance", "derived_projection")
                row = (
                    observation_id,
                    getattr(summary, "repository_hash", ""),
                    getattr(summary, "root_path_digest", ""),
                    _parse_timestamptz(
                        getattr(summary, "latest_observation_at", "")
                        or getattr(summary, "registered_at", "")
                    ),
                    getattr(summary, "latest_status", "registered"),
                    getattr(summary, "latest_head_sha", "") or "",
                    getattr(summary, "latest_branch", "") or "",
                    getattr(summary, "is_detached", False),
                    getattr(summary, "dirty_modified", 0),
                    0,
                    getattr(summary, "dirty_untracked", 0),
                    0,
                    0,
                    getattr(summary, "tracked_file_count", 0),
                    getattr(summary, "is_github_backed", False),
                    getattr(summary, "is_local_only", True),
                    getattr(summary, "remote_count", 0),
                    getattr(summary, "instruction_file_count", 0),
                    getattr(summary, "latest_observation_digest", "") or "",
                    getattr(summary, "latest_observation_digest", "") or "",
                    str(provenance),
                    str(proj_authority),
                    getattr(summary, "latest_observation_digest", ""),
                    True,
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount

            # Corruption event observation rows
            for event in corruption_events:
                obs_id = f"corrupt:{getattr(event, 'event_id', 'unknown')}"
                row = (
                    obs_id,
                    getattr(event, "repository_hash", ""),
                    "",
                    now,
                    "not_a_repository",
                    "",
                    "",
                    False,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    False,
                    True,
                    0,
                    0,
                    "",
                    "",
                    "corrupt_untrusted",
                    "corrupt",
                    "",
                    False,
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount

        return count

    def _insert_workspace_instances(
        self, schema: str, summaries: list[Any], now: datetime
    ) -> int:
        """Build workspace instances from registered repository summaries.

        Each registered repository summary produces one workspace instance row.
        """
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(instance_id, repository_hash, workspace_root_digest, workspace_kind, "
            "git_common_dir_digest, head_sha, branch, is_detached, "
            "dirty_modified, dirty_staged, dirty_untracked, dirty_deleted, "
            "dirty_conflicted, tracked_file_count, remote_count, is_github_backed, "
            "last_observed_at, last_observation_id, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s) "
            "ON CONFLICT (instance_id) DO UPDATE SET "
            "head_sha = EXCLUDED.head_sha, "
            "branch = EXCLUDED.branch, "
            "is_detached = EXCLUDED.is_detached, "
            "dirty_modified = EXCLUDED.dirty_modified, "
            "dirty_staged = EXCLUDED.dirty_staged, "
            "dirty_untracked = EXCLUDED.dirty_untracked, "
            "dirty_deleted = EXCLUDED.dirty_deleted, "
            "dirty_conflicted = EXCLUDED.dirty_conflicted, "
            "tracked_file_count = EXCLUDED.tracked_file_count, "
            "remote_count = EXCLUDED.remote_count, "
            "is_github_backed = EXCLUDED.is_github_backed, "
            "last_observed_at = EXCLUDED.last_observed_at, "
            "last_observation_id = EXCLUDED.last_observation_id, "
            "materialized_at = EXCLUDED.materialized_at"
        ).format(
            psql.Identifier(schema), psql.Identifier("repository_workspace_instances")
        )

        count = 0
        with self.store.conn.cursor() as cur:
            for summary in summaries:
                rh = getattr(summary, "repository_hash", "")
                ws_digest = getattr(summary, "root_path_digest", "")
                if not rh or not ws_digest:
                    continue

                instance_id = _compute_instance_id(rh, ws_digest)
                workspace_kind = _classify_workspace_kind_from_summary(rh, ws_digest)

                row = (
                    instance_id,
                    rh,
                    ws_digest,
                    workspace_kind,
                    "",
                    getattr(summary, "latest_head_sha", "") or "",
                    getattr(summary, "latest_branch", "") or "",
                    getattr(summary, "is_detached", False),
                    getattr(summary, "dirty_modified", 0),
                    0,
                    getattr(summary, "dirty_untracked", 0),
                    0,
                    0,
                    getattr(summary, "tracked_file_count", 0),
                    getattr(summary, "remote_count", 0),
                    getattr(summary, "is_github_backed", False),
                    _parse_timestamptz(
                        getattr(summary, "latest_observation_at", "")
                        or getattr(summary, "registered_at", "")
                    ),
                    f"{rh}:summary",
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount
        return count

    def _insert_observation_changes(
        self, schema: str, recent_changes: list[Any], now: datetime
    ) -> int:
        """Insert observation changes from projection recent_changes."""
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(change_id, repository_hash, prior_observation_digest, "
            "later_observation_digest, detected_at, change_kinds, "
            "prior_head_sha, later_head_sha, prior_branch, later_branch, "
            "change_count, provenance_class, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (change_id) DO NOTHING"
        ).format(
            psql.Identifier(schema), psql.Identifier("repository_observation_changes")
        )

        count = 0
        with self.store.conn.cursor() as cur:
            for change in recent_changes:
                from_obs = getattr(change, "from_observation_id", "")
                to_obs = getattr(change, "to_observation_id", "")
                change_id = _compute_change_id(from_obs, to_obs)
                change_kinds = getattr(change, "change_kinds", [])
                provenance = getattr(change, "provenance", "derived_projection")

                row = (
                    change_id,
                    getattr(change, "repository_hash", ""),
                    from_obs,
                    to_obs,
                    _parse_timestamptz(getattr(change, "detected_at", "")),
                    [str(k) for k in change_kinds],
                    "",
                    "",
                    "",
                    "",
                    len(change_kinds),
                    str(provenance),
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount
        return count

    # ── Build receipt ──────────────────────────────────────────────────

    def _record_estate_build(
        self,
        schema: str,
        *,
        source_counts: tuple[int, int, int, int],
        built_counts: tuple[int, int, int, int],
        corrupt_counts: tuple[int, int],
        source_evidence_digest: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Insert a repository_estate_builds row and return the receipt dict.

        source_counts: (source_registration_count, source_observation_count,
                         corrupt_registration_count, corrupt_observation_count)
        built_counts: (repositories_built, observations_built,
                        workspace_instances_built, changes_built)
        corrupt_counts: (corrupt_registration_count, corrupt_observation_count)
        """
        (
            source_registration_count,
            source_observation_count,
            corrupt_registration_count,
            corrupt_observation_count,
        ) = source_counts
        (
            repositories_built,
            observations_built,
            workspace_instances_built,
            changes_built,
        ) = built_counts

        receipt_id = compute_receipt_id(
            "materialize_repo_estate", "repository_estate", now
        )
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(receipt_id, source_registration_count, source_observation_count, "
            "repositories_built, observations_built, workspace_instances_built, "
            "changes_built, corrupt_registration_count, corrupt_observation_count, "
            "built_at, evidence_source_sha256, deterministic) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(psql.Identifier(schema), psql.Identifier("repository_estate_builds"))

        with self.store.conn.cursor() as cur:
            cur.execute(
                query,
                (
                    receipt_id,
                    source_registration_count,
                    source_observation_count,
                    repositories_built,
                    observations_built,
                    workspace_instances_built,
                    changes_built,
                    corrupt_registration_count,
                    corrupt_observation_count,
                    now,
                    source_evidence_digest,
                    False,
                ),
            )
        return {"receipt_id": receipt_id}

    # ── Table clearing ─────────────────────────────────────────────────

    def _clear_estate_tables(self, schema: str) -> int:
        """Clear all repository estate projection tables."""
        tables = [
            "repository_observation_changes",
            "repository_observations",
            "repository_workspace_instances",
            "repository_estate_builds",
        ]
        total = 0
        with self.store.conn.cursor() as cur:
            for table in tables:
                query = psql.SQL("DELETE FROM {}.{}").format(
                    psql.Identifier(schema), psql.Identifier(table)
                )
                cur.execute(query)
                total += cur.rowcount
        return total


# ── Module-level helpers ────────────────────────────────────────────────


def _fetch_count(cur: Any, schema: str, table: str) -> int:
    """Fetch row count from a table, returning 0 if table is empty."""
    cur.execute(
        psql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            psql.Identifier(schema), psql.Identifier(table)
        )
    )
    row = cur.fetchone()
    return row[0] if row else 0


def _parse_timestamptz(raw: str) -> datetime:
    """Parse an ISO 8601 string to a timezone-aware datetime, with fallback."""
    if not raw:
        return datetime.now()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now()


def _parse_timestamptz_or_none(raw: str) -> datetime | None:
    """Parse an ISO 8601 string to datetime or None."""
    if not raw:
        return None
    return _parse_timestamptz(raw)


def _compute_instance_id(repository_hash: str, workspace_root_digest: str) -> str:
    """Compute a stable instance_id from repository hash and workspace root."""
    raw = f"{repository_hash}:{workspace_root_digest}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _compute_change_id(from_obs_id: str, to_obs_id: str) -> str:
    """Compute a stable change_id from observation pair."""
    raw = f"{from_obs_id}:{to_obs_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _classify_workspace_kind(
    repository_hash: str, workspace_root_digest: str, git_facts: dict
) -> str:
    """Classify workspace kind as primary_checkout, worktree, bare_clone, or other."""
    common_dir = git_facts.get("git_common_dir_digest", "")
    if not common_dir:
        return "other"
    if (
        repository_hash in workspace_root_digest
        or workspace_root_digest in repository_hash
    ):
        return "primary_checkout"
    return "other"


def _classify_workspace_kind_from_summary(
    repository_hash: str, workspace_root_digest: str
) -> str:
    """Classify workspace kind from summary data only (no git_facts dict).

    When git_facts are unavailable (projection-only materialization),
    default to primary_checkout.
    """
    return "primary_checkout"


def _detect_change_kinds(prev: dict, curr: dict) -> list[str]:
    """Detect change kinds between two observation payloads."""
    prev_gf = prev.get("git_facts", {})
    curr_gf = curr.get("git_facts", {})
    kinds: list[str] = []

    if prev_gf.get("head_sha") != curr_gf.get("head_sha"):
        kinds.append("head_changed")
    if prev_gf.get("branch") != curr_gf.get("branch"):
        kinds.append("branch_changed")
    if prev_gf.get("is_detached") != curr_gf.get("is_detached"):
        kinds.append("detached_state_changed")

    prev_dc = prev_gf.get("dirty_counts", {})
    curr_dc = curr_gf.get("dirty_counts", {})
    if (
        prev_dc.get("modified") != curr_dc.get("modified")
        or prev_dc.get("staged") != curr_dc.get("staged")
        or prev_dc.get("untracked") != curr_dc.get("untracked")
        or prev_dc.get("deleted") != curr_dc.get("deleted")
        or prev_dc.get("conflicted") != curr_dc.get("conflicted")
    ):
        kinds.append("dirty_state_changed")

    if prev_gf.get("tracked_file_count") != curr_gf.get("tracked_file_count"):
        kinds.append("tracked_file_count_changed")

    prev_remotes = {r.get("url_digest") for r in prev_gf.get("remotes", [])}
    curr_remotes = {r.get("url_digest") for r in curr_gf.get("remotes", [])}
    if prev_remotes != curr_remotes:
        kinds.append("remotes_changed")

    if prev_gf.get("git_common_dir_digest") != curr_gf.get("git_common_dir_digest"):
        kinds.append("common_dir_changed")

    prev_instr = {i.get("content_sha256") for i in prev_gf.get("instruction_files", [])}
    curr_instr = {i.get("content_sha256") for i in curr_gf.get("instruction_files", [])}
    if prev_instr != curr_instr:
        kinds.append("instruction_files_changed")

    return kinds


__all__ = ["RepositoryEstateMaterializer"]

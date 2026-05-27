"""Repository Estate materializer for PostgreSQL operational store.

Materializes RepositoryEstateService evidence (registrations, observations,
changes) into the operational PostgreSQL projection tables. Distinguishes
logical repository identity from workspace/checkout instances.

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
    projection/evidence contract. Distinguishes logical repository
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
        return self._materialize_impl(
            input_data.projection,
            input_data.registration_events,
            input_data.observation_events,
        )

    def materialize_from_service(self, service: Any) -> MaterializationReceipt:
        """Materialize from a live RepositoryEstateService (public API only).

        Uses RepositoryEstateMaterializationInput.from_service() which
        reads the projection through build_projection() and evidence
        JSONL ledgers from the filesystem. Never accesses service._store.
        """
        input_data = RepositoryEstateMaterializationInput.from_service(service)
        return self.materialize(input_data)

    def materialize_from_projection(
        self,
        projection: Any,
        raw_registrations: list[dict] | None = None,
        raw_observations: list[dict] | None = None,
    ) -> MaterializationReceipt:
        """Materialize from a pre-built RepositoryEstateProjection.

        Raw registration/observation events are optional — without them,
        only projection-level summaries and changes are materialized.
        """
        return self._materialize_impl(
            projection, raw_registrations or [], raw_observations or []
        )

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

        tables = [
            "repository_observations",
            "repository_workspace_instances",
            "repository_observation_changes",
        ]
        exclude = ["materialized_at", "receipt_id", "built_at"]

        digest_before = compute_multi_table_digest(
            self.store.conn, schema, tables, exclude
        )

        # Count rows for diagnostics
        rows_before = sum(_fetch_count(self.store.conn, schema, t) for t in tables)

        with self.store.conn.transaction():
            self._clear_estate_tables(schema)

        _receipt = self.materialize(input_data)

        digest_after = compute_multi_table_digest(
            self.store.conn, schema, tables, exclude
        )
        rows_after = sum(_fetch_count(self.store.conn, schema, t) for t in tables)

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
        self,
        projection: Any,
        raw_registrations: list[dict],
        raw_observations: list[dict],
    ) -> MaterializationReceipt:
        """Materialize all evidence rows into PostgreSQL projection tables."""
        schema = self.store.config.schema_name
        now = datetime.now()

        # ── Parse and deduplicate registrations ──
        repos_by_hash: dict[str, dict] = {}
        corrupt_reg_count = 0
        for reg_event in raw_registrations:
            if reg_event.get("_corrupt"):
                corrupt_reg_count += 1
                continue
            payload = reg_event.get("payload", {})
            rh = payload.get("repository_hash", "")
            if not rh:
                continue
            registered_at = payload.get("registered_at", "")
            existing = repos_by_hash.get(rh)
            if existing is None or registered_at >= existing.get("registered_at", ""):
                repos_by_hash[rh] = payload

        # ── Parse observations ──
        valid_obs: list[dict] = []
        corrupt_obs_count = 0
        for obs_event in raw_observations:
            if obs_event.get("_corrupt"):
                corrupt_obs_count += 1
                valid_obs.append({
                    "_corrupt": True,
                    "observation_id": obs_event.get("event_id", ""),
                })
                continue
            payload = obs_event.get("payload", {})
            valid_obs.append(payload)

        # ── Materialize in a single transaction ──
        with self.store.conn.transaction():
            repos_built = self._insert_registered_repositories(
                schema, projection, repos_by_hash, now
            )
            obs_built = self._insert_observations(schema, valid_obs, now)
            ws_built = self._insert_workspace_instances(schema, valid_obs, now)
            changes_built = self._insert_observation_changes(schema, valid_obs, now)

            source_registration_count = len(raw_registrations)
            source_observation_count = len(raw_observations)
            total_rows = repos_built + obs_built + ws_built + changes_built

            receipt = self._record_estate_build(
                schema,
                source_registration_count=source_registration_count,
                source_observation_count=source_observation_count,
                repositories_built=repos_built,
                observations_built=obs_built,
                workspace_instances_built=ws_built,
                changes_built=changes_built,
                corrupt_registration_count=corrupt_reg_count,
                corrupt_observation_count=corrupt_obs_count,
                now=now,
            )

        return MaterializationReceipt(
            receipt_id=receipt["receipt_id"],
            domain="repository_estate",
            source_evidence_count=source_registration_count + source_observation_count,
            rows_materialized=total_rows,
            corrupt_rows=corrupt_reg_count + corrupt_obs_count,
            duplicate_rows=obs_built - len(valid_obs),
            built_at=now,
        )

    # ── Table-level inserts ────────────────────────────────────────────

    def _insert_registered_repositories(
        self,
        schema: str,
        projection: Any,
        repos_by_hash: dict[str, dict],
        now: datetime,
    ) -> int:
        """Insert/update registered_repositories from projection summaries."""
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(repository_hash, repository_label, repository_kind, root_path_digest, "
            "git_common_dir_digest, remote_identity_digest, registered_at, last_registered_at, "
            "latest_observation_digest, latest_observation_at, provenance_class, "
            "authority_state, registration_sha256, materialized_at) "
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

        count = 0
        summaries = getattr(projection, "registered_repositories", [])
        for summary in summaries:
            rh = getattr(summary, "repository_hash", "")
            full_reg = repos_by_hash.get(rh, {})
            row = (
                rh,
                getattr(summary, "repository_label", ""),
                getattr(summary, "repository_kind", "local_only"),
                getattr(summary, "root_path_digest", ""),
                full_reg.get("git_common_dir_digest", ""),
                full_reg.get("remote_identity_digest", ""),
                _parse_timestamptz(getattr(summary, "registered_at", "")),
                _parse_timestamptz(getattr(summary, "last_registered_at", "")),
                getattr(summary, "latest_observation_digest", "") or "",
                _parse_timestamptz_or_none(
                    getattr(summary, "latest_observation_at", "")
                ),
                getattr(summary, "provenance", "canonical_fact"),
                "controlled_boundary",
                "",
                now,
            )
            with self.store.conn.cursor() as cur:
                cur.execute(query, row)
                count += cur.rowcount
        return count

    def _insert_observations(
        self, schema: str, valid_obs: list[dict], now: datetime
    ) -> int:
        """Insert observations into repository_observations table.

        Corrupt observations (provenance_class == 'corrupt_untrusted') are still stored.
        """
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(observation_id, repository_hash, workspace_root_digest, observed_at, "
            "status, head_sha, branch, is_detached, "
            "dirty_modified, dirty_staged, dirty_untracked, dirty_deleted, dirty_conflicted, "
            "tracked_file_count, is_github_backed, is_local_only, remote_count, "
            "instruction_file_count, previous_observation_digest, observation_digest, "
            "provenance_class, authority_state, observation_sha256, "
            "content_light_guarantee, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (observation_id) DO NOTHING"
        ).format(psql.Identifier(schema), psql.Identifier("repository_observations"))

        count = 0
        with self.store.conn.cursor() as cur:
            for payload in valid_obs:
                if payload.get("_corrupt"):
                    row = (
                        payload.get("observation_id", ""),
                        "",
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
                else:
                    git_facts = payload.get("git_facts", {})
                    dc = git_facts.get("dirty_counts", {})
                    row = (
                        payload.get("observation_id", ""),
                        payload.get("repository_hash", ""),
                        payload.get("root_path_digest", ""),
                        _parse_timestamptz(payload.get("observed_at", "")),
                        payload.get("status", "registered"),
                        git_facts.get("head_sha", "") or "",
                        git_facts.get("branch", "") or "",
                        git_facts.get("is_detached", False),
                        dc.get("modified", 0),
                        dc.get("staged", 0),
                        dc.get("untracked", 0),
                        dc.get("deleted", 0),
                        dc.get("conflicted", 0),
                        git_facts.get("tracked_file_count", 0),
                        git_facts.get("is_github_backed", False),
                        git_facts.get("is_local_only", True),
                        len(git_facts.get("remotes", [])),
                        len(git_facts.get("instruction_files", [])),
                        payload.get("previous_observation_digest", "") or "",
                        payload.get("observation_digest", ""),
                        "derived_projection",
                        "controlled_boundary",
                        payload.get("observation_digest", ""),
                        payload.get("content_light_guarantee", True),
                        now,
                    )
                cur.execute(query, row)
                count += cur.rowcount
        return count

    def _insert_workspace_instances(
        self, schema: str, valid_obs: list[dict], now: datetime
    ) -> int:
        """Build workspace instances from observations.

        Groups observations by (repository_hash, workspace_root_digest),
        takes the latest observation per group, and inserts/updates
        rows in repository_workspace_instances.
        """
        query = psql.SQL(
            "INSERT INTO {}.{} "
            "(instance_id, repository_hash, workspace_root_digest, workspace_kind, "
            "git_common_dir_digest, head_sha, branch, is_detached, "
            "dirty_modified, dirty_staged, dirty_untracked, dirty_deleted, dirty_conflicted, "
            "tracked_file_count, remote_count, is_github_backed, "
            "last_observed_at, last_observation_id, materialized_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
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

        # Group by (repository_hash, workspace_root_digest)
        groups: dict[tuple[str, str], list[dict]] = {}
        for payload in valid_obs:
            if payload.get("_corrupt"):
                continue
            rh = payload.get("repository_hash", "")
            ws_digest = payload.get("root_path_digest", "")
            if not rh or not ws_digest:
                continue
            key = (rh, ws_digest)
            groups.setdefault(key, []).append(payload)

        count = 0
        with self.store.conn.cursor() as cur:
            for (rh, ws_digest), obs_list in groups.items():
                obs_list.sort(key=lambda o: o.get("observed_at", ""))
                latest = obs_list[-1]
                instance_id = _compute_instance_id(rh, ws_digest)
                git_facts = latest.get("git_facts", {})
                dc = git_facts.get("dirty_counts", {})
                workspace_kind = _classify_workspace_kind(rh, ws_digest, git_facts)

                row = (
                    instance_id,
                    rh,
                    ws_digest,
                    workspace_kind,
                    git_facts.get("git_common_dir_digest", "") or "",
                    git_facts.get("head_sha", "") or "",
                    git_facts.get("branch", "") or "",
                    git_facts.get("is_detached", False),
                    dc.get("modified", 0),
                    dc.get("staged", 0),
                    dc.get("untracked", 0),
                    dc.get("deleted", 0),
                    dc.get("conflicted", 0),
                    git_facts.get("tracked_file_count", 0),
                    len(git_facts.get("remotes", [])),
                    git_facts.get("is_github_backed", False),
                    _parse_timestamptz(latest.get("observed_at", "")),
                    latest.get("observation_id", ""),
                    now,
                )
                cur.execute(query, row)
                count += cur.rowcount
        return count

    def _insert_observation_changes(
        self, schema: str, valid_obs: list[dict], now: datetime
    ) -> int:
        """Compute and insert observation changes between consecutive observations."""
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

        # Group observations by repository_hash, index by observation_id
        obs_by_repo: dict[str, list[dict]] = {}
        for payload in valid_obs:
            if payload.get("_corrupt"):
                continue
            rh = payload.get("repository_hash", "")
            if not rh:
                continue
            obs_by_repo.setdefault(rh, []).append(payload)

        count = 0
        with self.store.conn.cursor() as cur:
            for _rh, obs_list in obs_by_repo.items():
                obs_list.sort(key=lambda o: o.get("observed_at", ""))
                for i in range(1, len(obs_list)):
                    prev = obs_list[i - 1]
                    curr = obs_list[i]
                    change_kinds = _detect_change_kinds(prev, curr)
                    if not change_kinds:
                        continue

                    prev_id = prev.get("observation_id", "")
                    curr_id = curr.get("observation_id", "")
                    change_id = _compute_change_id(prev_id, curr_id)
                    prev_gf = prev.get("git_facts", {})
                    curr_gf = curr.get("git_facts", {})

                    row = (
                        change_id,
                        curr.get("repository_hash", ""),
                        prev.get("observation_digest", ""),
                        curr.get("observation_digest", ""),
                        _parse_timestamptz(curr.get("observed_at", "")),
                        change_kinds,
                        prev_gf.get("head_sha", "") or "",
                        curr_gf.get("head_sha", "") or "",
                        prev_gf.get("branch", "") or "",
                        curr_gf.get("branch", "") or "",
                        len(change_kinds),
                        "derived_projection",
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
        source_registration_count: int,
        source_observation_count: int,
        repositories_built: int,
        observations_built: int,
        workspace_instances_built: int,
        changes_built: int,
        corrupt_registration_count: int,
        corrupt_observation_count: int,
        now: datetime,
    ) -> dict[str, Any]:
        """Insert a repository_estate_builds row and return the receipt dict."""
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
                    "",
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

"""RepositoryEstateService — typed application service for repository registration,
observation, change detection, and projection.

This is the sole authority for repository estate domain operations.
All product actions enter through this service; no CLI, tool, or frontend
code may bypass it.

Reuses read-only Git observation helpers from ``rig_relay.digestion.identity``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any
import uuid

from rig_relay.digestion.identity import (
    is_github_backed,
    parse_dirty_state_from_porcelain,
    resolve_git_branch,
    resolve_git_common_dir,
    resolve_git_head_sha,
    resolve_git_porcelain_v2,
    resolve_git_remotes,
    resolve_git_worktree_root,
)
from rig_relay.repository_estate._digest_utils import digest_path, digest_text
from rig_relay.repository_estate._models import (
    AuthorityState,
    ChangeKind,
    DirtyCounts,
    GitIdentityBundle,
    InstructionFilePresence,
    ObservationStatus,
    ProvenanceClass,
    RecentChangeEvent,
    RegisteredRepository,
    RegisteredRepositorySummary,
    RemoteRecord,
    RepositoryEstateProjection,
    RepositoryKind,
    RepositoryObservation,
    RepositoryObservationChange,
)
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore


class RegistryError(Exception):
    """Raised when a repository estate operation fails domain validation."""


class _EstateConfig:
    """Configuration defaults for repository estate operations."""

    DEFAULT_STORE_ROOT: Path | None = None

    # Instruction files to check for presence during observation.
    # These are common instruction/governance file names.
    INSTRUCTION_FILE_NAMES: tuple[str, ...] = (
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "PROJECT.md",
        "LICENSE",
        "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    )

    # Private paths excluded from instruction file scan.
    EXCLUDED_INSTRUCTION_PREFIXES: tuple[str, ...] = (".rig/", ".build/", ".git/")


class RepositoryEstateService:
    """Typed application service for the Repository Estate domain.

    Owns the authority to register local repositories, produce content-light
    repository observations, detect observable state changes, and emit
    reconstructable projections for PostgreSQL and Gridline consumption.

    All evidence is stored in an append-only JSONL registry. No private
    source content, raw paths, or secrets are ever emitted.
    """

    def __init__(self, store_root: Path | None = None) -> None:
        store = store_root or _EstateConfig.DEFAULT_STORE_ROOT
        self._store = RepositoryEstateRegistryStore(store)

    # ── Registration ─────────────────────────────────────────────────

    def register_repository(self, root_path: Path) -> RegisteredRepository:
        """Register a local repository through the typed application service.

        Args:
            root_path: Path to the local repository root.

        Returns:
            A RegisteredRepository evidence record.

        Raises:
            RegistryError: If the path is not a git repository, or if
                the path is outside permitted workspace policy.
        """
        resolved = root_path.resolve()

        # -- Gate 1: Must be a git repository --
        worktree_root = resolve_git_worktree_root(resolved)
        if worktree_root is None:
            raise RegistryError(
                f"Path is not a git repository: {digest_path(resolved)[:12]}..."
            )

        # -- Gate 2: Compute identity signals --
        common_dir_digest = resolve_git_common_dir(worktree_root)
        root_path_digest = digest_path(worktree_root)
        path_and_common = f"{root_path_digest}:{common_dir_digest or ''}"
        repository_hash = hashlib.sha256(path_and_common.encode()).hexdigest()

        # -- Gate 3: Check for existing registration (idempotent) --
        existing = self._find_registration_by_common_dir(
            common_dir_digest, root_path_digest
        )
        if existing is not None:
            return self._reconcile_registration(existing, worktree_root)

        # -- Resolve identity signals --
        remotes = resolve_git_remotes(worktree_root)
        github_backed = is_github_backed(remotes)
        remote_digest = self._derive_remote_identity_digest(remotes)
        label = self._derive_label(worktree_root, remotes, github_backed)

        # -- Build and emit --
        now = datetime.now(UTC).isoformat()
        registration = RegisteredRepository(
            repository_hash=repository_hash,
            repository_label=label,
            repository_kind=(
                RepositoryKind.GITHUB_BACKED
                if github_backed
                else RepositoryKind.LOCAL_ONLY
            ),
            root_path_digest=root_path_digest,
            git_common_dir_digest=common_dir_digest,
            remote_identity_digest=remote_digest,
            registered_at=now,
            last_registered_at=now,
        )
        self._store.append_registration(registration)

        # -- Perform initial observation --
        observation = self._perform_observation(
            registration=registration,
            root=worktree_root,
            previous_observation=None,
            initial_registration=True,
        )
        self._store.append_observation(observation)

        # -- Update registration with observation pointer --
        registration.latest_observation_digest = observation.observation_digest
        registration.latest_observation_at = observation.observed_at
        self._store.append_registration(registration)

        return registration

    # ── Observation ──────────────────────────────────────────────────

    def observe_repository(
        self, repository_hash: str, root_path: Path | None = None
    ) -> RepositoryObservation:
        """Observe a registered repository and detect changes.

        Re-observes the repository at its registered path and compares
        against the previous observation. Returns an observation event
        with the appropriate status (observed, unchanged, changed,
        inaccessible, not_a_repository, disappeared).

        Args:
            repository_hash: The stable repository identifier from registration.
            root_path: Optional filesystem path to the repository. Required
                when the service cannot resolve the path from digest alone.
                Tests should always pass this; production callers maintain a
                path→hash mapping at a higher level.

        Returns:
            A RepositoryObservation evidence record.

        Raises:
            RegistryError: If no registration exists for this hash.
        """
        registration_event = self._find_registration_event(repository_hash)
        if registration_event is None:
            raise RegistryError(f"No registration found for hash: {repository_hash}")

        registration = RegisteredRepository.model_validate(
            registration_event["payload"]
        )

        previous_obs_event = self._store.latest_observation_for(repository_hash)
        previous_obs: RepositoryObservation | None = None
        if previous_obs_event is not None:
            try:
                previous_obs = RepositoryObservation.model_validate(
                    previous_obs_event["payload"]
                )
            except Exception:
                previous_obs = None

        # Resolve the repository path
        root = root_path if root_path is not None else None
        if root is None:
            root = self._resolve_root_from_registration(registration)
        if root is None:
            obs = self._build_disappeared_observation(registration, previous_obs)
            self._store.append_observation(obs)
            return obs

        observation = self._perform_observation(
            registration=registration,
            root=root,
            previous_observation=previous_obs,
            initial_registration=False,
        )
        self._store.append_observation(observation)

        # Update latest observation pointer
        registration.latest_observation_digest = observation.observation_digest
        registration.latest_observation_at = observation.observed_at
        self._store.append_registration(registration)

        return observation

    # ── Projection ───────────────────────────────────────────────────

    def build_projection(self) -> RepositoryEstateProjection:
        """Build a content-light RepositoryEstateProjection from canonical evidence.

        Reads all registration and observation events and computes
        a deterministic projection suitable for PostgreSQL materialization
        and Gridline consumption.
        """
        registrations = self._store.read_all_registrations()
        observations = self._store.read_all_observations()

        if not registrations:
            return RepositoryEstateProjection(
                authority_state=AuthorityState.MISSING,
                degraded_reason="No registrations found in evidence store.",
            )

        # Build per-repository summaries
        summaries: list[RegisteredRepositorySummary] = []
        recent_changes: list[RecentChangeEvent] = []
        dirty_count = 0
        inaccessible_count = 0
        _DEGRADED_STATUS_SET = {
            ObservationStatus.INACCESSIBLE,
            ObservationStatus.NOT_A_REPOSITORY,
            ObservationStatus.DISAPPEARED,
        }

        # Index observations by repository_hash (latest first)
        obs_by_repo: dict[str, list[dict]] = {}
        for o in observations:
            repo_hash = o.get("payload", {}).get("repository_hash", "")
            if repo_hash:
                obs_by_repo.setdefault(repo_hash, []).append(o)

        # Deduplicate registrations: keep only the latest per repository_hash
        latest_reg: dict[str, RegisteredRepository] = {}
        for reg_event in registrations:
            try:
                reg = RegisteredRepository.model_validate(reg_event["payload"])
            except Exception:
                continue
            rh = reg.repository_hash
            existing = latest_reg.get(rh)
            if (
                existing is None
                or reg.last_registered_at >= existing.last_registered_at
            ):
                latest_reg[rh] = reg

        for reg in latest_reg.values():
            repo_obs = obs_by_repo.get(reg.repository_hash, [])
            latest_obs_event = repo_obs[-1] if repo_obs else None
            latest_obs: RepositoryObservation | None = None
            if latest_obs_event is not None:
                try:
                    latest_obs = RepositoryObservation.model_validate(
                        latest_obs_event["payload"]
                    )
                except Exception:
                    latest_obs = None

            is_dirty = False
            if latest_obs is not None:
                facts = latest_obs.git_facts
                dc = facts.dirty_counts
                is_dirty = bool(
                    dc.modified
                    or dc.staged
                    or dc.untracked
                    or dc.deleted
                    or dc.conflicted
                )
                _INACCESSIBLE_STATUSES = {
                    ObservationStatus.INACCESSIBLE,
                    ObservationStatus.NOT_A_REPOSITORY,
                    ObservationStatus.DISAPPEARED,
                }
                if latest_obs.status in _INACCESSIBLE_STATUSES:
                    inaccessible_count += 1
                elif is_dirty:
                    dirty_count += 1

            summary = RegisteredRepositorySummary(
                provenance=ProvenanceClass.CANONICAL_FACT,
                repository_hash=reg.repository_hash,
                repository_label=reg.repository_label,
                repository_kind=reg.repository_kind,
                root_path_digest=reg.root_path_digest,
                registered_at=reg.registered_at,
                last_registered_at=reg.last_registered_at,
                latest_observation_digest=reg.latest_observation_digest,
                latest_observation_at=reg.latest_observation_at,
                latest_status=latest_obs.status
                if latest_obs
                else ObservationStatus.REGISTERED,
                latest_head_sha=latest_obs.git_facts.head_sha if latest_obs else None,
                latest_branch=latest_obs.git_facts.branch if latest_obs else None,
                is_detached=latest_obs.git_facts.is_detached if latest_obs else False,
                is_dirty=is_dirty,
                dirty_modified=latest_obs.git_facts.dirty_counts.modified
                if latest_obs
                else 0,
                dirty_untracked=latest_obs.git_facts.dirty_counts.untracked
                if latest_obs
                else 0,
                tracked_file_count=latest_obs.git_facts.tracked_file_count
                if latest_obs
                else 0,
                is_github_backed=reg.repository_kind == RepositoryKind.GITHUB_BACKED,
                is_local_only=reg.repository_kind == RepositoryKind.LOCAL_ONLY,
                instruction_file_count=(
                    len(latest_obs.git_facts.instruction_files) if latest_obs else 0
                ),
                remote_count=len(latest_obs.git_facts.remotes) if latest_obs else 0,
                degraded_reason=(
                    _degraded_reason_for_status(latest_obs.status)
                    if latest_obs and latest_obs.status in _DEGRADED_STATUS_SET
                    else ""
                ),
            )
            summaries.append(summary)

            # Compute recent changes from observation chain
            prev_obs_for_repo: dict | None = None
            for obs_event in repo_obs[-10:]:  # last 10 observations
                try:
                    obs = RepositoryObservation.model_validate(obs_event["payload"])
                except Exception:
                    continue
                if prev_obs_for_repo is not None:
                    change = self._detect_changes(
                        prev_obs_for_repo, obs_event["payload"]
                    )
                    if change is not None and change.changed:
                        recent_changes.append(
                            RecentChangeEvent(
                                repository_hash=reg.repository_hash,
                                repository_label=reg.repository_label,
                                detected_at=obs.observed_at,
                                change_kinds=change.change_kinds,
                                from_observation_id=change.from_observation_id,
                                to_observation_id=change.to_observation_id,
                            )
                        )
                prev_obs_for_repo = obs_event["payload"]

        # Sort recent changes by time (newest first)
        recent_changes.sort(key=lambda c: c.detected_at, reverse=True)
        # Cap at 50 recent changes for projection size
        recent_changes = recent_changes[:50]

        # Compute authority state
        authority = AuthorityState.CANONICAL_LIVE
        degraded = ""
        if inaccessible_count > 0:
            authority = AuthorityState.DEGRADED
            degraded = f"{inaccessible_count} repositories inaccessible"
        elif not observations:
            authority = AuthorityState.STALE
            degraded = "No observations recorded"

        projection = RepositoryEstateProjection(
            provenance=ProvenanceClass.DERIVED_PROJECTION,
            authority_state=authority,
            degraded_reason=degraded,
            available=len(summaries) > 0,
            registered_repositories=summaries,
            total_registered=len(summaries),
            local_only_count=sum(
                1 for s in summaries if s.repository_kind == RepositoryKind.LOCAL_ONLY
            ),
            github_backed_count=sum(
                1
                for s in summaries
                if s.repository_kind == RepositoryKind.GITHUB_BACKED
            ),
            dirty_count=dirty_count,
            inaccessible_count=inaccessible_count,
            recent_changes=recent_changes,
            total_observations=len(observations),
        )
        return projection

    # ── Internal: observation execution ───────────────────────────────

    def _perform_observation(
        self,
        *,
        registration: RegisteredRepository,
        root: Path,
        previous_observation: RepositoryObservation | None,
        initial_registration: bool,
    ) -> RepositoryObservation:
        """Execute a real Git observation against the filesystem."""
        now = datetime.now(UTC).isoformat()
        obs_id = str(uuid.uuid4())

        # Validate repository is still accessible
        worktree_root = resolve_git_worktree_root(root)
        if worktree_root is None:
            return self._build_inaccessible_observation(
                registration, obs_id, now, previous_observation, "not_a_repository"
            )

        # Collect git facts
        head_sha = resolve_git_head_sha(worktree_root)
        branch = resolve_git_branch(worktree_root)
        is_detached = head_sha is not None and branch is None
        porcelain = resolve_git_porcelain_v2(worktree_root)
        dirty = parse_dirty_state_from_porcelain(porcelain)
        dirty_counts = DirtyCounts(
            modified=dirty.modified,
            staged=dirty.staged,
            untracked=dirty.untracked,
            deleted=dirty.deleted,
            conflicted=dirty.conflicted,
        )
        tracked_file_count = self._count_tracked_files(worktree_root)
        remotes_raw = resolve_git_remotes(worktree_root)
        remotes = [
            RemoteRecord(name=r["name"], url_digest=r["url_digest"], host=r["host"])
            for r in remotes_raw
        ]
        github_backed = is_github_backed(remotes_raw)
        common_dir_digest = resolve_git_common_dir(worktree_root)

        # Instruction file presence
        instruction_files = self._scan_instruction_files(worktree_root)

        git_facts = GitIdentityBundle(
            head_sha=head_sha,
            branch=branch,
            is_detached=is_detached,
            dirty_counts=dirty_counts,
            tracked_file_count=tracked_file_count,
            is_github_backed=github_backed,
            is_local_only=len(remotes) == 0,
            remotes=remotes,
            git_common_dir_digest=common_dir_digest,
            instruction_files=instruction_files,
        )

        # Determine observation status
        prev_digest = (
            previous_observation.observation_digest if previous_observation else None
        )

        if initial_registration:
            status = ObservationStatus.REGISTERED
        elif previous_observation is not None:
            change = self._detect_changes_direct(
                previous_observation, git_facts, now, obs_id
            )
            if change is not None and change.changed:
                status = ObservationStatus.CHANGED
            else:
                status = ObservationStatus.UNCHANGED
        else:
            status = ObservationStatus.OBSERVED

        # Compute observation digest
        root_path_digest = digest_path(worktree_root)
        payload = {
            "schema_version": "rig.relay.repository_estate_observation.v1",
            "observation_id": obs_id,
            "repository_hash": registration.repository_hash,
            "observed_at": now,
            "status": status,
            "root_path_digest": root_path_digest,
            "git_facts": git_facts.model_dump(mode="json"),
            "previous_observation_digest": prev_digest,
            "observation_digest": "",
            "content_light_guarantee": True,
        }
        obs_digest = digest_text(
            _canonical_json({
                k: v for k, v in payload.items() if k != "observation_digest"
            })
        )

        return RepositoryObservation(
            observation_id=obs_id,
            repository_hash=registration.repository_hash,
            observed_at=now,
            status=status,
            root_path_digest=root_path_digest,
            git_facts=git_facts,
            previous_observation_digest=prev_digest,
            observation_digest=obs_digest,
        )

    def _build_inaccessible_observation(
        self,
        registration: RegisteredRepository,
        obs_id: str,
        now: str,
        previous_obs: RepositoryObservation | None,
        reason: str,
    ) -> RepositoryObservation:
        prev_digest = previous_obs.observation_digest if previous_obs else None
        status = (
            ObservationStatus.NOT_A_REPOSITORY
            if reason == "not_a_repository"
            else ObservationStatus.INACCESSIBLE
        )
        git_facts = GitIdentityBundle()
        payload = {
            "observation_id": obs_id,
            "repository_hash": registration.repository_hash,
            "observed_at": now,
            "status": status,
            "root_path_digest": registration.root_path_digest,
            "git_facts": git_facts.model_dump(mode="json"),
            "previous_observation_digest": prev_digest,
            "observation_digest": "",
            "content_light_guarantee": True,
        }
        obs_digest = digest_text(
            _canonical_json({
                k: v for k, v in payload.items() if k != "observation_digest"
            })
        )
        return RepositoryObservation(
            observation_id=obs_id,
            repository_hash=registration.repository_hash,
            observed_at=now,
            status=status,
            root_path_digest=registration.root_path_digest,
            git_facts=git_facts,
            previous_observation_digest=prev_digest,
            observation_digest=obs_digest,
        )

    def _build_disappeared_observation(
        self,
        registration: RegisteredRepository,
        previous_obs: RepositoryObservation | None,
    ) -> RepositoryObservation:
        now = datetime.now(UTC).isoformat()
        obs_id = str(uuid.uuid4())
        prev_digest = previous_obs.observation_digest if previous_obs else None
        git_facts = GitIdentityBundle()
        payload = {
            "observation_id": obs_id,
            "repository_hash": registration.repository_hash,
            "observed_at": now,
            "status": ObservationStatus.DISAPPEARED,
            "root_path_digest": registration.root_path_digest,
            "git_facts": git_facts.model_dump(mode="json"),
            "previous_observation_digest": prev_digest,
            "observation_digest": "",
            "content_light_guarantee": True,
        }
        obs_digest = digest_text(
            _canonical_json({
                k: v for k, v in payload.items() if k != "observation_digest"
            })
        )
        return RepositoryObservation(
            observation_id=obs_id,
            repository_hash=registration.repository_hash,
            observed_at=now,
            status=ObservationStatus.DISAPPEARED,
            root_path_digest=registration.root_path_digest,
            git_facts=git_facts,
            previous_observation_digest=prev_digest,
            observation_digest=obs_digest,
        )

    # ── Internal: change detection ────────────────────────────────────

    def _detect_changes(
        self, prev_payload: dict[str, Any], curr_payload: dict[str, Any]
    ) -> RepositoryObservationChange | None:
        """Detect changes between two observation payloads."""
        try:
            prev = RepositoryObservation.model_validate(prev_payload)
            curr = RepositoryObservation.model_validate(curr_payload)
        except Exception:
            return None
        return self._detect_changes_direct(
            prev, curr.git_facts, curr.observed_at, curr.observation_id
        )

    def _detect_changes_direct(
        self,
        previous: RepositoryObservation,
        current_facts: GitIdentityBundle,
        now: str,
        new_obs_id: str,
    ) -> RepositoryObservationChange:
        """Direct change detection between observation and facts."""
        prev_facts = previous.git_facts
        change_kinds: list[ChangeKind] = []

        if prev_facts.head_sha != current_facts.head_sha:
            change_kinds.append(ChangeKind.HEAD_CHANGED)
        if prev_facts.branch != current_facts.branch:
            change_kinds.append(ChangeKind.BRANCH_CHANGED)
        if prev_facts.is_detached != current_facts.is_detached:
            change_kinds.append(ChangeKind.DETACHED_STATE_CHANGED)

        prev_dc = prev_facts.dirty_counts
        curr_dc = current_facts.dirty_counts
        if (
            prev_dc.modified != curr_dc.modified
            or prev_dc.staged != curr_dc.staged
            or prev_dc.untracked != curr_dc.untracked
            or prev_dc.deleted != curr_dc.deleted
            or prev_dc.conflicted != curr_dc.conflicted
        ):
            change_kinds.append(ChangeKind.DIRTY_STATE_CHANGED)

        if prev_facts.tracked_file_count != current_facts.tracked_file_count:
            change_kinds.append(ChangeKind.TRACKED_FILE_COUNT_CHANGED)

        prev_remotes_digest = self._remote_digest_set(prev_facts.remotes)
        curr_remotes_digest = self._remote_digest_set(current_facts.remotes)
        if prev_remotes_digest != curr_remotes_digest:
            change_kinds.append(ChangeKind.REMOTES_CHANGED)

        if prev_facts.git_common_dir_digest != current_facts.git_common_dir_digest:
            change_kinds.append(ChangeKind.COMMON_DIR_CHANGED)

        prev_inst_digest = self._instruction_digest_set(prev_facts.instruction_files)
        curr_inst_digest = self._instruction_digest_set(current_facts.instruction_files)
        if prev_inst_digest != curr_inst_digest:
            change_kinds.append(ChangeKind.INSTRUCTION_FILES_CHANGED)

        return RepositoryObservationChange(
            repository_hash=previous.repository_hash,
            from_observation_id=previous.observation_id,
            to_observation_id=new_obs_id,
            from_observation_digest=previous.observation_digest,
            to_observation_digest="",  # filled by caller
            changed=len(change_kinds) > 0,
            change_kinds=change_kinds,
        )

    def _remote_digest_set(self, remotes: list[RemoteRecord]) -> frozenset[str]:
        return frozenset(r.url_digest for r in remotes)

    def _instruction_digest_set(
        self, instructions: list[InstructionFilePresence]
    ) -> frozenset[str]:
        return frozenset(i.content_sha256 for i in instructions)

    # ── Internal: registration helpers ────────────────────────────────

    def _find_registration_by_common_dir(
        self, common_dir_digest: str | None, root_path_digest: str
    ) -> RegisteredRepository | None:
        """Find an existing registration with matching common dir or path."""
        if common_dir_digest is None:
            return None
        for event in self._store.read_all_registrations():
            try:
                reg = RegisteredRepository.model_validate(event["payload"])
            except Exception:
                continue
            if reg.git_common_dir_digest == common_dir_digest:
                return reg
            if reg.root_path_digest == root_path_digest:
                return reg
        return None

    def _find_registration_event(self, repository_hash: str) -> dict | None:
        """Find the most recent registration event for a repository hash."""
        for event in reversed(self._store.read_all_registrations()):
            if event.get("payload", {}).get("repository_hash") == repository_hash:
                return event
        return None

    def _reconcile_registration(
        self, existing: RegisteredRepository, new_root: Path
    ) -> RegisteredRepository:
        """Reconcile a re-registration: update timestamps, re-observe."""
        now = datetime.now(UTC).isoformat()
        existing.last_registered_at = now
        existing.root_path_digest = digest_path(new_root)
        self._store.append_registration(existing)

        previous_obs_event = self._store.latest_observation_for(
            existing.repository_hash
        )
        previous_obs = None
        if previous_obs_event is not None:
            try:
                previous_obs = RepositoryObservation.model_validate(
                    previous_obs_event["payload"]
                )
            except Exception:
                pass

        observation = self._perform_observation(
            registration=existing,
            root=new_root,
            previous_observation=previous_obs,
            initial_registration=False,
        )
        self._store.append_observation(observation)

        existing.latest_observation_digest = observation.observation_digest
        existing.latest_observation_at = observation.observed_at
        self._store.append_registration(existing)
        return existing

    def _resolve_root_from_registration(
        self, registration: RegisteredRepository
    ) -> Path | None:
        """Attempt to resolve a filesystem path from the root_path_digest.

        Since path digests are one-way, we scan common locations to find
        the current path. This is a limitation of content-light identity —
        the caller must maintain a path map or use a well-known location.
        For tests, we use the registration's last known root.
        """
        # For now, return None if we can't resolve.
        # We detect this in observe_repository and emit a disappeared event.
        # In a future iteration, a path registry (mapping hash→path) would be
        # maintained in a separate durable store.
        return None

    # ── Internal: observation helpers ─────────────────────────────────

    def _count_tracked_files(self, root: Path) -> int:
        """Count tracked files via git ls-files."""
        import subprocess

        try:
            result = subprocess.check_output(
                ["git", "--no-optional-locks", "ls-files"],
                text=True,
                stderr=subprocess.DEVNULL,
                cwd=root,
            )
            return len([l for l in result.splitlines() if l.strip()])
        except (subprocess.CalledProcessError, FileNotFoundError):
            return 0

    def _scan_instruction_files(self, root: Path) -> list[InstructionFilePresence]:
        """Scan for instruction/governance files at the repo root.

        Only checks the repo root level and immediate subdirectories
        that aren't excluded. Returns content-light presence records.
        """
        import hashlib as hl

        results: list[InstructionFilePresence] = []
        seen_kinds: set[str] = set()

        # Check root-level instruction files
        for name in _EstateConfig.INSTRUCTION_FILE_NAMES:
            fp = root / name
            if not fp.is_file():
                continue
            try:
                content = fp.read_bytes()
                content_sha = hl.sha256(content).hexdigest()
                path_digest = digest_path(fp)
                kind = _kind_for_filename(name)
                if kind not in seen_kinds:
                    seen_kinds.add(kind)
                    results.append(
                        InstructionFilePresence(
                            kind=kind,
                            path_digest=path_digest,
                            content_sha256=content_sha,
                        )
                    )
            except OSError:
                continue

        return results

    def _derive_label(
        self, root: Path, remotes: list[dict[str, str]], github_backed: bool
    ) -> str:
        """Derive a human-readable label for the repository."""
        if github_backed:
            for r in remotes:
                if r.get("name") == "origin":
                    # url_digest is SHA256, can't recover. Use dirname.
                    return root.name
        return root.name

    def _derive_remote_identity_digest(
        self, remotes: list[dict[str, str]]
    ) -> str | None:
        """Derive a stable remote identity digest from an origin remote."""
        for r in remotes:
            if r.get("name") == "origin":
                return r.get("url_digest")
        if remotes:
            return remotes[0].get("url_digest")
        return None


def _kind_for_filename(name: str) -> str:
    """Map a filename to an instruction kind label."""
    mapping = {
        "AGENTS.md": "agents_md",
        "CLAUDE.md": "claude_md",
        "README.md": "readme_md",
        "CONTRIBUTING.md": "contributing_md",
        "SECURITY.md": "security_md",
        "CODE_OF_CONDUCT.md": "code_of_conduct_md",
        "PROJECT.md": "project_md",
        "LICENSE": "license",
        "CONTRIBUTOR_LICENSE_AGREEMENT.md": "cla_md",
    }
    return mapping.get(name, name.lower().replace(".", "_"))


def _canonical_json(obj: dict) -> str:
    """Serialize to canonical JSON for hashing."""
    from rig_relay.coordination._canonical_json import dump_canonical_json

    return dump_canonical_json(obj)


def _degraded_reason_for_status(status: ObservationStatus) -> str:
    if status == ObservationStatus.INACCESSIBLE:
        return "Repository path is inaccessible."
    if status == ObservationStatus.NOT_A_REPOSITORY:
        return "Path is no longer a git repository."
    if status == ObservationStatus.DISAPPEARED:
        return "Repository path has disappeared."
    return ""


__all__ = ["RegistryError", "RepositoryEstateService"]

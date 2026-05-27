"""Observation engine — typed collaborator for repository observation.

Executes real Git observations against the filesystem, collects content-light
operational facts, and enforces identity-match gating before appending any
observation evidence. Never carries raw file contents, raw paths, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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
    DirtyCounts,
    GitIdentityBundle,
    InstructionFilePresence,
    ObservationStatus,
    RegisteredRepository,
    RemoteRecord,
    RepositoryKind,
    RepositoryObservation,
)
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore


class _EstateConfig:
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


class ObservationEngine:
    """Typed authority for repository observation with identity-match enforcement.

    Owns the logic for executing Git observations, collecting operational facts,
    and enforcing the rule that a supplied repository path must correspond to
    the registered repository identity before any observation event is appended.
    """

    def __init__(self, store: RepositoryEstateRegistryStore) -> None:
        self._store = store

    # ── Public: observe with identity-match gate ─────────────────────

    def observe(
        self,
        *,
        registration: RegisteredRepository,
        root_path: Path,
        previous_obs: RepositoryObservation | None,
        initial_registration: bool,
    ) -> RepositoryObservation:
        """Observe a repository and produce an observation event.

        Gate 1: Verify the observed path resolves to a git worktree.
        Gate 2: Verify the resolved identity matches the registered identity.
        Gate 3: Collect content-light git facts.
        Gate 4: Emit observation with appropriate status.
        """
        resolved = root_path.resolve()
        worktree_root = resolve_git_worktree_root(resolved)
        if worktree_root is None:
            return self._build_status_observation(
                registration=registration,
                status=ObservationStatus.NOT_A_REPOSITORY,
                root_path_digest=registration.root_path_digest,
                previous_obs=previous_obs,
                empty_facts=True,
            )

        # ── Identity-match gate ──
        match = self._verify_identity_match(
            registration=registration, worktree_root=worktree_root
        )
        if not match.matched:
            return self._build_status_observation(
                registration=registration,
                status=ObservationStatus.IDENTITY_MISMATCH,
                root_path_digest=digest_path(worktree_root),
                previous_obs=previous_obs,
                empty_facts=True,
            )

        # ── Collect git facts ──
        git_facts = self._collect_git_facts(worktree_root)

        # ── Determine observation status ──
        if initial_registration:
            status = ObservationStatus.REGISTERED
        elif previous_obs is not None:
            if self._has_changed(previous_obs.git_facts, git_facts):
                status = ObservationStatus.CHANGED
            else:
                status = ObservationStatus.UNCHANGED
        else:
            status = ObservationStatus.OBSERVED

        return self._build_full_observation(
            registration=registration,
            status=status,
            root_path_digest=digest_path(worktree_root),
            git_facts=git_facts,
            previous_obs=previous_obs,
        )

    def observe_or_disappeared(
        self,
        *,
        registration: RegisteredRepository,
        root_path: Path | None,
        previous_obs: RepositoryObservation | None,
        initial_registration: bool,
    ) -> RepositoryObservation:
        """Observe with root_path or emit DISAPPEARED if path cannot be resolved."""
        if root_path is None:
            return self._build_status_observation(
                registration=registration,
                status=ObservationStatus.DISAPPEARED,
                root_path_digest=registration.root_path_digest,
                previous_obs=previous_obs,
                empty_facts=True,
            )
        return self.observe(
            registration=registration,
            root_path=root_path,
            previous_obs=previous_obs,
            initial_registration=initial_registration,
        )

    # ── Identity-match logic ─────────────────────────────────────────

    def _verify_identity_match(
        self, registration: RegisteredRepository, worktree_root: Path
    ) -> _IdentityMatchResult:
        """Verify the observed path's identity corresponds to the registered repo.

        Local-only repos: match on root_path_digest AND git_common_dir_digest.
        GitHub-backed repos: match on root_path_digest OR git_common_dir_digest
        OR remote_identity_digest.
        """
        observed_path_digest = digest_path(worktree_root)
        observed_common_dir = resolve_git_common_dir(worktree_root)

        if registration.repository_kind == RepositoryKind.LOCAL_ONLY:
            # Local-only: match on root_path_digest alone.
            # git_common_dir_digest may change across normal Git operations
            # (branch switches, commits) while the repo remains the same entity.
            path_ok = observed_path_digest == registration.root_path_digest
            common_ok = True  # advisory, not blocking
            matched = path_ok
        else:
            path_ok = observed_path_digest == registration.root_path_digest
            common_ok = observed_common_dir == registration.git_common_dir_digest
            remote_ok = (
                registration.remote_identity_digest is not None
                and self._remote_matches(
                    worktree_root, registration.remote_identity_digest
                )
            )
            matched = path_ok or common_ok or remote_ok

        return _IdentityMatchResult(
            matched=matched, path_ok=path_ok, common_ok=common_ok
        )

    def _remote_matches(self, worktree_root: Path, expected_remote_digest: str) -> bool:
        remotes = resolve_git_remotes(worktree_root)
        for r in remotes:
            if r.get("url_digest") == expected_remote_digest:
                return True
        return False

    # ── Git fact collection ───────────────────────────────────────────

    def _collect_git_facts(self, worktree_root: Path) -> GitIdentityBundle:
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
        instruction_files = self._scan_instruction_files(worktree_root)

        return GitIdentityBundle(
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

    # ── Observation builders ──────────────────────────────────────────

    def _build_full_observation(
        self,
        *,
        registration: RegisteredRepository,
        status: ObservationStatus,
        root_path_digest: str,
        git_facts: GitIdentityBundle,
        previous_obs: RepositoryObservation | None,
    ) -> RepositoryObservation:
        now = datetime.now(UTC).isoformat()
        obs_id = str(uuid.uuid4())
        prev_digest = previous_obs.observation_digest if previous_obs else None
        payload = {
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

    def _build_status_observation(
        self,
        *,
        registration: RegisteredRepository,
        status: ObservationStatus,
        root_path_digest: str,
        previous_obs: RepositoryObservation | None,
        empty_facts: bool,
    ) -> RepositoryObservation:
        now = datetime.now(UTC).isoformat()
        obs_id = str(uuid.uuid4())
        prev_digest = previous_obs.observation_digest if previous_obs else None
        git_facts = (
            GitIdentityBundle()
            if empty_facts
            else self._collect_git_facts(
                Path(".")  # unreachable when root_path_digest is from registration
            )
        )
        payload = {
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

    # ── Helpers ───────────────────────────────────────────────────────

    def _count_tracked_files(self, root: Path) -> int:
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
        import hashlib as hl

        results: list[InstructionFilePresence] = []
        seen_kinds: set[str] = set()
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

    def _has_changed(self, prev: GitIdentityBundle, curr: GitIdentityBundle) -> bool:
        """Quick boolean check for any change between two fact bundles."""
        if prev.head_sha != curr.head_sha:
            return True
        if prev.branch != curr.branch:
            return True
        if prev.is_detached != curr.is_detached:
            return True
        pdc, cdc = prev.dirty_counts, curr.dirty_counts
        if (
            pdc.modified != cdc.modified
            or pdc.staged != cdc.staged
            or pdc.untracked != cdc.untracked
            or pdc.deleted != cdc.deleted
            or pdc.conflicted != cdc.conflicted
        ):
            return True
        if prev.tracked_file_count != curr.tracked_file_count:
            return True
        if {r.url_digest for r in prev.remotes} != {r.url_digest for r in curr.remotes}:
            return True
        if prev.git_common_dir_digest != curr.git_common_dir_digest:
            return True
        if {i.content_sha256 for i in prev.instruction_files} != {
            i.content_sha256 for i in curr.instruction_files
        }:
            return True
        return False


class _IdentityMatchResult:
    def __init__(self, *, matched: bool, path_ok: bool, common_ok: bool) -> None:
        self.matched = matched
        self.path_ok = path_ok
        self.common_ok = common_ok


def _kind_for_filename(name: str) -> str:
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
    from rig_relay.coordination._canonical_json import dump_canonical_json

    return dump_canonical_json(obj)


__all__ = ["ObservationEngine"]

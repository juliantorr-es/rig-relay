"""Registration authority — typed collaborator for repository registration.

Handles identity computation, idempotent re-registration, and registration lookups.
All evidence is written through the supplied store.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path

from rig_relay.digestion.identity import (
    is_github_backed,
    resolve_git_common_dir,
    resolve_git_remotes,
    resolve_git_worktree_root,
)
from rig_relay.repository_estate._digest_utils import digest_path
from rig_relay.repository_estate._models import RegisteredRepository, RepositoryKind
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore


class RegistrationError(Exception):
    """Raised when a repository estate registration fails domain validation.

    This is the canonical repository-estate domain error. The service-layer
    ``RegistryError`` re-exports it for continuity with the public API.
    """


class RegistrationAuthority:
    """Typed authority for repository registration and identity management.

    Owns the logic for computing stable repository identity, checking for
    existing registrations (idempotent), reconciling re-registrations, and
    finding registration events by hash or correlation signal.
    """

    def __init__(self, store: RepositoryEstateRegistryStore) -> None:
        self._store = store

    def register(self, root_path: Path) -> tuple[RegisteredRepository, Path]:
        """Register a local repository or reconcile an existing registration.

        Args:
            root_path: Path to the local repository root.

        Returns:
            Tuple of (RegisteredRepository, resolved_worktree_root).

        Raises:
            RegistrationError: If the path is not a git repository.
        """
        resolved = root_path.resolve()
        worktree_root = resolve_git_worktree_root(resolved)
        if worktree_root is None:
            raise RegistrationError(
                f"Path is not a git repository: {digest_path(resolved)[:12]}..."
            )

        common_dir_digest = resolve_git_common_dir(worktree_root)
        root_path_digest = digest_path(worktree_root)

        existing = self._find_by_correlation(common_dir_digest, root_path_digest)
        if existing is not None:
            now = datetime.now(UTC).isoformat()
            existing.last_registered_at = now
            existing.root_path_digest = root_path_digest
            self._store.append_registration(existing)
            return existing, worktree_root

        remotes = resolve_git_remotes(worktree_root)
        github_backed = is_github_backed(remotes)
        remote_digest = self._derive_remote_identity_digest(remotes)
        label = self._derive_label(worktree_root, remotes, github_backed)
        path_and_common = f"{root_path_digest}:{common_dir_digest or ''}"
        repository_hash = hashlib.sha256(path_and_common.encode()).hexdigest()

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
        return registration, worktree_root

    def find_event(self, repository_hash: str) -> dict | None:
        """Find the most recent registration event for a repository hash."""
        for event in reversed(self._store.read_all_registrations()):
            if event.get("payload", {}).get("repository_hash") == repository_hash:
                return event
        return None

    def _find_by_correlation(
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

    def _derive_label(
        self, root: Path, remotes: list[dict[str, str]], github_backed: bool
    ) -> str:
        if github_backed:
            for r in remotes:
                if r.get("name") == "origin":
                    return root.name
        return root.name

    def _derive_remote_identity_digest(
        self, remotes: list[dict[str, str]]
    ) -> str | None:
        for r in remotes:
            if r.get("name") == "origin":
                return r.get("url_digest")
        if remotes:
            return remotes[0].get("url_digest")
        return None


__all__ = ["RegistrationAuthority", "RegistrationError"]

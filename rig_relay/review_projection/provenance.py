from __future__ import annotations

import hashlib
from pathlib import Path

from git import InvalidGitRepositoryError, Repo
from git.exc import GitCommandError


class DiffDelta:
    """A single changed-file record from git diff."""

    __slots__ = (
        "path",
        "change_type",
        "old_path",
        "old_blob_sha256",
        "new_blob_sha256",
    )

    def __init__(
        self,
        path: str,
        change_type: str,
        old_path: str | None = None,
        old_blob_sha256: str | None = None,
        new_blob_sha256: str | None = None,
    ) -> None:
        self.path = path
        self.change_type = change_type
        self.old_path = old_path
        self.old_blob_sha256 = old_blob_sha256
        self.new_blob_sha256 = new_blob_sha256


class ProjectionSnapshot:
    """Git provenance snapshot: HEAD commit, branch, dirty-state inventory.

    Captures four states: staged vs HEAD, unstaged vs index, untracked files,
    and renames/deletions. The primary review view is HEAD vs working tree.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = (repo_root or Path.cwd()).resolve()
        self._repo: Repo | None = None

        try:
            self._repo = Repo(self._repo_root, search_parent_directories=True)
        except InvalidGitRepositoryError as e:
            raise GitNotFoundError(
                f"No git repository found at {self._repo_root}"
            ) from e

        self.head_sha: str = self._repo.head.commit.hexsha
        self.branch: str | None = (
            None if self._repo.head.is_detached else self._repo.active_branch.name
        )
        self.is_detached: bool = self._repo.head.is_detached

        # Staged modifications relative to HEAD
        self._staged_deltas: list[DiffDelta] = []
        # Unstaged modifications relative to index
        self._unstaged_deltas: list[DiffDelta] = []
        # Renames detected in staged or unstaged
        self._renames: dict[str, str] = {}  # old_path -> new_path
        self._deletions: set[str] = set()

        self._collect_deltas()

        # Untracked files (not in git at all)
        self.untracked_files: list[str] = self._repo.untracked_files

        # The primary review surface: HEAD vs working tree
        self.changed_paths: list[DiffDelta] = self._build_changed_paths()

    def _collect_deltas(self) -> None:
        repo = self._repo
        if repo is None:
            return

        # Staged vs HEAD
        try:
            for diff in repo.index.diff(repo.head.commit):
                delta = self._diff_to_delta(diff)
                self._staged_deltas.append(delta)
                if diff.renamed_file:
                    old = diff.rename_from or ""
                    new = diff.b_path or ""
                    if old and new:
                        self._renames[old] = new
                if diff.change_type == "D":
                    path = diff.a_path or diff.b_path or ""
                    if path:
                        self._deletions.add(path)
        except GitCommandError:
            pass

        # Unstaged vs index
        try:
            for diff in repo.index.diff(None):
                delta = self._diff_to_delta(diff)
                self._unstaged_deltas.append(delta)
                if diff.renamed_file:
                    old = diff.rename_from or ""
                    new = diff.b_path or ""
                    if old and new:
                        self._renames[old] = new
        except GitCommandError:
            pass

    @staticmethod
    def _diff_to_delta(diff: object) -> DiffDelta:
        path = getattr(diff, "b_path", None) or getattr(diff, "a_path", "") or ""
        old_path: str | None = None
        if getattr(diff, "renamed_file", False):
            old_path = getattr(diff, "rename_from", None) or None
        return DiffDelta(
            path=path,
            change_type=getattr(diff, "change_type", "M") or "M",
            old_path=old_path,
        )

    def _build_changed_paths(self) -> list[DiffDelta]:
        seen: dict[str, DiffDelta] = {}

        repo = self._repo
        if repo is not None:
            try:
                output = repo.git.diff("HEAD", "--name-status")
                for line in output.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) < 2:
                        continue
                    status = parts[0]
                    path_str = parts[1]
                    if status.startswith("R"):
                        sub = path_str.split("\t", 1)
                        if len(sub) == 2:
                            old_path = sub[0]
                            new_path = sub[1]
                            self._renames[old_path] = new_path
                            seen[new_path] = DiffDelta(
                                path=new_path, change_type="R", old_path=old_path
                            )
                            continue
                    ct = status[0] if status else "M"
                    seen[path_str] = DiffDelta(path=path_str, change_type=ct)
            except GitCommandError:
                pass

        for untracked in self.untracked_files:
            if untracked.startswith(".build/"):
                continue
            if untracked not in seen:
                seen[untracked] = DiffDelta(path=untracked, change_type="A")

        return list(seen.values())

    @property
    def has_staged_only_changes(self) -> bool:
        return len(self._staged_deltas) > 0

    @property
    def has_unstaged_changes(self) -> bool:
        return len(self._unstaged_deltas) > 0

    @property
    def renames(self) -> dict[str, str]:
        return dict(self._renames)

    @property
    def deletions(self) -> frozenset[str]:
        return frozenset(self._deletions)

    def get_baseline_content(self, rel_path: str) -> bytes | None:
        """Read blob content from HEAD commit for a tracked path."""
        repo = self._repo
        if repo is None:
            return None
        try:
            blob = repo.head.commit.tree / rel_path
            return blob.data_stream.read()
        except (KeyError, ValueError, OSError):
            return None

    def get_dirty_content(self, rel_path: str) -> bytes | None:
        """Read file content from the working tree."""
        file_path = self._repo_root / rel_path
        try:
            return file_path.read_bytes()
        except OSError:
            return None

    def hash_baseline(self, rel_path: str) -> str | None:
        content = self.get_baseline_content(rel_path)
        if content is None:
            return None
        return hashlib.sha256(content).hexdigest()

    def hash_dirty(self, rel_path: str) -> str | None:
        content = self.get_dirty_content(rel_path)
        if content is None:
            return None
        return hashlib.sha256(content).hexdigest()

    @property
    def staged_paths(self) -> list[str]:
        return [d.path for d in self._staged_deltas if d.path]

    @property
    def unstaged_paths(self) -> list[str]:
        return [d.path for d in self._unstaged_deltas if d.path]

    @property
    def changed_path_names(self) -> list[str]:
        return [d.path for d in self.changed_paths if d.path]


class GitNotFoundError(Exception):
    """Raised when no git repository is found at the given root."""

from __future__ import annotations

from pathlib import Path
import subprocess


class WorktreeError(Exception):
    pass


class CompilerWorktree:
    def __init__(self, worktree_root: Path, repo_root: Path) -> None:
        self._worktree_root = worktree_root
        self._repo_root = repo_root
        self._worktree_dir: Path | None = None
        self._base_sha: str | None = None

    @property
    def worktree_dir(self) -> Path:
        if self._worktree_dir is None:
            raise RuntimeError("Worktree not created")
        return self._worktree_dir

    @property
    def base_sha(self) -> str:
        if self._base_sha is None:
            raise RuntimeError("Worktree not created")
        return self._base_sha

    def create(self, run_id: str, candidate_id: str) -> tuple[Path, str]:
        self._refuse_dangerous_paths()
        wt_dir = self._worktree_root / run_id / "scratch" / candidate_id
        wt_dir.parent.mkdir(parents=True, exist_ok=True)
        self._base_sha = self._git_head_sha()
        self._run_git(["worktree", "add", str(wt_dir), self._base_sha])
        self._worktree_dir = wt_dir
        return wt_dir, self._base_sha

    def reap(self) -> None:
        if self._worktree_dir is not None and self._worktree_dir.exists():
            self._run_git(["worktree", "remove", str(self._worktree_dir)])
            self._run_git(["worktree", "prune"])
            self._worktree_dir = None

    def _refuse_dangerous_paths(self) -> None:
        resolved = self._worktree_root.resolve()
        home = Path.home().resolve()
        root = Path("/").resolve()
        if resolved in {home, root} or resolved == self._repo_root.resolve():
            raise ValueError(
                f"Worktree root {resolved} resolves to a dangerous path. "
                "Refusing to operate."
            )

    def _git_head_sha(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self._repo_root),
        )
        return result.stdout.strip()

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(self._repo_root),
        )

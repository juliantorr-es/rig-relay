"""Repository source tracking test — verifies critical files are tracked by Git.

Uses git ls-files and git check-ignore, not Path.exists(). Git is the
source of truth for whether a file is tracked.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_ls_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=_REPO_ROOT
    )
    return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()


def _git_check_ignore(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], capture_output=True, cwd=_REPO_ROOT
    )
    return result.returncode == 0


# ── Critical source files that MUST be tracked ──────────────────

_CRITICAL_FRONTEND = [
    "frontend/desktop/index.html",
    "frontend/desktop/app.js",
    "frontend/desktop/websocket.js",
    "frontend/desktop/js/main.js",
    "frontend/desktop/js/state.js",
    "frontend/desktop/js/transport.js",
    "frontend/desktop/js/projection.js",
    "frontend/desktop/js/utils.js",
]

_CRITICAL_GOVERNANCE = [
    "AGENTS.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    "ATTRIBUTION.md",
]


def _git_untracked() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()


class TestCriticalFilesTracked:
    def test_frontend_index_tracked(self) -> None:
        tracked = _git_ls_files()
        for path in _CRITICAL_FRONTEND:
            assert path in tracked, f"{path} is not tracked by Git — check .gitignore"

    def test_frontend_files_not_ignored(self) -> None:
        for path in _CRITICAL_FRONTEND:
            ignored = _git_check_ignore(path)
            assert not ignored, f"{path} is ignored by Git — fix .gitignore"

    def test_governance_files_tracked_or_untracked(self) -> None:
        tracked = _git_ls_files()
        untracked = _git_untracked()
        for path in _CRITICAL_GOVERNANCE:
            present = path in tracked or (
                path in untracked and (_REPO_ROOT / path).is_file()
            )
            assert present, (
                f"{path} is not tracked and not on disk — file may be missing"
            )

    def test_governance_files_not_ignored(self) -> None:
        for path in _CRITICAL_GOVERNANCE:
            ignored = _git_check_ignore(path)
            assert not ignored, f"{path} is ignored by Git — fix .gitignore"

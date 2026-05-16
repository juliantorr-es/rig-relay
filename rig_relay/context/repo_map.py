"""Repo map builder — reads the repository topology from disk.

Builds a structured map of the repository: subsystems, entry points,
config files, schemas, docs, and tests. All path-based, no AST parsing.
Designed for the rig.get_context tool mode=map.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from rig_relay.context.models import RepoInfo, SubsystemEntry


def build_repo_info(workspace_root: Path | None = None) -> RepoInfo:
    """Build basic repository metadata from git."""
    root = workspace_root or Path.cwd()
    head = _git("rev-parse", "HEAD", cwd=root) or "unknown"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root) or "unknown"
    status = _git("status", "--short", cwd=root) or ""

    dirty_summary: dict[str, int] = {"modified": 0, "untracked": 0, "staged": 0}
    for line in status.splitlines():
        if not line.strip():
            continue
        prefix = line[:2]
        if "?" in prefix:
            dirty_summary["untracked"] += 1
        elif " " in prefix:
            dirty_summary["modified"] += 1
        else:
            dirty_summary["staged"] += 1

    return RepoInfo(
        root=str(root.resolve()),
        head=head[:16] if head != "unknown" else head,
        branch=branch,
        dirty_summary=dirty_summary,
    )


def build_subsystem_map(workspace_root: Path | None = None) -> list[SubsystemEntry]:
    """Build a structured subsystem map from the repository layout.

    Uses git-ls-files to discover tracked files, then groups by top-level
    directory. Detects entry points, config files, schemas, docs, and tests.
    """
    root = (workspace_root or Path.cwd()).resolve()
    files = _git_ls_files(root)

    # Group files by top-level directory
    dirs: dict[str, list[str]] = {}
    for f in files:
        top = f.split("/")[0] if "/" in f else f
        dirs.setdefault(top, []).append(f)

    subsystems: list[SubsystemEntry] = []
    for dir_name in sorted(dirs):
        dir_files = dirs[dir_name]
        entry_points = [
            f
            for f in dir_files
            if f.endswith(("__init__.py", "__main__.py", "entrypoint.py", "main.py"))
        ]
        config_files = [
            f for f in dir_files if f.endswith(("pyproject.toml", "toml", "cfg", "ini"))
        ]
        schemas = [
            f for f in dir_files if "schema" in f.lower() and f.endswith(".json")
        ]
        docs_list = [f for f in dir_files if f.startswith("docs/") or f.endswith(".md")]
        tests = [f for f in dir_files if "test_" in f or "_test" in f]

        # Only include non-empty subsystems
        if dir_files:
            subsystems.append(
                SubsystemEntry(
                    name=dir_name,
                    paths=dir_files[:20],
                    entry_points=entry_points[:5],
                    config_files=config_files[:5],
                    schemas=schemas[:10],
                    docs=docs_list[:10],
                    tests=tests[:10],
                )
            )

    return subsystems


def git_ls_files(root: Path) -> list[str]:
    """List all tracked files in a git repository."""
    return _git_ls_files(root)


def git_status_short(root: Path) -> str:
    """Return the short git status."""
    return _git("status", "--short", cwd=root) or ""


# ── Git helpers ──────────────────────────────────────────────────


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL, cwd=cwd or Path.cwd()
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _git_ls_files(root: Path) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], text=True, stderr=subprocess.DEVNULL, cwd=root
        )
        return [l.strip() for l in out.splitlines() if l.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

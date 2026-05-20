"""Integration bridge: governed context envelope compilation for AgentLoop.

Wires MissionContextCompiler into the context envelope path, replacing
ad-hoc assembly when ``governed_context_enabled`` is True.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess

from rig_relay.governance.mission_context_compiler import MissionContextCompiler
from rig_relay.governance.mission_context_packet import (
    MissionContextDirtyFileState,
    MissionContextPacket,
    MissionContextPacketReceipt,
)
from rig_relay.governance.mission_envelope import MissionDirtySummary, MissionEnvelope

_STATUS_LINE_MIN_LENGTH = 4


def _load_git_metadata(repo_root: Path) -> tuple[str | None, str | None]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch or None, head or None
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _collect_dirty_file_states(repo_root: Path) -> list[MissionContextDirtyFileState]:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain=v1"],
            capture_output=True,
            check=True,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    states: list[MissionContextDirtyFileState] = []
    for line in result.stdout.splitlines():
        if not line or len(line) < _STATUS_LINE_MIN_LENGTH:
            continue
        status = line[:2]
        raw_path = line[3:]
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[-1]
        rel = Path(raw_path).as_posix()

        file_path = repo_root / rel
        try:
            file_bytes = file_path.read_bytes()
            after_hash = f"sha256:{hashlib.sha256(file_bytes).hexdigest()}"
            byte_count = len(file_bytes)
        except (OSError, PermissionError):
            after_hash = None
            byte_count = None

        before_hash = None if status == "??" else after_hash

        states.append(
            MissionContextDirtyFileState(
                path=rel,
                status=f"{status[0]}{status[1]}",
                before_sha256=before_hash,
                after_sha256=after_hash,
                byte_count=byte_count,
                protected=False,
            )
        )

    return states


def _count_tracked_modified(states: list[MissionContextDirtyFileState]) -> int:
    return sum(
        1
        for s in states
        if s.status != "??" and (s.status[0] != " " or s.status[1] != " ")
    )


def _count_untracked(states: list[MissionContextDirtyFileState]) -> int:
    return sum(1 for s in states if s.status == "??")


def compile_governed_context(
    *,
    repo_root: Path,
    mission_id: str = "",
    title: str = "",
    acceptance_checks: list[str] | None = None,
    handoff_required: bool = False,
) -> tuple[MissionContextPacket, MissionContextPacketReceipt, list[str]]:
    """Compile a governed mission context packet from workspace state.

    Produces a content-light (SHA256-only) packet with git metadata,
    dirty file states, and source refs from canonical instruction files.
    Never embeds raw file content in the canonical artifact.
    """
    root_str = repo_root.resolve().as_posix()
    branch, head = _load_git_metadata(repo_root)
    branch = branch or "unknown"
    head = head or "unknown"
    dirty_states = _collect_dirty_file_states(repo_root)

    tracked_modified = _count_tracked_modified(dirty_states)
    untracked = _count_untracked(dirty_states)
    protected_dirty = 0

    envelope = MissionEnvelope(
        mission_id=mission_id or f"governed-context-{head[:7]}",
        title=title or "Governed context compilation",
        created_at=datetime.now(UTC).isoformat(),
        repo_root=root_str,
        branch=branch,
        head=head,
        dirty_summary=MissionDirtySummary(
            tracked_modified_count=tracked_modified,
            untracked_count=untracked,
            protected_dirty_count=protected_dirty,
        ),
        allowed_paths=[],
        protected_paths=[],
        instruction_paths=_discover_instruction_paths(repo_root),
        acceptance_checks=list(acceptance_checks or []),
        handoff_required=handoff_required,
    )

    source_paths = _collect_source_paths(repo_root, envelope.instruction_paths)

    compiler = MissionContextCompiler()
    result = compiler.compile(
        envelope,
        source_paths=source_paths,
        dirty_file_states=dirty_states,
        created_at=envelope.created_at,
    )

    missing_instruction_warnings = _collect_missing_instruction_warnings(repo_root)
    blocker_messages = [b.message for b in result.blockers]
    warning_messages = list(result.warnings)

    return (
        result.packet,
        result.receipt,
        blocker_messages + warning_messages + missing_instruction_warnings,
    )


def _discover_instruction_paths(repo_root: Path) -> list[str]:
    """Return all expected instruction paths, regardless of whether they exist."""
    candidates = ["AGENTS.md", "README.md", "CONTRIBUTING.md"]
    found: list[str] = []
    for rel in candidates:
        abs_path = repo_root / rel
        if abs_path.is_file():
            found.append(rel)
    return found


def _collect_missing_instruction_warnings(repo_root: Path) -> list[str]:
    candidates = ["AGENTS.md", "README.md", "CONTRIBUTING.md"]
    missing: list[str] = []
    for rel in candidates:
        abs_path = repo_root / rel
        if not abs_path.is_file():
            missing.append(f"Missing instruction file: {rel}")
    return missing


def _collect_source_paths(repo_root: Path, instruction_paths: list[str]) -> list[Path]:
    paths: list[Path] = []
    for rel in instruction_paths:
        abs_path = repo_root / rel
        if abs_path.is_file():
            paths.append(abs_path.resolve())
    return paths


__all__ = ["compile_governed_context"]

"""Digestion freshness markers — separate from stable repository identity.

Slice 1A: Desktop Repository Preview Intake v1.
Freshness changes when HEAD, dirty state, manifests, or instruction files
change. Repository identity remains stable across these changes.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path


def compute_freshness(
    repo_root: Path,
    head_sha: str | None,
    dirty_state_digest: str | None,
    manifest_paths: list[str],
    instruction_paths: list[str],
    previous_freshness: "DigestionFreshness | None" = None,
) -> "DigestionFreshness":
    """Compute freshness markers for the current digestion.

    Compares current state against a previous digestion to detect
    staleness and produce invalidation reasons.

    Args:
        repo_root: Repository root path.
        head_sha: Current HEAD SHA, or None.
        dirty_state_digest: SHA256 of canonical dirty file list, or None.
        manifest_paths: Paths to manifest files (pyproject.toml, Cargo.toml, etc.).
        instruction_paths: Paths to instruction files.
        previous_freshness: Freshness from a prior digestion for comparison,
            or None for initial digestion.
    """
    from rig_relay.digestion.models import DigestionFreshness

    now = datetime.now(UTC).isoformat()

    manifest_digests = _digest_files(repo_root, manifest_paths)
    instruction_digests = _digest_files(repo_root, instruction_paths)

    stale = False
    invalidation_reasons: list[str] = []

    if previous_freshness is not None:
        prev = previous_freshness
        if head_sha is not None and prev.head_sha is not None:
            if head_sha != prev.head_sha:
                stale = True
                invalidation_reasons.append("HEAD changed")
        if dirty_state_digest is not None and prev.dirty_state_digest is not None:
            if dirty_state_digest != prev.dirty_state_digest:
                stale = True
                invalidation_reasons.append("dirty state changed")
        for path, digest in manifest_digests.items():
            prev_digest = prev.manifest_digests.get(path)
            if prev_digest is not None and digest != prev_digest:
                stale = True
                invalidation_reasons.append(f"manifest changed: {path}")

    return DigestionFreshness(
        generated_at=now,
        head_sha=head_sha,
        dirty_state_digest=dirty_state_digest,
        manifest_digests=manifest_digests,
        instruction_file_digests=instruction_digests,
        stale=stale,
        invalidation_reasons=invalidation_reasons,
        freshness_ttl_seconds=300,
    )


def _digest_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Compute SHA256 digests of multiple files.

    Returns a dict mapping path to hex digest. Missing files are omitted.
    """
    digests: dict[str, str] = {}
    for rel_path in paths:
        filepath = root / rel_path
        if not filepath.is_file():
            continue
        try:
            content = filepath.read_bytes()
            digests[rel_path] = hashlib.sha256(content).hexdigest()
        except OSError:
            continue
    return digests


def compute_dirty_state_digest(dirty_paths: list[str]) -> str:
    """Compute a SHA256 digest from a sorted list of dirty file paths."""
    canonical = "\n".join(sorted(dirty_paths))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

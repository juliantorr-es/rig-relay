"""Sealed mode lane provisioning and policy."""
from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SealedLaneDescriptor(BaseModel):
    """Immutable descriptor of an isolated fixture lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    lane_root: str
    baseline_digest: str
    approved_relative_paths: list[str]
    approved_path_set_digest: str
    completion_output_root: str


class Refusal(Exception):
    """Exception raised when sealed policy is violated."""

    pass


class SealedLanePolicy:
    """Enforces boundaries and rules for a sealed lane."""

    def __init__(self, descriptor: SealedLaneDescriptor) -> None:
        self.descriptor = descriptor
        self.lane_root = Path(descriptor.lane_root).resolve(strict=True)
        self.approved_paths = {
            (self.lane_root / p).resolve(strict=False)
            for p in descriptor.approved_relative_paths
        }
        self.completion_output_root = Path(descriptor.completion_output_root).resolve(strict=True)

    def _validate_path(self, path: str | Path, check_exists: bool = False) -> Path:
        """Resolve a path and ensure it's safely within the lane root."""
        target = Path(path)
        if target.is_absolute():
            # If absolute, it must be exactly within lane_root
            resolved = target.resolve(strict=False)
        else:
            resolved = (self.lane_root / target).resolve(strict=False)

        # Basic traversal/escape check
        try:
            resolved.relative_to(self.lane_root)
        except ValueError:
            raise Refusal(f"Path escapes lane root: {target}")

        if check_exists and not resolved.exists():
            raise Refusal(f"Path does not exist: {target}")
            
        if not check_exists and not resolved.parent.exists():
            raise Refusal(f"Parent directory of path does not exist: {target}")

        if ".rig/relay/" in str(resolved) or "confidential" in resolved.name:
            # Simple heuristic matching the 'reject any read or write directed at confidential-evidence-sink'
            if ".build/rig-relay/confidential" in str(resolved):
                raise Refusal(f"Access to confidential evidence sink denied: {target}")

        return resolved

    def validate_read_target(self, path: str | Path) -> Path:
        resolved = self._validate_path(path, check_exists=True)
        if resolved not in self.approved_paths:
            raise Refusal(f"Read target not in approved path set: {path}")
        return resolved

    def validate_write_target(self, path: str | Path) -> Path:
        resolved = self._validate_path(path, check_exists=False)
        if resolved not in self.approved_paths:
            raise Refusal(f"Write target not in approved path set: {path}")
        return resolved

    def validate_test_command(self, cmd: list[str]) -> None:
        # Example naive validation: ensure it's in a known approved list or simple format
        allowed_prefixes = [("uv", "run", "pytest"), ("pytest",)]
        matched = False
        for prefix in allowed_prefixes:
            if tuple(cmd[:len(prefix)]) == prefix:
                matched = True
                break
        if not matched:
            raise Refusal(f"Unapproved test command: {cmd}")

    def refuse_prohibited_capability(self, name: str) -> str:
        raise Refusal(f"Capability '{name}' is strictly prohibited in sealed mode")

    def calculate_changed_path_digests(self, baseline_manifest: dict[str, str], current_manifest: dict[str, str]) -> tuple[dict[str, str], str]:
        """Compare manifests and return changes (path -> diff_hash) and overall diff digest."""
        changes = {}
        hasher = hashlib.sha256()
        for path, digest in current_manifest.items():
            baseline_digest = baseline_manifest.get(path)
            if baseline_digest != digest:
                diff_rep = f"{path}:{baseline_digest}->{digest}".encode()
                changes[path] = hashlib.sha256(diff_rep).hexdigest()
                hasher.update(diff_rep)
        return changes, hasher.hexdigest()

"""GitHub Truth Evidence Store — content-light, append-only, file-backed.

Provides a durable persistence seam for read-only GitHub truth observations
produced by GitHubTruthAdapter. Writes content-light evidence records to an
append-only JSONL ledger under ``.build/rig-relay/github-truth/``.

Each observation record is content-light: repository identity (hashed),
operation kind, observed remote identifiers, timestamps, status/conclusion,
hashes/digests, and provenance. Raw secrets, OAuth tokens, raw private
content, and unrestricted response dumps are forbidden.

The ledger is append-only and idempotent by observation digest.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TRUTH_ROOT = REPO_ROOT / ".build" / "rig-relay" / "github-truth"

CONTENT_LIGHT_FORBIDDEN = frozenset({
    "access_token",
    "Authorization",
    "Bearer",
    "token",
    "secret",
    "api_key",
    "private_key",
    "credential",
})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def _content_light_check(record: dict[str, Any]) -> list[str]:
    """Scan a record for forbidden content markers. Returns list of found markers (empty = clean)."""
    serialized = json.dumps(record, sort_keys=True).lower()
    found: list[str] = []
    for forbidden in CONTENT_LIGHT_FORBIDDEN:
        if forbidden.lower() in serialized:
            found.append(forbidden)
    return found


class GitHubTruthStore:
    """Append-only, file-backed store for content-light GitHub truth observations.

    Thread-safe for sequential use. Not thread-safe for concurrent writers
    (callers should serialize writes).
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_TRUTH_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def _ledger_path(self) -> Path:
        return self.root / "observations.jsonl"

    def _digest_for(self, record: dict[str, Any]) -> str:
        """Compute observation digest from canonical JSON for idempotency."""
        return _sha256(json.dumps(record, sort_keys=True))

    def append_observation(
        self,
        operation_kind: str,
        repository_hash: str,
        owner: str,
        repo: str,
        status: str,
        observed_digest: str | None = None,
        verification_status: str | None = None,
        remote_head_sha: str | None = None,
        expected_sha: str | None = None,
        ref: str | None = None,
        accepted_head_present: bool | None = None,
        follow_on_commits_count: int | None = None,
        follow_on_head_sha: str | None = None,
        ci_state: str | None = None,
        overall_state: str | None = None,
        passed_count: int | None = None,
        failed_count: int | None = None,
        pending_count: int | None = None,
        suggested_next_action: str | None = None,
        error_kind: str | None = None,
        warnings: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Append a content-light GitHub truth observation to the ledger.

        Returns the written record dict. Idempotent: if a record with the
        same observation_digest already exists, returns the existing record
        without writing a duplicate.
        """
        record: dict[str, Any] = {
            "schema_version": "rig.relay.github_truth_observation.v1",
            "operation_kind": operation_kind,
            "repository_hash": repository_hash,
            "observed_at": _now_iso(),
            "status": status,
            "observed_digest": observed_digest,
            "verification_status": verification_status,
            "remote_head_sha": remote_head_sha,
            "expected_sha": expected_sha,
            "ref": ref,
            "accepted_head_present": accepted_head_present,
            "follow_on_commits_count": follow_on_commits_count,
            "follow_on_head_sha": follow_on_head_sha,
            "ci_state": ci_state,
            "overall_state": overall_state,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "suggested_next_action": suggested_next_action,
            "error_kind": error_kind,
            "warnings": warnings or [],
            "content_light": True,
        }
        # Remove None values for cleaner storage
        record = {k: v for k, v in record.items() if v is not None}
        # Merge extra fields (bounded, controlled)
        record.update({k: v for k, v in extra.items() if v is not None})

        # Content-light enforcement
        forbidden = _content_light_check(record)
        if forbidden:
            raise ValueError(
                f"Observation contains forbidden content markers: {forbidden}"
            )

        digest = self._digest_for(record)
        record["observation_digest"] = digest

        # Idempotency: check if already present
        existing = self.get_observation(digest)
        if existing is not None:
            return existing

        line = json.dumps(record, sort_keys=True) + "\n"
        with self._ledger_path().open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

        return record

    def get_observation(self, observation_digest: str) -> dict[str, Any] | None:
        """Find an observation by digest. Returns None if not found."""
        path = self._ledger_path()
        if not path.is_file():
            return None
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("observation_digest") == observation_digest:
                return record
        return None

    def list_observations(
        self,
        operation_kind: str | None = None,
        repository_hash: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List observations matching optional filters.

        Returns most recent first, up to ``limit``.
        """
        path = self._ledger_path()
        if not path.is_file():
            return []
        results: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if operation_kind and record.get("operation_kind") != operation_kind:
                continue
            if repository_hash and record.get("repository_hash") != repository_hash:
                continue
            if since and record.get("observed_at", "") < since:
                continue
            results.append(record)
        results.sort(key=lambda r: r.get("observed_at", ""), reverse=True)
        return results[:limit]

    def observation_count(self, operation_kind: str | None = None) -> int:
        """Count observations, optionally filtered by operation kind."""
        return len(self.list_observations(operation_kind=operation_kind))

    def last_observation(
        self, operation_kind: str, repository_hash: str
    ) -> dict[str, Any] | None:
        """Get the most recent observation for a given operation and repo."""
        results = self.list_observations(
            operation_kind=operation_kind, repository_hash=repository_hash, limit=1
        )
        return results[0] if results else None


__all__ = ["GitHubTruthStore"]

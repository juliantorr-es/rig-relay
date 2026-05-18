"""File-backed context cache for ContextDigestionResult.

Provides atomic writes, TTL expiry, and commit-aware invalidation.
No SQLite — stores JSON artifacts in a cache directory.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from rig_relay.context.digester import ContextDigestionResult


class ContextCache:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 300) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(
        self, repo_root: Path, source_event_range: tuple[int, int], source_commit: str
    ) -> str:
        repo_identity = hashlib.sha256(
            str(repo_root.resolve()).encode("utf-8")
        ).hexdigest()[:16]
        min_seq, max_seq = source_event_range
        raw = f"{repo_identity}:{source_commit}:{min_seq}:{max_seq}"
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        safe = key.replace(":", "_")
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if not path.is_file():
            return None

        try:
            mtime = path.stat().st_mtime
            if mtime:
                mtime_dt = datetime.fromtimestamp(mtime, tz=UTC)
                age = (datetime.now(UTC) - mtime_dt).total_seconds()
                if age > self.ttl_seconds:
                    return None

            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if data.get("schema_version") != "rig.relay.context_digestion.v1":
            return None

        return data

    def set(self, key: str, result: ContextDigestionResult) -> None:
        path = self._cache_path(key)
        payload = {
            "schema_version": result.schema_version,
            "generated_at": result.generated_at,
            "source_commit": result.source_commit,
            "workspace_id": result.workspace_id,
            "active_lane_count": result.active_lane_count,
            "active_lanes": result.active_lanes,
            "owned_paths": result.owned_paths,
            "do_not_touch_paths": result.do_not_touch_paths,
            "recent_conflicts": result.recent_conflicts,
            "release_gate_status": result.release_gate_status,
            "open_blocker_ids": result.open_blocker_ids,
            "evidence_paths": result.evidence_paths,
            "redaction_status": result.redaction_status,
            "source_event_range": list(result.source_event_range),
            "digest_sha256": result.digest_sha256,
        }

        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", prefix="cache_", dir=str(self.cache_dir)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def invalidate(self, key: str) -> None:
        path = self._cache_path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def is_fresh(self, key: str, current_commit: str) -> bool:
        cached = self.get(key)
        if cached is None:
            return False
        return cached.get("source_commit") == current_commit


__all__ = ["ContextCache"]

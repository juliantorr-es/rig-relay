from __future__ import annotations

from pathlib import Path
import time

from rig_relay.context.cache import ContextCache
from rig_relay.context.digester import ContextDigestionResult


def _make_result(
    *, source_commit: str = "abc123", source_event_range: tuple[int, int] = (1, 5)
) -> ContextDigestionResult:
    return ContextDigestionResult(
        generated_at="2026-01-01T00:00:00Z",
        source_commit=source_commit,
        workspace_id="sha256:def456",
        active_lane_count=1,
        active_lanes=[
            {
                "session_id": "s1",
                "task_id": "t1",
                "status": "running",
                "reserved_paths": [],
                "last_heartbeat": "2026-01-01T00:00:00Z",
            }
        ],
        owned_paths=["src/a.py"],
        do_not_touch_paths=["src/a.py"],
        source_event_range=source_event_range,
        digest_sha256="sha256:test123",
    )


def test_cache_set_and_get_roundtrip(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result()
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)
    cached = cache.get(key)

    assert cached is not None
    assert cached["source_commit"] == "abc123"
    assert cached["active_lane_count"] == 1
    assert cached["owned_paths"] == ["src/a.py"]
    assert cached["digest_sha256"] == "sha256:test123"


def test_cache_ttl_expiry(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=1)

    result = _make_result()
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)

    cached = cache.get(key)
    assert cached is not None

    time.sleep(1.1)

    cached_after = cache.get(key)
    assert cached_after is None


def test_cache_invalidate(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result()
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)
    assert cache.get(key) is not None

    cache.invalidate(key)
    assert cache.get(key) is None


def test_cache_atomic_write(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result()
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)

    cached = cache.get(key)
    assert cached is not None
    assert cached["digest_sha256"] == "sha256:test123"
    assert cached["active_lane_count"] == 1


def test_cache_key_deterministic(tmp_path: Path) -> None:
    cache = ContextCache(tmp_path / "cache", ttl_seconds=300)

    key1 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 5), source_commit="abc123"
    )
    key2 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 5), source_commit="abc123"
    )

    assert key1 == key2
    assert key1.startswith("sha256:")


def test_cache_key_different_commit(tmp_path: Path) -> None:
    cache = ContextCache(tmp_path / "cache", ttl_seconds=300)

    key1 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 5), source_commit="abc123"
    )
    key2 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 5), source_commit="def456"
    )

    assert key1 != key2


def test_cache_key_different_range(tmp_path: Path) -> None:
    cache = ContextCache(tmp_path / "cache", ttl_seconds=300)

    key1 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 5), source_commit="abc123"
    )
    key2 = cache.cache_key(
        repo_root=Path("/tmp/repo"), source_event_range=(1, 10), source_commit="abc123"
    )

    assert key1 != key2


def test_cache_handles_malformed_file(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result()
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache_path = cache._cache_path(key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("not valid json {{{", encoding="utf-8")

    cached = cache.get(key)
    assert cached is None


def test_cache_is_fresh_true(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result(source_commit="abc123")
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)
    assert cache.is_fresh(key, "abc123") is True


def test_cache_is_fresh_false_different_commit(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    result = _make_result(source_commit="abc123")
    key = cache.cache_key(
        repo_root=tmp_path,
        source_event_range=result.source_event_range,
        source_commit=result.source_commit,
    )

    cache.set(key, result)
    assert cache.is_fresh(key, "def456") is False


def test_cache_is_fresh_missing_key(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    assert cache.is_fresh("sha256:nonexistent", "abc123") is False


def test_cache_invalidate_nonexistent(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    cache.invalidate("sha256:nonexistent")


def test_cache_get_nonexistent(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ContextCache(cache_dir, ttl_seconds=300)

    assert cache.get("sha256:nonexistent") is None

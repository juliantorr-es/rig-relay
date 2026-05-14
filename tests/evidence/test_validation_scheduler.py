"""Tests for validation scheduler — locks, coalescing, parallel policy, lifecycle."""

from __future__ import annotations

from pathlib import Path

from rig_relay.evidence.validation_scheduler import (
    PARALLEL_DISABLED,
    PARALLEL_ENABLED,
    PARALLEL_NOT_APPLICABLE,
    PARALLEL_REFUSED,
    PHASE_EDIT,
    PHASE_PRE_REPORT,
    ValidationLock,
    ValidationSchedulerStore,
    apply_parallel_policy,
    check_lifecycle_policy,
)


class TestValidationSchedulerStore:
    def test_acquire_lock_succeeds(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        acquired, blocking = store.acquire_lock("sha256:test1")
        assert acquired
        assert blocking is None

    def test_duplicate_lock_blocked(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        acquired1, _ = store.acquire_lock("sha256:dup")
        assert acquired1

        acquired2, blocking = store.acquire_lock("sha256:dup")
        assert not acquired2
        assert blocking == "sha256:dup"

    def test_release_lock_allows_reacquire(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        store.acquire_lock("sha256:rel")
        store.release_lock("sha256:rel")

        acquired, _ = store.acquire_lock("sha256:rel")
        assert acquired

    def test_has_active_lock_true(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        store.acquire_lock("sha256:act")
        assert store.has_active_lock("sha256:act")

    def test_has_active_lock_false_after_release(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        store.acquire_lock("sha256:act")
        store.release_lock("sha256:act")
        assert not store.has_active_lock("sha256:act")

    def test_different_keys_independent(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        a1, _ = store.acquire_lock("sha256:a")
        a2, _ = store.acquire_lock("sha256:b")
        assert a1
        assert a2

    def test_stale_lock_allows_reacquire(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        store.acquire_lock("sha256:stale")
        # Mark as stale by writing old timestamp
        from datetime import UTC, datetime, timedelta
        import json

        path = store._lock_path("sha256:stale")
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        lock = ValidationLock(
            cache_key="sha256:stale", started_at=old, last_heartbeat_at=old
        )
        path.write_text(json.dumps(lock.model_dump(mode="json")), encoding="utf-8")

        # Should be stale and allow reacquire
        acquired, _ = store.acquire_lock("sha256:stale")
        assert acquired

    def test_release_stale_locks(self, tmp_path: Path) -> None:
        store = ValidationSchedulerStore(tmp_path / "sched")
        from datetime import UTC, datetime, timedelta
        import json

        stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()

        for key in ("sha256:s1", "sha256:s2"):
            path = store._lock_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = ValidationLock(
                cache_key=key, started_at=stale, last_heartbeat_at=stale
            )
            path.write_text(json.dumps(lock.model_dump(mode="json")), encoding="utf-8")

        # Add a fresh lock
        store.acquire_lock("sha256:fresh")

        released = store.release_stale_locks(max_age_seconds=600)
        assert released >= 2
        assert store.active_lock_count >= 1


class TestApplyParallelPolicy:
    def test_non_pytest_not_applicable(self) -> None:
        argv = ["uv", "run", "ruff", "check"]
        mod, status, warn = apply_parallel_policy(argv, "auto", None, "loadfile")
        assert status == PARALLEL_NOT_APPLICABLE
        assert mod == argv

    def test_pytest_injects_xdist(self) -> None:
        argv = ["uv", "run", "pytest", "tests/"]
        mod, status, warn = apply_parallel_policy(argv, "auto", 2, "loadfile")
        if status == PARALLEL_REFUSED:
            assert warn is not None
        else:
            assert status == PARALLEL_ENABLED
            assert "-n" in mod
            assert "2" in mod
            assert "--dist" in mod

    def test_existing_xdist_not_duplicated(self) -> None:
        argv = ["uv", "run", "pytest", "-n", "4", "tests/"]
        mod, status, warn = apply_parallel_policy(argv, "auto", None, "loadfile")
        assert status == PARALLEL_NOT_APPLICABLE

    def test_xdist_disabled_stays_serial(self) -> None:
        argv = ["uv", "run", "pytest", "tests/"]
        mod, status, warn = apply_parallel_policy(argv, "disabled", None, "loadfile")
        assert status == PARALLEL_DISABLED

    def test_single_file_focused_stays_serial(self) -> None:
        argv = ["uv", "run", "pytest", "tests/test_foo.py"]
        mod, status, warn = apply_parallel_policy(argv, "auto", None, "loadfile")
        assert status == PARALLEL_NOT_APPLICABLE
        assert "focused" in (warn or "")

    def test_force_overrides_focused(self) -> None:
        argv = ["uv", "run", "pytest", "tests/test_foo.py"]
        mod, status, warn = apply_parallel_policy(argv, "force", 2, "loadfile")
        if status == PARALLEL_REFUSED:
            assert warn is not None
        else:
            assert status == PARALLEL_ENABLED
            assert "-n" in mod

    def test_max_workers_capped(self) -> None:
        argv = ["uv", "run", "pytest", "tests/"]
        mod, status, _ = apply_parallel_policy(argv, "auto", 1, "loadscope")
        if status == PARALLEL_REFUSED:
            pass
        else:
            assert status == PARALLEL_ENABLED
            n_index = mod.index("-n")
            assert mod[n_index + 1] == "1"

    def test_schema_validation_stays_serial(self) -> None:
        argv = ["uv", "run", "pytest", "tests/test_validate_schemas.py"]
        mod, status, warn = apply_parallel_policy(argv, "auto", 4, "loadfile")
        # If it contains "schema" in path, it's treated as schema validation
        # Actually _is_schema_validation checks the arg for "schema" substring
        # "test_validate_schemas.py" contains "schema" -> treated as schema validation
        assert status == PARALLEL_NOT_APPLICABLE

    def test_ruff_pyright_not_applicable(self) -> None:
        argv = ["ruff", "check", "."]
        mod, status, _ = apply_parallel_policy(argv, "auto", 4, "loadfile")
        assert status == PARALLEL_NOT_APPLICABLE


class TestCheckLifecyclePolicy:
    def test_edit_phase_full_suite_warns(self) -> None:
        warnings = check_lifecycle_policy(PHASE_EDIT, "python", ["pytest"])
        assert "full_suite_during_edit_phase" in warnings

    def test_pre_report_no_warning(self) -> None:
        warnings = check_lifecycle_policy(PHASE_PRE_REPORT, "python", ["pytest"])
        assert len(warnings) == 0

    def test_edit_phase_quick_profile_no_warning(self) -> None:
        warnings = check_lifecycle_policy(PHASE_EDIT, "quick", ["ruff"])
        assert len(warnings) == 0


class TestValidationLock:
    def test_is_stale_old_timestamp(self) -> None:
        from datetime import UTC, datetime, timedelta

        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        lock = ValidationLock(cache_key="k", started_at=old, last_heartbeat_at=old)
        assert lock.is_stale(max_age_seconds=300)

    def test_not_stale_recent(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        lock = ValidationLock(cache_key="k", started_at=now, last_heartbeat_at=now)
        assert not lock.is_stale(max_age_seconds=300)

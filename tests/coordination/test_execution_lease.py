"""Tests for rig_relay.coordination.execution_lease — P2c ExecutionLease models and store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.coordination.execution_lease import (
    ExecutionLease,
    ExecutionLeaseResult,
    ExecutionLeaseStatus,
    ExecutionLeaseStore,
)
from rig_relay.runtime.execution_request import ExecutionRequest


def _request(**overrides: object) -> ExecutionRequest:
    kwargs: dict[str, object] = {
        "request_id": "req-001",
        "argv": ["pytest", "tests/"],
        "cwd": "/home/user/project",
        "timeout_ms": 30000,
        "purpose": "Run tests",
    }
    kwargs.update(overrides)
    return ExecutionRequest(**kwargs)  # type: ignore[arg-type]


class TestExecutionLeaseStatus:
    def test_all_values_present(self) -> None:
        assert list(ExecutionLeaseStatus) == [
            ExecutionLeaseStatus.PENDING,
            ExecutionLeaseStatus.ACTIVE,
            ExecutionLeaseStatus.RELEASED,
            ExecutionLeaseStatus.EXPIRED,
            ExecutionLeaseStatus.CANCELLED,
            ExecutionLeaseStatus.FAILED,
        ]

    def test_string_values(self) -> None:
        assert ExecutionLeaseStatus.ACTIVE.value == "active"
        assert ExecutionLeaseStatus.RELEASED.value == "released"
        assert ExecutionLeaseStatus.EXPIRED.value == "expired"
        assert ExecutionLeaseStatus.PENDING.value == "pending"
        assert ExecutionLeaseStatus.CANCELLED.value == "cancelled"
        assert ExecutionLeaseStatus.FAILED.value == "failed"


class TestExecutionLeaseValidation:
    def test_unknown_fields_rejected(self) -> None:
        req = _request()
        with pytest.raises(ValidationError):
            ExecutionLease(
                lease_id="lease-001",
                request=req,
                acquired_at="2026-06-01T10:00:00",
                expires_at="2026-06-01T10:05:00",
                status=ExecutionLeaseStatus.ACTIVE,
                unknown_field="bad",  # type: ignore[arg-type]
            )

    def test_no_raw_fields(self) -> None:
        req = _request()
        lease = ExecutionLease(
            lease_id="lease-001",
            request=req,
            acquired_at="2026-06-01T10:00:00",
            expires_at="2026-06-01T10:05:00",
            status=ExecutionLeaseStatus.ACTIVE,
        )
        dumped = lease.model_dump(mode="json")
        assert "stdout" not in dumped
        assert "stderr" not in dumped
        assert "output" not in dumped
        assert "content" not in dumped
        assert "diff" not in dumped
        assert "shell" not in dumped


class TestExecutionLeaseResultValidation:
    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionLeaseResult(
                status="granted",
                unknown_field="bad",  # type: ignore[arg-type]
            )

    def test_minimal_result(self) -> None:
        result = ExecutionLeaseResult(status="not_found")
        assert result.status == "not_found"
        assert result.lease is None
        assert result.error_kind is None
        assert result.refusal_reason is None


class TestExecutionLeaseStoreAcquire:
    def test_acquire_creates_active_lease_with_expires_at(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        result = store.acquire(req, ttl_seconds=300)

        assert result.status == "granted"
        assert result.lease is not None
        assert result.lease.status == ExecutionLeaseStatus.ACTIVE
        assert result.lease.acquired_at <= result.lease.expires_at
        assert result.lease.lease_id == "req-001"

    def test_acquire_sets_expires_at_correctly(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        before = datetime.now(UTC)
        result = store.acquire(req, ttl_seconds=120)

        assert result.lease is not None
        expires = datetime.fromisoformat(result.lease.expires_at.replace("Z", "+00:00"))
        # expires should be 120s in the future, within tolerance
        delta = (expires - before).total_seconds()
        assert 110 <= delta <= 130

    def test_acquire_zero_ttl_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        result = store.acquire(req, ttl_seconds=0)

        assert result.status == "error"
        assert result.error_kind == "invalid_ttl"
        assert result.lease is None

    def test_acquire_negative_ttl_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        result = store.acquire(req, ttl_seconds=-10)

        assert result.status == "error"
        assert result.error_kind == "invalid_ttl"

    def test_acquire_writes_file(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        lease_file = tmp_path / "req-001.json"
        assert lease_file.is_file()
        content = lease_file.read_text(encoding="utf-8")
        assert "active" in content
        assert "pytest" in content


class TestExecutionLeaseStoreRead:
    def test_read_returns_lease(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        lease = store.read("req-001")
        assert lease is not None
        assert lease.lease_id == "req-001"
        assert lease.status == ExecutionLeaseStatus.ACTIVE

    def test_read_missing_returns_none(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        lease = store.read("nonexistent")
        assert lease is None

    def test_read_malformed_file_returns_none(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        lease = store.read("bad")
        assert lease is None

    def test_read_after_release(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)
        store.release("req-001")

        lease = store.read("req-001")
        assert lease is not None
        assert lease.status == ExecutionLeaseStatus.RELEASED
        assert lease.released_at is not None


class TestExecutionLeaseStoreRelease:
    def test_release_marks_released(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        result = store.release("req-001")
        assert result.status == "released"
        assert result.lease is not None
        assert result.lease.status == ExecutionLeaseStatus.RELEASED

    def test_release_missing_returns_not_found(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        result = store.release("nonexistent")

        assert result.status == "not_found"
        assert result.error_kind == "lease_not_found"
        assert result.lease is None

    def test_release_already_released_returns_structured(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)
        store.release("req-001")

        result = store.release("req-001")
        assert result.status == "already_released"
        assert result.error_kind == "lease_already_released"
        assert result.lease is not None

    def test_release_expired_returns_structured(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        # Force expiry via expire_stale with a far-future now
        far_future = datetime.now(UTC) + timedelta(hours=1)
        store.expire_stale(now=far_future)

        result = store.release("req-001")
        assert result.status == "already_expired"
        assert result.error_kind == "lease_already_expired"
        assert result.lease is not None


class TestExecutionLeaseStoreExpireStale:
    def test_expire_stale_marks_active_leases(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        # Use a time after expiry
        future = datetime.now(UTC) + timedelta(seconds=600)
        expired = store.expire_stale(now=future)

        assert len(expired) == 1
        assert expired[0].lease_id == "req-001"
        assert expired[0].status == ExecutionLeaseStatus.EXPIRED

    def test_expire_stale_skips_non_active(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)
        store.release("req-001")

        future = datetime.now(UTC) + timedelta(seconds=600)
        expired = store.expire_stale(now=future)

        assert len(expired) == 0

        # Verify still released
        lease = store.read("req-001")
        assert lease is not None
        assert lease.status == ExecutionLeaseStatus.RELEASED

    def test_expire_stale_only_expires_past_leases(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)

        # Use a time before expiry
        past = datetime.now(UTC) + timedelta(seconds=10)
        expired = store.expire_stale(now=past)

        assert len(expired) == 0

        # Verify still active
        lease = store.read("req-001")
        assert lease is not None
        assert lease.status == ExecutionLeaseStatus.ACTIVE


class TestExecutionLeaseStoreList:
    def test_list_leases_returns_deterministic_order(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)

        req_a = _request(request_id="req-a", argv=["echo", "a"])
        req_b = _request(request_id="req-b", argv=["echo", "b"])
        req_c = _request(request_id="req-c", argv=["echo", "c"])

        store.acquire(req_c, ttl_seconds=300)
        store.acquire(req_a, ttl_seconds=300)
        store.acquire(req_b, ttl_seconds=300)

        leases = store.list_leases()
        assert len(leases) == 3
        ids = [l.lease_id for l in leases]
        assert ids == sorted(ids)  # alphabetical

    def test_list_leases_empty(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        assert store.list_leases() == []

    def test_list_leases_skips_malformed(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()
        store.acquire(req, ttl_seconds=300)
        (tmp_path / "garbage.json").write_text("not json", encoding="utf-8")

        leases = store.list_leases()
        assert len(leases) == 1  # only the valid one


class TestExecutionLeaseStoreSafety:
    def test_unsafe_lease_id_with_dot_prefix_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        with pytest.raises(ValueError, match="must not start with"):
            store.read("..secret")

    def test_unsafe_lease_id_with_slash_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        with pytest.raises((ValueError,)):
            store.read("../etc/passwd")

    def test_unsafe_lease_id_with_backslash_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        with pytest.raises((ValueError,)):
            store.read("..\\etc\\passwd")

    def test_empty_lease_id_rejected(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        with pytest.raises(ValueError, match="lease_id must be non-empty"):
            store.read("")


class TestExecutionLeaseSerialization:
    def test_lease_schema_version(self, tmp_path: Path) -> None:
        req = _request()
        lease = ExecutionLease(
            lease_id="lease-001",
            request=req,
            acquired_at="2026-06-01T10:00:00",
            expires_at="2026-06-01T10:05:00",
            status=ExecutionLeaseStatus.ACTIVE,
        )
        assert lease.schema_version == "rig.relay.execution_lease.v1"

    def test_result_schema_version(self) -> None:
        result = ExecutionLeaseResult(status="granted")
        assert result.schema_version == "rig.relay.execution_lease_result.v1"

    def test_lease_json_dump(self, tmp_path: Path) -> None:
        req = _request()
        lease = ExecutionLease(
            lease_id="lease-001",
            request=req,
            acquired_at="2026-06-01T10:00:00",
            expires_at="2026-06-01T10:05:00",
            status=ExecutionLeaseStatus.ACTIVE,
        )
        dumped = lease.model_dump(mode="json")
        assert dumped["lease_id"] == "lease-001"
        assert dumped["request"]["argv"] == ["pytest", "tests/"]
        assert dumped["status"] == "active"

    def test_result_json_dump(self) -> None:
        req = _request()
        lease = ExecutionLease(
            lease_id="lease-001",
            request=req,
            acquired_at="2026-06-01T10:00:00",
            expires_at="2026-06-01T10:05:00",
            status=ExecutionLeaseStatus.ACTIVE,
        )
        result = ExecutionLeaseResult(status="granted", lease=lease)
        dumped = result.model_dump(mode="json")
        assert dumped["status"] == "granted"
        assert dumped["lease"]["lease_id"] == "lease-001"


class TestExecutionLeaseFullCycle:
    def test_acquire_read_release_cycle(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req = _request()

        # Acquire
        acquire_result = store.acquire(req, ttl_seconds=300)
        assert acquire_result.status == "granted"
        assert acquire_result.lease is not None
        lease_id = acquire_result.lease.lease_id

        # Read
        lease = store.read(lease_id)
        assert lease is not None
        assert lease.status == ExecutionLeaseStatus.ACTIVE

        # Release
        release_result = store.release(lease_id)
        assert release_result.status == "released"

        # Read after release
        lease = store.read(lease_id)
        assert lease is not None
        assert lease.status == ExecutionLeaseStatus.RELEASED
        assert lease.released_at is not None


class TestExecutionLeaseConflictDetection:
    def test_same_worktree_path_refused(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt1"
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"

        result2 = store.acquire(req2, ttl_seconds=300)
        assert result2.status == "refused"
        assert result2.error_kind == "active_worktree_lease_exists"
        assert result2.lease is None

    def test_same_workspace_id_without_worktree_refused(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a",
            argv=["echo", "a"],
            workspace_id="ws-1",
            worktree_path=None,
        )
        req2 = _request(
            request_id="req-b",
            argv=["echo", "b"],
            workspace_id="ws-1",
            worktree_path=None,
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"

        result2 = store.acquire(req2, ttl_seconds=300)
        assert result2.status == "refused"
        assert result2.error_kind == "active_workspace_lease_exists"

    def test_released_lease_does_not_block(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt1"
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"
        store.release("req-a")

        result2 = store.acquire(req2, ttl_seconds=300)
        assert result2.status == "granted"

    def test_expired_lease_does_not_block(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt1"
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"

        # Manually expire the lease
        far_future = datetime.now(UTC) + timedelta(hours=1)
        store.expire_stale(now=far_future)

        result2 = store.acquire(req2, ttl_seconds=300)
        assert result2.status == "granted"

    def test_distinct_worktree_paths_can_coexist(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt2"
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"

        result2 = store.acquire(req2, ttl_seconds=300)
        assert result2.status == "granted"

    def test_conflict_result_schema_valid(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt1"
        )

        store.acquire(req1, ttl_seconds=300)
        result = store.acquire(req2, ttl_seconds=300)

        assert result.status == "refused"
        assert result.error_kind == "active_worktree_lease_exists"
        assert result.refusal_reason is not None
        assert "req-a" in result.refusal_reason

        # Verify JSON serialization
        dumped = result.model_dump(mode="json")
        assert dumped["status"] == "refused"
        assert dumped["error_kind"] == "active_worktree_lease_exists"

    def test_enforce_exclusive_false_allows_same_worktree(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req1 = _request(
            request_id="req-a", argv=["echo", "a"], worktree_path="/tmp/wt1"
        )
        req2 = _request(
            request_id="req-b", argv=["echo", "b"], worktree_path="/tmp/wt1"
        )

        result1 = store.acquire(req1, ttl_seconds=300)
        assert result1.status == "granted"

        result2 = store.acquire(req2, ttl_seconds=300, enforce_exclusive_worktree=False)
        assert result2.status == "granted"

    def test_list_leases_deterministic_preserved(self, tmp_path: Path) -> None:
        store = ExecutionLeaseStore(tmp_path)
        req_a = _request(request_id="req-a", argv=["echo", "a"])
        req_b = _request(request_id="req-b", argv=["echo", "b"])
        store.acquire(req_b, ttl_seconds=300)
        store.acquire(req_a, ttl_seconds=300)

        leases = store.list_leases()
        ids = [l.lease_id for l in leases]
        assert ids == sorted(ids)

"""Tests for rig_relay.coordination.lease_manager — PathLeaseManager.

Covers lease acquisition, release, renewal, conflict detection, stale
behavior, owner enforcement, and content-light contracts.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.coordination.lease_manager import (
    LeaseClaimResult,
    PathLease,
    PathLeaseManager,
)


def _manager(tmp_path: Path) -> PathLeaseManager:
    return PathLeaseManager(tmp_path / ".build" / "rig-relay" / "coordination")


# ── Model tests ───────────────────────────────────────────────────────


class TestPathLeaseModel:
    def test_extra_forbid(self) -> None:
        with pytest.raises((ValidationError, ValueError, TypeError)):
            PathLease.model_validate({
                "session_id": "s1",
                "task_id": "t1",
                "mode": "write",
                "paths": ["a.py"],
                "expires_at": "2026-01-01T00:00:00",
                "status": "active",
                "extra_field": "x",
            })

    def test_minimal_valid(self) -> None:
        lease = PathLease(
            session_id="s1",
            task_id="t1",
            mode="write",
            paths=["a.py"],
            expires_at="2026-01-01T00:00:00",
        )
        assert lease.session_id == "s1"
        assert lease.mode == "write"


class TestLeaseClaimResultModel:
    def test_extra_forbid(self) -> None:
        with pytest.raises((ValidationError, ValueError, TypeError)):
            LeaseClaimResult.model_validate({"status": "granted", "unknown_field": "x"})

    def test_minimal_valid(self) -> None:
        r = LeaseClaimResult(status="granted")
        assert r.status == "granted"
        assert r.lease is None


# ── PathLeaseManager tests ─────────────────────────────────────────────


class TestClaimPaths:
    def test_claim_success(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        result = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.status == "granted"
        assert result.lease is not None
        assert result.lease.session_id == "sess-a"
        assert result.lease.task_id == "task-a"
        assert result.lease.mode == "write"
        assert "src/main.py" in result.lease.paths

    def test_claim_empty_paths(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        result = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=[],
            ttl_seconds=120,
        )
        assert result.status == "error"
        assert result.error_kind == "no_paths"


class TestReadReadCoexistence:
    def test_read_leases_coexist(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        r1 = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert r1.status == "granted"

        r2 = mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert r2.status == "granted"

        r3 = mgr.claim_paths(
            session_id="sess-c",
            task_id="task-c",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert r3.status == "granted"


class TestExclusiveWriteConflicts:
    def test_exclusive_write_conflicts_with_existing_write(
        self, tmp_path: Path
    ) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.status == "conflict"

    def test_exclusive_write_conflicts_with_existing_read(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.status == "conflict"

    def test_write_conflicts_with_existing_read(self, tmp_path: Path) -> None:
        """New exclusive_write conflicts with existing shared_read."""
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.status == "conflict"

    def test_read_conflicts_with_existing_write(self, tmp_path: Path) -> None:
        """New shared_read conflicts with existing exclusive_write."""
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="shared_read",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.status == "conflict"


class TestSameOwnerRenewal:
    def test_same_owner_renews(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        r1 = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert r1.status == "granted"

        r2 = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert r2.status == "granted"


class TestReleaseOwnerEnforcement:
    def test_release_by_non_owner_refused(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.release_paths(
            session_id="sess-b", task_id="task-b", paths=["src/main.py"]
        )
        assert result.status in ("not_found", "not_owner")

    def test_release_by_owner_succeeds(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.release_paths(
            session_id="sess-a", task_id="task-a", paths=["src/main.py"]
        )
        assert result.status == "granted"


class TestRenewLease:
    def test_renew_active_lease(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        result = mgr.renew_lease(
            session_id="sess-a",
            task_id="task-a",
            paths=["src/main.py"],
            ttl_seconds=300,
        )
        assert result.status == "granted"

    def test_renew_nonexistent_lease(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        result = mgr.renew_lease(
            session_id="sess-a",
            task_id="task-a",
            paths=["src/main.py"],
            ttl_seconds=300,
        )
        assert result.status == "not_found"


class TestQueryActiveLeases:
    def test_query_after_claim(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        active = mgr.query_active_leases()
        assert len(active) == 1
        assert active[0].session_id == "sess-a"

    def test_query_by_session(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        mgr.claim_paths(
            session_id="sess-b",
            task_id="task-b",
            mode="shared_read",
            paths=["src/other.py"],
            ttl_seconds=120,
        )
        active_a = mgr.query_active_leases(session_id="sess-a")
        assert len(active_a) == 1
        assert active_a[0].session_id == "sess-a"

    def test_query_empty_after_release(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        mgr.release_paths(session_id="sess-a", task_id="task-a", paths=["src/main.py"])
        active = mgr.query_active_leases()
        assert len(active) == 0


class TestContentLight:
    def test_path_lease_has_no_forbidden_fields(self, tmp_path: Path) -> None:
        """PathLease model dump has no raw content fields."""
        mgr = _manager(tmp_path)
        result = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        assert result.lease is not None
        dumped = json.dumps(result.lease.model_dump(mode="json"))
        for forbidden in (
            "stdout",
            "stderr",
            "content",
            "prompt",
            "secret",
            "diff",
            "patch",
        ):
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in PathLease dump"
            )

    def test_lease_claim_result_has_no_forbidden_fields(self, tmp_path: Path) -> None:
        """LeaseClaimResult model dump has no raw content fields."""
        mgr = _manager(tmp_path)
        result = mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        dumped = json.dumps(result.model_dump(mode="json"))
        for forbidden in (
            "stdout",
            "stderr",
            "content",
            "prompt",
            "secret",
            "diff",
            "patch",
        ):
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in LeaseClaimResult dump"
            )


# ── Coordination event schema validation ──────────────────────────────


class TestCoordinationEventSchema:
    def test_path_reserved_event_has_no_forbidden_fields(self, tmp_path: Path) -> None:
        """The coordination event written by reserve_paths has no forbidden fields."""
        mgr = _manager(tmp_path)
        mgr.claim_paths(
            session_id="sess-a",
            task_id="task-a",
            mode="exclusive_write",
            paths=["src/main.py"],
            ttl_seconds=120,
        )
        events_path = (
            tmp_path / ".build" / "rig-relay" / "coordination" / "events.jsonl"
        )
        if events_path.is_file():
            raw = events_path.read_text(encoding="utf-8")
            for line in raw.strip().split("\n"):
                if line:
                    event = json.loads(line)
                    payload = event.get("payload", {})
                    payload_str = json.dumps(payload)
                    for forbidden in (
                        "stdout",
                        "stderr",
                        "content",
                        "prompt",
                        "secret",
                    ):
                        assert forbidden not in payload_str, (
                            f"Found forbidden field '{forbidden}' in coordination event"
                        )

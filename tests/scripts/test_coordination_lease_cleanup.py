"""Tests for coordination lease cleanup script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rig_relay_cleanup_coordination_leases import (
    _delete_files,
    _parse_iso_datetime,
    _scan_leases,
    _scan_tasks,
    run_cleanup,
)

pytestmark = [pytest.mark.migration]

def test_parse_iso_datetime_with_z():
    dt = _parse_iso_datetime("2026-05-13T17:17:15.165891+00:00")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 13


def test_parse_iso_datetime_z_suffix():
    dt = _parse_iso_datetime("2026-05-13T17:17:15Z")
    assert dt.year == 2026


def test_dry_run_empty_directory(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    tasks_dir = tmp_path / "tasks"
    leases_dir.mkdir(parents=True)
    tasks_dir.mkdir(parents=True)

    result = run_cleanup(coordination_root=tmp_path, dry_run=True, confirm=False)
    assert result["action"] in ("none", "dry_run")


def test_dry_run_with_stale_lease(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    lease = {
        "schema_version": "rig.relay.coordination.path_reservation.v1",
        "session_id": "session_test",
        "task_id": "task_test",
        "mode": "write",
        "paths": ["/tmp/test.py"],
        "ttl_seconds": 300,
        "status": "stale",
        "created_at": "2026-05-13T17:17:15+00:00",
        "expires_at": "2026-05-13T17:22:15+00:00",
    }
    lease_file = leases_dir / "test_lease.json"
    lease_file.write_text(json.dumps(lease))

    result = run_cleanup(coordination_root=tmp_path, dry_run=True, confirm=False)
    assert result["action"] == "dry_run"
    assert result["stats"]["leases_stale"] == 1
    assert result["stats"]["leases_cleanable"] == 1
    assert result["stats"]["total_cleanable"] >= 1


def test_dry_run_with_expired_active_lease(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    lease = {
        "schema_version": "rig.relay.coordination.path_reservation.v1",
        "session_id": "session_test",
        "task_id": "task_test",
        "mode": "write",
        "paths": ["/tmp/test.py"],
        "ttl_seconds": 300,
        "status": "active",
        "created_at": "2025-01-01T00:00:00+00:00",
        "expires_at": "2025-01-01T00:05:00+00:00",
    }
    lease_file = leases_dir / "expired_lease.json"
    lease_file.write_text(json.dumps(lease))

    result = run_cleanup(coordination_root=tmp_path, dry_run=True, confirm=False)
    assert result["stats"]["leases_expired"] == 1
    assert result["stats"]["leases_cleanable"] == 1


def test_dry_run_with_active_unexpired_lease(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    lease = {
        "schema_version": "rig.relay.coordination.path_reservation.v1",
        "session_id": "session_test",
        "task_id": "task_test",
        "mode": "write",
        "paths": ["/tmp/test.py"],
        "ttl_seconds": 3600,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": future,
    }
    lease_file = leases_dir / "active_lease.json"
    lease_file.write_text(json.dumps(lease))

    result = run_cleanup(coordination_root=tmp_path, dry_run=True, confirm=False)
    assert result["stats"]["leases_active"] == 1
    assert result["stats"]["leases_cleanable"] == 0


def test_dry_run_skips_no_active_lease_removal(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    lease = {
        "schema_version": "rig.relay.coordination.path_reservation.v1",
        "session_id": "session_test",
        "task_id": "task_test",
        "mode": "write",
        "paths": ["/tmp/test.py"],
        "ttl_seconds": 3600,
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": future,
    }
    lease_file = leases_dir / "active_lease.json"
    lease_file.write_text(json.dumps(lease))

    # confirm + no archive should NOT delete active leases
    result = run_cleanup(
        coordination_root=tmp_path, dry_run=False, confirm=True, archive=False
    )
    assert result["stats"]["leases_active"] == 1
    assert result["stats"]["leases_cleanable"] == 0
    # active file should still exist
    assert lease_file.is_file()


def test_delete_files_removes_files(tmp_path: Path):
    f1 = tmp_path / "f1.json"
    f2 = tmp_path / "f2.json"
    f1.write_text("{}")
    f2.write_text("{}")

    entries = [{"_path": str(f1)}, {"_path": str(f2)}]
    errors = _delete_files(entries)
    assert not errors
    assert not f1.is_file()
    assert not f2.is_file()


def test_delete_files_handles_missing_file(tmp_path: Path):
    entries = [{"_path": str(tmp_path / "nonexistent.json")}]
    errors = _delete_files(entries)
    assert not errors


def test_scan_leases_categorizes_correctly(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)

    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    leases = {
        "stale.json": {"status": "stale", "expires_at": past},
        "released.json": {"status": "released", "expires_at": past},
        "active_future.json": {"status": "active", "expires_at": future},
        "active_expired.json": {"status": "active", "expires_at": past},
    }

    for name, data in leases.items():
        (leases_dir / name).write_text(json.dumps(data))

    result = _scan_leases(leases_dir)
    assert len(result["stale"]) == 1
    assert len(result["released"]) == 1
    assert len(result["expired"]) == 1
    assert len(result["active"]) == 1


def test_scan_tasks_categorizes_correctly(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    tasks = {
        "stale.json": {"status": "stale", "expires_at": past},
        "released.json": {"status": "released", "expires_at": past},
        "active_future.json": {"status": "active", "expires_at": future},
        "active_expired.json": {"status": "active", "expires_at": past},
    }

    for name, data in tasks.items():
        (tasks_dir / name).write_text(json.dumps(data))

    result = _scan_tasks(tasks_dir)
    assert len(result["stale"]) == 1
    assert len(result["released"]) == 1
    assert len(result["expired"]) == 1
    assert len(result["active"]) == 1


def test_archive_moves_files_instead_of_deleting(tmp_path: Path):
    leases_dir = tmp_path / "leases" / "paths"
    leases_dir.mkdir(parents=True)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)

    from datetime import UTC, datetime, timedelta

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    lease = {
        "status": "stale",
        "expires_at": past,
        "session_id": "test",
        "task_id": "test",
        "mode": "write",
        "paths": [],
        "ttl_seconds": 300,
    }
    lease_file = leases_dir / "stale_lease.json"
    lease_file.write_text(json.dumps(lease))

    result = run_cleanup(
        coordination_root=tmp_path, dry_run=False, confirm=True, archive=True
    )
    assert result["action"] == "archived"
    assert not lease_file.is_file()
    archive_path = tmp_path / "archived" / "leases" / "paths" / "stale_lease.json"
    assert archive_path.is_file()


def test_main_missing_root_fails(tmp_path: Path):
    from scripts.rig_relay_cleanup_coordination_leases import main

    exit_code = main(["--coordination-root", str(tmp_path / "nonexistent")])
    assert exit_code == 1

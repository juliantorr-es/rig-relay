from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.events.storage import (
    LocalFileBackend,
    MemoryBackend,
    StorageConfig,
    StorageError,
)
from rig_relay.events.wal import WriteAheadLog

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]


def _make_entry(event_id: str, event_type: str = "test.event") -> dict:
    return {
        "schema_version": "rig.event.envelope.v1",
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "test",
        "correlation_id": f"corr_{event_id}",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
    }


@pytest.fixture
def wal_dir(tmp_path: Path) -> Path:
    return tmp_path


def _backend(wal_dir: Path) -> LocalFileBackend:
    return LocalFileBackend(StorageConfig(path=wal_dir / "store.jsonl"))


def _wal(backend: LocalFileBackend, wal_dir: Path) -> WriteAheadLog:
    return WriteAheadLog(backend, wal_dir / "wal.jsonl")


def test_wal_write_appends_to_wal_file(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    entry = _make_entry("evt_001")
    wal.write(entry)
    wal_path = wal_dir / "wal.jsonl"
    assert wal_path.exists()
    with open(wal_path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    assert "evt_001" in lines[0]


def test_wal_commit_writes_to_main_store(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    wal.write(_make_entry("evt_001"))
    wal.write(_make_entry("evt_002"))
    committed = wal.commit()
    assert committed == 2
    results = backend.read()
    assert len(results) == 2
    assert results[0]["event_id"] == "evt_001"
    assert results[1]["event_id"] == "evt_002"


def test_wal_recover_returns_uncommitted_entries(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    wal.write(_make_entry("evt_pending_1"))
    wal.write(_make_entry("evt_pending_2"))
    recovered = wal.recover()
    assert len(recovered) == 2
    assert recovered[0]["event_id"] == "evt_pending_1"
    assert recovered[1]["event_id"] == "evt_pending_2"


def test_wal_recover_returns_empty_when_all_committed(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    wal.write(_make_entry("evt_001"))
    wal.commit()
    recovered = wal.recover()
    assert recovered == []


def test_wal_truncate_removes_committed_entries_from_wal(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    wal.write(_make_entry("evt_001"))
    wal.commit()
    wal.truncate()
    wal_path = wal_dir / "wal.jsonl"
    content = wal_path.read_text()
    assert content == "" or content.strip() == ""


def test_wal_does_not_lose_entries_across_close_reopen_cycle(wal_dir: Path):
    backend_a = _backend(wal_dir)
    wal_a = _wal(backend_a, wal_dir)
    wal_a.write(_make_entry("evt_001"))
    wal_a.write(_make_entry("evt_002"))
    wal_a.commit()

    backend_b = LocalFileBackend(StorageConfig(path=wal_dir / "store.jsonl"))
    results = backend_b.read()
    assert len(results) == 2
    assert results[0]["event_id"] == "evt_001"
    assert results[1]["event_id"] == "evt_002"


def test_wal_write_crash_no_commit_recover_returns_entry(wal_dir: Path):
    backend_a = _backend(wal_dir)
    wal_a = _wal(backend_a, wal_dir)
    wal_a.write(_make_entry("evt_crashed"))

    wal_b = WriteAheadLog(
        LocalFileBackend(StorageConfig(path=wal_dir / "store.jsonl")),
        wal_dir / "wal.jsonl",
    )
    recovered = wal_b.recover()
    assert len(recovered) == 1
    assert recovered[0]["event_id"] == "evt_crashed"


def test_wal_respects_content_light_validation(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    entry = _make_entry("evt_001")
    del entry["event_id"]
    with pytest.raises(StorageError, match="event_id required"):
        wal.write(entry)


def test_wal_with_memory_backend():
    mem = MemoryBackend()
    wal = WriteAheadLog(mem, Path("/tmp/test_wal_mem.jsonl"))
    wal.write(_make_entry("evt_001"))
    wal.write(_make_entry("evt_002"))
    committed = wal.commit()
    assert committed == 2
    results = mem.read()
    assert len(results) == 2


def test_sequential_writes_are_ordered_correctly(wal_dir: Path):
    backend = _backend(wal_dir)
    wal = _wal(backend, wal_dir)
    for i in range(5):
        wal.write(_make_entry(f"evt_{i:03d}"))
    wal.commit()
    results = backend.read()
    assert [r["event_id"] for r in results] == [
        "evt_000",
        "evt_001",
        "evt_002",
        "evt_003",
        "evt_004",
    ]

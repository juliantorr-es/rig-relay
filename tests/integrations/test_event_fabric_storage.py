from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rig_relay.events.storage import (
    LocalFileBackend,
    MemoryBackend,
    StorageConfig,
    StorageError,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]


def _make_entry(
    event_id: str, event_type: str = "test.event", **kwargs: object
) -> dict:
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
        "payload": {},
        **kwargs,
    }


@pytest.fixture
def file_backend(tmp_path: Path) -> LocalFileBackend:
    return LocalFileBackend(StorageConfig(path=tmp_path / "store.jsonl"))


@pytest.fixture
def memory_backend() -> MemoryBackend:
    return MemoryBackend()


def test_local_file_backend_appends_and_reads_entries(file_backend: LocalFileBackend):
    entry = _make_entry("evt_001")
    file_backend.append(entry)
    results = file_backend.read()
    assert len(results) == 1
    assert results[0]["event_id"] == "evt_001"
    assert results[0]["event_type"] == "test.event"


def test_local_file_backend_checksums_are_deterministic(tmp_path: Path):
    backend_a = LocalFileBackend(StorageConfig(path=tmp_path / "store_a.jsonl"))
    backend_b = LocalFileBackend(StorageConfig(path=tmp_path / "store_b.jsonl"))
    entry = _make_entry("evt_001")
    backend_a.append(entry)
    backend_b.append(entry)
    assert backend_a.checksum() == backend_b.checksum()
    assert len(backend_a.checksum()) == 64


def test_local_file_backend_compact_respects_max_entries(tmp_path: Path):
    backend = LocalFileBackend(
        StorageConfig(path=tmp_path / "store.jsonl", max_entries=3)
    )
    for i in range(5):
        backend.append(_make_entry(f"evt_{i:03d}"))
    assert len(backend.read()) == 5
    removed = backend.compact()
    assert removed == 2
    results = backend.read()
    assert len(results) == 3
    assert results[0]["event_id"] == "evt_002"
    assert results[-1]["event_id"] == "evt_004"


def test_local_file_backend_compact_respects_max_bytes(tmp_path: Path):
    backend = LocalFileBackend(
        StorageConfig(path=tmp_path / "store.jsonl", max_bytes=500)
    )
    for i in range(5):
        backend.append(_make_entry(f"evt_{i:03d}"))
    assert len(backend.read()) == 5
    removed = backend.compact()
    assert removed > 0
    assert backend.size_bytes() <= 500


def test_memory_backend_returns_empty_when_empty(memory_backend: MemoryBackend):
    assert memory_backend.read() == []


def test_memory_backend_appends_multiple_entries_in_order(
    memory_backend: MemoryBackend,
):
    for i in range(3):
        memory_backend.append(_make_entry(f"evt_{i:03d}"))
    results = memory_backend.read()
    assert len(results) == 3
    assert results[0]["event_id"] == "evt_000"
    assert results[1]["event_id"] == "evt_001"
    assert results[2]["event_id"] == "evt_002"


def test_backends_reject_entries_without_event_id(
    file_backend: LocalFileBackend, memory_backend: MemoryBackend
):
    entry = {"event_type": "test.event", "content_light": True, "payload": {}}
    with pytest.raises(StorageError, match="event_id required"):
        file_backend.append(entry)
    with pytest.raises(StorageError, match="event_id required"):
        memory_backend.append(entry)


def test_backends_reject_forbidden_field_names(
    file_backend: LocalFileBackend, memory_backend: MemoryBackend
):
    entry = _make_entry("evt_001", payload={"token_prefix": "ghp_abc123"})
    with pytest.raises(StorageError, match="raw_content_field_detected"):
        file_backend.append(entry)
    with pytest.raises(StorageError, match="raw_content_field_detected"):
        memory_backend.append(entry)


def test_storage_exists_false_before_append_true_after(file_backend: LocalFileBackend):
    assert not file_backend.exists()
    file_backend.append(_make_entry("evt_001"))
    assert file_backend.exists()


def test_local_file_backend_size_bytes_returns_correct_size(
    file_backend: LocalFileBackend,
):
    assert file_backend.size_bytes() == 0
    file_backend.append(_make_entry("evt_001"))
    size = file_backend.size_bytes()
    assert size > 0
    assert isinstance(size, int)


def test_local_file_backend_fsync_durable_after_append(tmp_path: Path):
    backend = LocalFileBackend(StorageConfig(path=tmp_path / "store.jsonl", fsync=True))
    entry = _make_entry("evt_fsync")
    backend.append(entry)
    with open(tmp_path / "store.jsonl") as f:
        content = f.read()
    assert "evt_fsync" in content
    parsed = json.loads(content.strip())
    assert parsed["event_id"] == "evt_fsync"


def test_empty_backend_checksum_is_deterministic():
    mem = MemoryBackend()
    empty_hash = hashlib.sha256(b"").hexdigest()
    assert mem.checksum() == empty_hash

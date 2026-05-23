"""Tests for ReceiptStore protocol and FilesystemReceiptStore."""

from __future__ import annotations

from pathlib import Path

from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptActorTier,
    ReceiptEnvelope,
    ReceiptSubject,
    ReceiptSubjectKind,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore, ReceiptStore


def _make_envelope(
    session_id: str = "s1", kind: str = "tool_invocation"
) -> ReceiptEnvelope:
    return ReceiptEnvelope(
        envelope_id=f"env-{session_id}-test",
        receipt_kind=kind,
        actor=ReceiptActor(
            actor_id="agent-1",
            actor_kind=ReceiptActorKind.AGENT,
            display_name="Test Agent",
            authority_tier=ReceiptActorTier.ADMINISTRATIVE,
        ),
        subject=ReceiptSubject(
            subject_id="sub-1",
            subject_kind=ReceiptSubjectKind.TOOL_INVOCATION,
            session_id=session_id,
        ),
        created_at="2026-05-14T12:00:00",
    )


class TestFilesystemReceiptStore:
    def test_append_creates_file(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        env = _make_envelope()
        path = store.append(env)
        assert path.is_file()
        assert path.suffix == ".json"

    def test_get_returns_envelope(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        env = _make_envelope()
        store.append(env)
        retrieved = store.get(env.envelope_id)
        assert retrieved is not None
        assert retrieved.envelope_id == env.envelope_id
        assert retrieved.receipt_kind == env.receipt_kind

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        assert store.get("nonexistent") is None

    def test_list_returns_newest_first(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        for i in range(5):
            env = _make_envelope(session_id="s1", kind=f"test-{i}")
            store.append(env)
        results = store.list(limit=10)
        assert len(results) == 5

    def test_list_respects_limit(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        for i in range(10):
            env = _make_envelope(session_id="s1", kind=f"test-{i}")
            store.append(env)
        results = store.list(limit=3)
        assert len(results) == 3

    def test_list_by_session_filters(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        store.append(_make_envelope(session_id="s1", kind="a"))
        store.append(_make_envelope(session_id="s2", kind="b"))
        s1_results = store.list_by_session("s1")
        assert len(s1_results) == 1
        assert s1_results[0].subject.session_id == "s1"

    def test_count(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        assert store.count() == 0
        store.append(_make_envelope(session_id="s1"))
        assert store.count() == 1
        store.append(_make_envelope(session_id="s1"))
        assert store.count() == 2

    def test_conforms_to_protocol(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        assert isinstance(store, ReceiptStore)

    def test_sharded_directory(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        env = _make_envelope()
        store.append(env)
        shard = env.envelope_id[:2]
        assert (tmp_path / "envelopes" / shard).is_dir()

    def test_corrupted_file_returns_none(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path)
        env = _make_envelope()
        store.append(env)
        path = store._envelope_path(env.envelope_id)
        path.write_text("{invalid json", encoding="utf-8")
        assert store.get(env.envelope_id) is None

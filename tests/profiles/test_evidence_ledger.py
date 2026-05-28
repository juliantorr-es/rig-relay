from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.profiles._evidence_ledger import (
    Y3ProfileEvent,
    Y3ProfileEventKind,
    load_y3_events,
    persist_y3_event,
    verify_y3_ledger_integrity,
)


def _make_event(
    event_id: str = "evt-001",
    kind: Y3ProfileEventKind = Y3ProfileEventKind.PROFILE_SELECTED,
    provider: str = "openai",
    model_id: str = "gpt-4o",
    profile_id: str = "rig.native.governed.v1",
) -> Y3ProfileEvent:
    return Y3ProfileEvent(
        event_id=event_id,
        event_kind=kind,
        provider=provider,
        model_id=model_id,
        profile_id=profile_id,
    )


def test_persist_y3_event_writes_to_jsonl_file():
    with tempfile.TemporaryDirectory() as td:
        event = _make_event("evt-persist-1")
        digest = persist_y3_event(event, td)
        assert digest, "persist returned empty digest"

        ledger_path = Path(td) / "y3_profile_evidence_events.v1.jsonl"
        assert ledger_path.exists(), "ledger file not created"
        content = ledger_path.read_text()
        assert "evt-persist-1" in content


def test_load_y3_events_reads_back_persisted_events():
    with tempfile.TemporaryDirectory() as td:
        event = _make_event("evt-load-1", Y3ProfileEventKind.PROFILE_REGISTERED)
        persist_y3_event(event, td)

        loaded = load_y3_events(td)
        assert len(loaded) == 1
        assert loaded[0].event_id == "evt-load-1"
        assert loaded[0].event_kind == Y3ProfileEventKind.PROFILE_REGISTERED


def test_event_digests_are_deterministic():
    event = _make_event("evt-deterministic")
    digest1 = event.compute_digest()
    digest2 = event.compute_digest()
    assert digest1 == digest2


def test_event_digests_differ_for_different_content():
    event_a = _make_event("evt-diff-a", Y3ProfileEventKind.PROFILE_SELECTED)
    event_b = _make_event("evt-diff-b", Y3ProfileEventKind.PROFILE_REFUSED)
    digest_a = event_a.compute_digest()
    digest_b = event_b.compute_digest()
    assert digest_a != digest_b


def test_verify_integrity_passes_for_clean_ledger():
    with tempfile.TemporaryDirectory() as td:
        for i in range(3):
            event = _make_event(f"evt-clean-{i}")
            persist_y3_event(event, td)

        ok, corrupt = verify_y3_ledger_integrity(td)
        assert ok is True
        assert len(corrupt) == 0


def test_verify_integrity_detects_corrupted_json_line():
    with tempfile.TemporaryDirectory() as td:
        event = _make_event("evt-valid")
        persist_y3_event(event, td)

        ledger_path = Path(td) / "y3_profile_evidence_events.v1.jsonl"
        content = ledger_path.read_text()
        corrupted = content + "this is not valid json\n"
        ledger_path.write_text(corrupted)

        ok, corrupt = verify_y3_ledger_integrity(td)
        assert ok is False
        assert len(corrupt) >= 1


def test_verify_integrity_detects_tampered_digest():
    with tempfile.TemporaryDirectory() as td:
        event = _make_event("evt-tamper")
        persist_y3_event(event, td)

        ledger_path = Path(td) / "y3_profile_evidence_events.v1.jsonl"
        content = ledger_path.read_text()
        tampered = content.replace(
            '"event_digest":"', '"event_digest":"sha256:deadbeef'
        )
        ledger_path.write_text(tampered)

        ok, corrupt = verify_y3_ledger_integrity(td)
        assert ok is False
        assert len(corrupt) >= 1


def test_persist_event_with_empty_store_root_defaults_to_current_repo():
    event = _make_event("evt-default-root")
    digest = persist_y3_event(event)
    assert digest, "persist with default root returned empty digest"


def test_load_from_nonexistent_file_returns_empty_list():
    with tempfile.TemporaryDirectory() as td:
        loaded = load_y3_events(td)
        assert loaded == []


def test_all_thirteen_event_kinds_have_valid_enum_values():
    assert len(Y3ProfileEventKind) == 13
    kinds = {k for k in Y3ProfileEventKind}
    assert len(kinds) == 13
    for k in Y3ProfileEventKind:
        assert isinstance(k.value, str)
        assert len(k.value) > 0


def test_y3profileevent_content_light_is_always_true():
    event = _make_event()
    assert event.content_light is True

    event2 = Y3ProfileEvent(
        event_id="evt-test",
        event_kind=Y3ProfileEventKind.PROFILE_SELECTED,
        content_light=False,
    )
    assert event2.content_light is False


def test_y3profileevent_compute_digest_includes_sha256_prefix():
    event = _make_event()
    digest = event.compute_digest()
    assert digest.startswith("sha256:")
    assert len(digest) > len("sha256:")

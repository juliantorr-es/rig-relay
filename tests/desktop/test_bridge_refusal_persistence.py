from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.adversarial,
    pytest.mark.substrate,
]

from jsonschema import ValidationError, validate

from rig_relay.desktop.bridge_lifecycle_trace import BridgeLifecycleTraceWriter
from rig_relay.desktop.bridge_refusals import (
    build_bridge_refusal_envelope,
    build_bridge_refusal_trace_event,
    enforce_intent,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
_LIFECYCLE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_lifecycle_event.v1.schema.json"


def _lifecycle_schema() -> dict:
    return json.loads(_LIFECYCLE_SCHEMA_PATH.read_text(encoding="utf-8"))


_ALLOWED = frozenset({
    "refresh_projection",
    "safe_intent",
    "provider_intent",
    "network_intent",
    "release_intent",
    "safe_mutate",
    "dangerous",
    "leaky_intent",
    "path_intent",
})


def _make_refusal_trace(
    intent_kind: str = "unknown_xyz",
    mutation_class: str = "",
    capability_required: list[str] | None = None,
    payload: dict | None = None,
) -> dict:
    result = enforce_intent(
        intent_kind=intent_kind,
        trace_id="trace_persist_001",
        schema_version="rig.relay.frontend_intent.v1",
        mutation_class=mutation_class,
        capability_required=capability_required,
        payload=payload,
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed

    refusal = build_bridge_refusal_envelope(
        refusal_kind=result.refusal_kind,
        reason_code=result.reason_code,
        human_safe_message=result.message,
        trace_id="trace_persist_001",
        frontend_session_id="fs_persist_001",
        backend_session_id="bs_persist_001",
        parent_message_id="msg_inbound_persist",
        refused_intent_kind=intent_kind,
        mutation_class=mutation_class,
        capability_required=capability_required,
    )

    return build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind=intent_kind,
        refusal_message_id=str(refusal.get("message_id", "")),
        inbound_message_id="msg_inbound_persist",
        refusal_reason=result.message,
        mutation_class=mutation_class,
        capability_required=capability_required,
        trace_id="trace_persist_001",
        frontend_session_id="fs_persist_001",
        backend_session_id="bs_persist_001",
        handshake_id="hs_persist_001",
        source="bridge_refusal_builder",
    )


# ── Trace writer instantiation ────────────────────────────────────────────


def test_writer_creates_default_path() -> None:
    writer = BridgeLifecycleTraceWriter()
    assert writer.output_path is not None


def test_writer_accepts_custom_path(tmp_path: Path) -> None:
    path = tmp_path / "custom_trace.jsonl"
    writer = BridgeLifecycleTraceWriter(path)
    assert writer.output_path == path


# ── Single event persistence ─────────────────────────────────────────────


def test_refusal_emitted_persisted_to_jsonl(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    events = writer.read_events()
    assert len(events) == 1
    assert events[0]["event"] == "refusal_emitted"


def test_persisted_jsonl_validates_against_schema(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    events = writer.read_events()
    validate(instance=events[0], schema=_lifecycle_schema())


# ── Multiple events ──────────────────────────────────────────────────────


def test_multiple_refusals_append_multiple_rows(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    for i in range(5):
        event = _make_refusal_trace(f"intent_{i}")
        writer.write_event(event)
    assert writer.event_count() == 5


# ── Trace field preservation ─────────────────────────────────────────────


def test_persisted_event_preserves_trace_id(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["trace_id"] == "trace_persist_001"


def test_persisted_event_preserves_message_ids(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["inbound_message_id"] == "msg_inbound_persist"
    assert persisted["refusal_message_id"].startswith("msg_")
    assert persisted["inbound_message_id"] != persisted["refusal_message_id"]


def test_parent_message_id_links_to_inbound(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["inbound_message_id"] == "msg_inbound_persist"


def test_session_ids_preserved(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["frontend_session_id"] == "fs_persist_001"
    assert persisted["backend_session_id"] == "bs_persist_001"


def test_persisted_event_contains_refusal_kind(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["refusal_kind"] == "unknown_intent_kind"


def test_persisted_event_has_content_light_fields(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("leaky_intent", payload={"raw_prompt": "secret"})
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert persisted["content_light"] is True
    assert persisted["redaction_status"] == "content_light"


def test_persisted_event_has_hashes(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_intent_xyz")
    writer.write_event(event)
    persisted = writer.read_events()[0]
    assert "refusal_reason_hash" in persisted
    assert len(persisted["refusal_reason_hash"]) > 0


# ── Content-light: no raw unsafe values persisted ────────────────────────


def test_raw_github_token_not_persisted(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace(
        "leaky_intent", payload={"token": "ghp_abcdef1234567890"}
    )
    writer.write_event(event)
    raw_text = writer.output_path.read_text(encoding="utf-8")
    assert "ghp_abcdef1234567890" not in raw_text


def test_raw_path_not_persisted(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace(
        "path_intent", payload={"file": "/Users/user/secret.txt"}
    )
    writer.write_event(event)
    raw_text = writer.output_path.read_text(encoding="utf-8")
    assert "/Users/user/secret.txt" not in raw_text


def test_raw_prompt_not_persisted(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace(
        "leaky_intent", payload={"raw_prompt": "secret prompt content"}
    )
    writer.write_event(event)
    raw_text = writer.output_path.read_text(encoding="utf-8")
    assert "secret prompt content" not in raw_text


# ── Malformed event rejection ────────────────────────────────────────────


def test_malformed_event_rejected_by_writer(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    bad_event = {
        "schema_version": "rig.relay.bridge_lifecycle_event.v1",
        "event_id": "x",
    }
    with pytest.raises(ValidationError):
        writer.write_event(bad_event)
    assert writer.event_count() == 0


# ── No side-effect contamination ──────────────────────────────────────────


def test_trace_writer_does_not_write_release_gate(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    release_gate_files = list(tmp_path.rglob("*release_gate*"))
    assert len(release_gate_files) == 0


def test_trace_writer_does_not_write_coordination_ledger(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    coord_files = list(tmp_path.rglob("*coordination*"))
    assert len(coord_files) == 0


def test_trace_writer_does_not_write_otel_files(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    otel_files = list(tmp_path.rglob("*otel*"))
    assert len(otel_files) == 0


def test_no_github_provider_code_called(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    raw = writer.output_path.read_text(encoding="utf-8")
    assert "github_provider" not in raw.lower()


def test_no_hidden_home_directory_files(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    hidden = [f for f in tmp_path.rglob("*") if f.name.startswith(".")]
    assert len(hidden) == 0


# ── Persistence failure does not throw ───────────────────────────────────


def test_persistence_failure_does_not_throw(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(
        tmp_path / "nonexistent_subdir" / "nested_subdir" / "trace.jsonl"
    )
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    persisted = writer.read_events()
    assert len(persisted) == 1


# ── No competing sink created ────────────────────────────────────────────


def test_only_one_writer_file_created(tmp_path: Path) -> None:
    writer = BridgeLifecycleTraceWriter(tmp_path / "trace.jsonl")
    event = _make_refusal_trace("unknown_xyz")
    writer.write_event(event)
    jsonl_files = list(tmp_path.rglob("*.jsonl"))
    assert len(jsonl_files) == 1

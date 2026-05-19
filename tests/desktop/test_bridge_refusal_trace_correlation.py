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

from jsonschema import validate

from rig_relay.desktop.bridge_refusals import (
    _hash_reason,
    build_bridge_refusal_envelope,
    build_bridge_refusal_trace_event,
    enforce_intent,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
_ENVELOPE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_envelope.v1.schema.json"
_LIFECYCLE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_lifecycle_event.v1.schema.json"


def _envelope_schema() -> dict:
    return json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))


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
    "big_intent",
})


def _refuse_and_trace(
    intent_kind: str,
    trace_id: str = "trace_corr_001",
    frontend_sid: str = "fs_corr_001",
    backend_sid: str = "bs_corr_001",
    mutation_class: str = "",
    capability_required: list[str] | None = None,
    **extra: object,
) -> tuple[dict, dict]:
    result = enforce_intent(
        intent_kind=intent_kind,
        trace_id=trace_id,
        mutation_class=mutation_class,
        capability_required=capability_required,
        allowed_intents=_ALLOWED,
        **extra,  # type: ignore[arg-type]
    )
    assert not result.allowed, f"Expected refusal for {intent_kind}"

    refusal = build_bridge_refusal_envelope(
        refusal_kind=result.refusal_kind,
        reason_code=result.reason_code,
        human_safe_message=result.message,
        trace_id=trace_id,
        frontend_session_id=frontend_sid,
        backend_session_id=backend_sid,
        parent_message_id="msg_inbound_001",
        refused_intent_kind=intent_kind,
        mutation_class=mutation_class,
        capability_required=capability_required,
    )

    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind=intent_kind,
        refusal_message_id=str(refusal.get("message_id", "")),
        inbound_message_id="msg_inbound_001",
        refusal_reason=result.message,
        mutation_class=mutation_class,
        capability_required=capability_required,
        trace_id=trace_id,
        frontend_session_id=frontend_sid,
        backend_session_id=backend_sid,
        handshake_id="hs_001",
        source="bridge_refusal_builder",
    )

    return refusal, trace_event


# ── Schema validation ────────────────────────────────────────────────────


def test_lifecycle_schema_parses() -> None:
    assert _lifecycle_schema() is not None


def test_lifecycle_schema_includes_refusal_emitted() -> None:
    schema = _lifecycle_schema()
    assert "refusal_emitted" in schema["properties"]["event"]["enum"]


def test_refusal_trace_event_validates_against_lifecycle_schema() -> None:
    _, trace_event = _refuse_and_trace("unknown_intent_xyz")
    validate(instance=trace_event, schema=_lifecycle_schema())


# ── Trace correlation: unknown intent ───────────────────────────────────


def test_unknown_intent_refusal_emits_trace_event() -> None:
    _, trace_event = _refuse_and_trace("unknown_intent_xyz")
    assert trace_event["event"] == "refusal_emitted"
    assert trace_event["refusal_kind"] == "unknown_intent_kind"
    assert trace_event["refused_intent_kind"] == "unknown_intent_xyz"


# ── Trace correlation: invalid schema_version ───────────────────────────


def test_invalid_schema_version_refusal_emits_trace_event() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        schema_version="rig.relay.future_intent.v99",
        trace_id="trace_001",
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="refresh_projection",
        refusal_message_id="msg_ref_001",
        inbound_message_id="msg_in_001",
        refusal_reason=result.message,
        trace_id="trace_001",
    )
    assert trace_event["refusal_kind"] == "invalid_schema_version"


# ── Trace correlation: missing trace_id ──────────────────────────────────


def test_missing_trace_id_refusal_emits_trace_event() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection", trace_id="", allowed_intents=_ALLOWED
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="refresh_projection",
        refusal_message_id="msg_ref_002",
        inbound_message_id="msg_in_002",
        refusal_reason=result.message,
        trace_id="",
    )
    assert trace_event["refusal_kind"] == "missing_trace_id"


# ── Trace correlation: oversized payload ─────────────────────────────────


def test_oversized_payload_refusal_emits_trace_event() -> None:
    big = {"data": "x" * (64 * 1024 + 1)}
    result = enforce_intent(
        intent_kind="big_intent",
        trace_id="trace_001",
        payload=big,
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="big_intent",
        refusal_message_id="msg_ref_003",
        inbound_message_id="msg_in_003",
        refusal_reason=result.message,
        trace_id="trace_001",
    )
    assert trace_event["refusal_kind"] == "oversized_payload"


# ── Trace correlation: raw secret ────────────────────────────────────────


def test_raw_secret_refusal_emits_trace_event_without_secret() -> None:
    result = enforce_intent(
        intent_kind="leaky_intent",
        trace_id="trace_001",
        payload={"token": "ghp_abcdef123456"},
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="leaky_intent",
        refusal_message_id="msg_ref_004",
        inbound_message_id="msg_in_004",
        refusal_reason=result.message,
        trace_id="trace_001",
    )
    assert trace_event["refusal_kind"] == "raw_secret_refused"
    raw = json.dumps(trace_event)
    assert "ghp_abcdef123456" not in raw


# ── Trace correlation: raw path ──────────────────────────────────────────


def test_raw_path_refusal_emits_trace_event_without_path() -> None:
    result = enforce_intent(
        intent_kind="path_intent",
        trace_id="trace_001",
        payload={"file": "/Users/user/secret.txt"},
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="path_intent",
        refusal_message_id="msg_ref_005",
        inbound_message_id="msg_in_005",
        refusal_reason=result.message,
        trace_id="trace_001",
    )
    assert trace_event["refusal_kind"] == "raw_path_refused"
    raw = json.dumps(trace_event)
    assert "/Users/" not in raw


# ── Trace correlation: mutation class refusals ───────────────────────────


def test_credentialed_provider_mutation_refusal_emits_trace() -> None:
    _, trace_event = _refuse_and_trace(
        "provider_intent",
        mutation_class="credentialed_provider_mutation",
        capability_required=["provider.credentials"],
    )
    assert trace_event["refusal_kind"] == "credentialed_provider_mutation_refused"
    assert trace_event["mutation_class"] == "credentialed_provider_mutation"


def test_external_network_mutation_refusal_emits_trace() -> None:
    _, trace_event = _refuse_and_trace(
        "network_intent",
        mutation_class="external_network_mutation",
        capability_required=["network.outbound"],
    )
    assert trace_event["refusal_kind"] == "external_network_mutation_refused"


def test_release_affecting_mutation_refusal_emits_trace() -> None:
    _, trace_event = _refuse_and_trace(
        "release_intent",
        mutation_class="release_affecting_mutation",
        capability_required=["release.gate"],
    )
    assert trace_event["refusal_kind"] == "release_affecting_mutation_refused"


def test_mutation_without_capability_refusal_emits_trace() -> None:
    _, trace_event = _refuse_and_trace(
        "safe_mutate", mutation_class="safe_local_mutation", capability_required=[]
    )
    assert trace_event["refusal_kind"] == "missing_capability"


# ── Message correlation ──────────────────────────────────────────────────


def test_trace_id_matches_across_inbound_refusal_trace() -> None:
    refusal, trace_event = _refuse_and_trace("unknown_xyz")
    assert trace_event["trace_id"] == refusal["trace_id"]
    assert trace_event["trace_id"] == "trace_corr_001"


def test_inbound_and_refusal_message_ids_are_distinct() -> None:
    _, trace_event = _refuse_and_trace("unknown_xyz")
    assert trace_event["inbound_message_id"] == "msg_inbound_001"
    assert trace_event["refusal_message_id"] != "msg_inbound_001"
    assert trace_event["refusal_message_id"].startswith("msg_")


def test_parent_message_id_links_refusal_to_inbound() -> None:
    refusal, trace_event = _refuse_and_trace("unknown_xyz")
    assert refusal["parent_message_id"] == "msg_inbound_001"
    assert trace_event["inbound_message_id"] == "msg_inbound_001"


def test_session_ids_preserved_in_trace_event() -> None:
    _, trace_event = _refuse_and_trace("unknown_xyz")
    assert trace_event["frontend_session_id"] == "fs_corr_001"
    assert trace_event["backend_session_id"] == "bs_corr_001"


# ── Schema validation of refusal + trace ─────────────────────────────────


def test_refusal_envelope_validates_against_schema() -> None:
    refusal, _ = _refuse_and_trace("unknown_xyz")
    validate(instance=refusal, schema=_envelope_schema())


def test_trace_event_is_content_light_and_no_raw_payload() -> None:
    result = enforce_intent(
        intent_kind="leaky_intent",
        trace_id="trace_001",
        payload={"raw_prompt": "secret stuff"},
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed
    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind="leaky_intent",
        refusal_message_id="msg_ref_cl",
        inbound_message_id="msg_in_cl",
        refusal_reason=result.message,
        trace_id="trace_001",
    )
    assert trace_event["content_light"] is True
    assert trace_event["redaction_status"] == "content_light"
    raw = json.dumps(trace_event)
    assert "raw_prompt" not in raw
    assert "raw_file_contents" not in raw
    assert "password" not in raw
    assert "secret_key" not in raw


def test_trace_event_uses_hashed_reason() -> None:
    _, trace_event = _refuse_and_trace("unknown_xyz")
    assert "refusal_reason_hash" in trace_event
    reason_hash = trace_event["refusal_reason_hash"]
    assert len(reason_hash) > 0
    raw = json.dumps(trace_event)
    assert "is not recognised" not in raw


def test_duplicate_message_refusal_does_not_produce_successful_patch() -> None:
    _, trace_event = _refuse_and_trace("unknown_xyz")
    assert trace_event["event"] == "refusal_emitted"
    assert "projection_patch" not in trace_event


# ── No side-effect contamination ─────────────────────────────────────────


def test_enforcement_does_not_write_release_gate_evidence(tmp_path: Path) -> None:
    initial = set(tmp_path.iterdir())
    _refuse_and_trace("unknown_xyz")
    final = set(tmp_path.iterdir())
    assert initial == final


def test_enforcement_does_not_write_coordination_ledger(tmp_path: Path) -> None:
    initial = set(tmp_path.iterdir())
    _refuse_and_trace("unknown_xyz")
    final = set(tmp_path.iterdir())
    assert initial == final


def test_enforcement_does_not_call_github_code() -> None:
    refusal, trace_event = _refuse_and_trace("unknown_xyz")
    raw = json.dumps({"refusal": refusal, "trace": trace_event})
    assert "github_provider" not in raw.lower()
    assert "ghp_" not in raw


# ── Frontend static protocol alignment ──────────────────────────────────


def test_lifecycle_events_include_refusal_emitted() -> None:
    schema = _lifecycle_schema()
    events = schema["properties"]["event"]["enum"]
    assert "refusal_emitted" in events
    assert len(events) == 17


def test_frontend_kind_constants_still_align() -> None:
    envelope = _envelope_schema()
    kinds = envelope["properties"]["kind"]["enum"]
    assert "error" in kinds
    assert "intent_request" in kinds


# ── All refusal kinds produce valid trace events ─────────────────────────


@pytest.mark.parametrize(
    "intent_kind, mutation_class, caps",
    [
        ("unknown_xyz", "", None),
        ("refresh_projection", "external_network_mutation", ["network.outbound"]),
        ("refresh_projection", "credentialed_provider_mutation", ["provider.creds"]),
        ("refresh_projection", "release_affecting_mutation", ["release.gate"]),
        ("safe_mutate", "safe_local_mutation", []),
        ("dangerous", "dangerous_local_mutation", ["file.mutate"]),
    ],
)
def test_all_refusal_paths_produce_valid_trace_event(
    intent_kind: str, mutation_class: str, caps: list[str] | None
) -> None:
    result = enforce_intent(
        intent_kind=intent_kind,
        trace_id="trace_001",
        mutation_class=mutation_class,
        capability_required=caps,
        allowed_intents=_ALLOWED,
    )
    assert not result.allowed

    trace_event = build_bridge_refusal_trace_event(
        refusal_kind=result.refusal_kind,
        refused_intent_kind=intent_kind,
        refusal_message_id="msg_ref_test",
        inbound_message_id="msg_in_test",
        refusal_reason=result.message,
        mutation_class=mutation_class,
        capability_required=caps,
        trace_id="trace_001",
    )
    validate(instance=trace_event, schema=_lifecycle_schema())


# ── Hash helper tests ────────────────────────────────────────────────────


def test_hash_reason_is_deterministic() -> None:
    h1 = _hash_reason("test reason")
    h2 = _hash_reason("test reason")
    assert h1 == h2


def test_hash_reason_differs_for_different_inputs() -> None:
    h1 = _hash_reason("reason A")
    h2 = _hash_reason("reason B")
    assert h1 != h2


def test_trace_event_never_contains_raw_refusal_reason() -> None:
    _, trace_event = _refuse_and_trace("unknown_xyz")
    raw = json.dumps(trace_event)
    assert "Content-light violation detected" not in raw
    assert "not recognised" not in raw
    assert "exceeds maximum" not in raw

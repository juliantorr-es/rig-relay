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
    build_bridge_refusal_envelope,
    enforce_intent,
    is_oversized_payload,
    scan_bridge_payload,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
_ENVELOPE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_envelope.v1.schema.json"


def _envelope_schema() -> dict:
    return json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Refusal envelope builder ──────────────────────────────────────────────


def test_refusal_envelope_validates_against_schema() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent 'delete_everything' is not recognised.",
        trace_id="trace_abc123",
        frontend_session_id="fs_abc123",
        backend_session_id="bs_def456",
        parent_message_id="msg_abcdef1234567890",
        refused_intent_kind="delete_everything",
        mutation_class="dangerous_local_mutation",
        capability_required=["file.write"],
        payload_hash="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    validate(instance=refusal, schema=_envelope_schema())


def test_refusal_envelope_is_content_light() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
    )
    assert refusal["redaction_status"] == "content_light"


def test_refusal_envelope_preserves_trace_id() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
        trace_id="trace_preserved_001",
    )
    assert refusal["trace_id"] == "trace_preserved_001"


def test_refusal_envelope_preserves_session_ids() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
        frontend_session_id="fs_sess_001",
        backend_session_id="bs_sess_002",
    )
    assert refusal["frontend_session_id"] == "fs_sess_001"
    assert refusal["backend_session_id"] == "bs_sess_002"


def test_refusal_envelope_links_parent_message_id() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
        parent_message_id="msg_abcdef1234567890abcdef",
    )
    assert refusal["parent_message_id"] == "msg_abcdef1234567890abcdef"


def test_refusal_envelope_no_raw_paths() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
    )
    raw = json.dumps(refusal)
    assert "/Users/" not in raw
    assert "/home/" not in raw
    assert "C:\\" not in raw


def test_refusal_envelope_no_raw_secrets() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="raw_secret_refused",
        reason_code="raw_secret_refused",
        human_safe_message="Token detected.",
    )
    raw = json.dumps(refusal)
    assert "ghp_" not in raw
    assert "github_pat_" not in raw


# ── Dispatcher enforcement: unknown / invalid ────────────────────────────


def test_unknown_intent_kind_refused() -> None:
    result = enforce_intent(
        intent_kind="nonexistent_intent",
        trace_id="trace_001",
        allowed_intents=frozenset({"refresh_projection", "get_chat_state"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "unknown_intent_kind"


def test_invalid_schema_version_refused() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        schema_version="rig.relay.future_intent.v99",
        trace_id="trace_001",
        allowed_intents=frozenset({"refresh_projection"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "invalid_schema_version"


def test_missing_trace_id_refused() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        trace_id="",
        allowed_intents=frozenset({"refresh_projection"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "missing_trace_id"


def test_allowed_intent_with_valid_data_passes() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        trace_id="trace_001",
        schema_version="rig.relay.frontend_intent.v1",
        allowed_intents=frozenset({"refresh_projection"}),
    )
    assert result.allowed


# ── Mutation class enforcement ────────────────────────────────────────────


def test_external_network_mutation_refused() -> None:
    result = enforce_intent(
        intent_kind="network_intent",
        trace_id="trace_001",
        mutation_class="external_network_mutation",
        capability_required=["network.outbound"],
        allowed_intents=frozenset({"network_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "external_network_mutation_refused"


def test_credentialed_provider_mutation_refused() -> None:
    result = enforce_intent(
        intent_kind="provider_intent",
        trace_id="trace_001",
        mutation_class="credentialed_provider_mutation",
        capability_required=["provider.credentials"],
        allowed_intents=frozenset({"provider_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "credentialed_provider_mutation_refused"


def test_release_affecting_mutation_refused() -> None:
    result = enforce_intent(
        intent_kind="release_intent",
        trace_id="trace_001",
        mutation_class="release_affecting_mutation",
        capability_required=["release.gate"],
        allowed_intents=frozenset({"release_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "release_affecting_mutation_refused"


def test_dangerous_local_mutation_refused() -> None:
    result = enforce_intent(
        intent_kind="dangerous_intent",
        trace_id="trace_001",
        mutation_class="dangerous_local_mutation",
        capability_required=["file.mutate"],
        allowed_intents=frozenset({"dangerous_intent"}),
    )
    assert not result.allowed
    assert "mutation_class_refused" in result.refusal_kind


def test_invalid_mutation_class_refused() -> None:
    result = enforce_intent(
        intent_kind="weird_intent",
        trace_id="trace_001",
        mutation_class="fantasy_class",
        capability_required=["nothing"],
        allowed_intents=frozenset({"weird_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "mutation_class_refused"


def test_mutation_without_capability_refused() -> None:
    result = enforce_intent(
        intent_kind="safe_mutate",
        trace_id="trace_001",
        mutation_class="safe_local_mutation",
        capability_required=[],
        allowed_intents=frozenset({"safe_mutate"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "missing_capability"


# ── Content-light scanner ─────────────────────────────────────────────────


def test_scanner_rejects_github_token_pattern() -> None:
    result = scan_bridge_payload({"parameters": {"token": "ghp_abc123def456"}})
    assert not result.safe
    assert result.finding_kind == "raw_secret_refused"


def test_scanner_rejects_github_pat_prefix() -> None:
    result = scan_bridge_payload({"parameters": {"pat": "github_pat_abc123"}})
    assert not result.safe
    assert result.finding_kind == "raw_secret_refused"


def test_scanner_rejects_raw_content_fields() -> None:
    result = scan_bridge_payload({"raw_prompt": "some secret prompt content"})
    assert not result.safe
    assert result.finding_kind == "unsafe_payload_refused"


def test_scanner_rejects_absolute_path() -> None:
    result = scan_bridge_payload({
        "parameters": {"file_path": "/Users/user/Documents/secret.txt"}
    })
    assert not result.safe
    assert result.finding_kind == "raw_path_refused"


def test_scanner_passes_clean_payload() -> None:
    result = scan_bridge_payload({
        "intent_kind": "refresh_projection",
        "trace_id": "trace_001",
        "mutation_class": "read_only",
        "capability_required": ["projection.read"],
    })
    assert result.safe


def test_scanner_does_not_echo_raw_token() -> None:
    result = scan_bridge_payload({"token": "ghp_secret_token_value"})
    assert not result.safe
    assert "secret_token_value" not in result.detail
    assert result.detail == "github_personal_access_token"


# ── Oversized payload enforcement ────────────────────────────────────────


def test_normal_payload_not_oversized() -> None:
    assert not is_oversized_payload({"key": "value"})


def test_oversized_payload_detected() -> None:
    big = {"data": "x" * (64 * 1024 + 1)}
    assert is_oversized_payload(big)


def test_oversized_payload_refused_by_enforcement() -> None:
    big = {"data": "x" * (64 * 1024 + 1)}
    result = enforce_intent(
        intent_kind="big_intent",
        trace_id="trace_001",
        payload=big,
        allowed_intents=frozenset({"big_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "oversized_payload"


# ── Dispatcher does not mutate backend state ────────────────────────────


def test_enforcement_is_pure_function() -> None:
    result1 = enforce_intent(
        intent_kind="test_intent",
        trace_id="trace_001",
        allowed_intents=frozenset({"test_intent"}),
    )
    result2 = enforce_intent(
        intent_kind="test_intent",
        trace_id="trace_001",
        allowed_intents=frozenset({"test_intent"}),
    )
    assert result1.allowed == result2.allowed


def test_enforcement_does_not_write_files(tmp_path: Path) -> None:
    initial_files = set(tmp_path.iterdir())
    enforce_intent(
        intent_kind="unknown",
        trace_id="trace_001",
        allowed_intents=frozenset({"known"}),
    )
    final_files = set(tmp_path.iterdir())
    assert initial_files == final_files


# ── Content-light scanner corner cases ───────────────────────────────────


def test_scanner_rejects_recursive_secrets() -> None:
    result = scan_bridge_payload({"nested": {"deep": {"access_token": "secret_value"}}})
    assert not result.safe
    assert result.finding_kind == "raw_secret_refused"


def test_scanner_rejects_path_in_list() -> None:
    result = scan_bridge_payload({
        "files": ["/Users/user/secret.txt", "normal_file.txt"]
    })
    assert not result.safe
    assert result.finding_kind == "raw_path_refused"


def test_scanner_rejects_raw_file_contents() -> None:
    result = scan_bridge_payload({"raw_file_contents": "file contents here"})
    assert not result.safe
    assert result.finding_kind == "unsafe_payload_refused"


# ── Enforcement with full payload integration ────────────────────────────


def test_content_light_violation_refused_by_enforcement() -> None:
    result = enforce_intent(
        intent_kind="bad_intent",
        trace_id="trace_001",
        payload={"raw_prompt": "secret prompt here"},
        allowed_intents=frozenset({"bad_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "unsafe_payload_refused"


def test_token_violation_refused_by_enforcement() -> None:
    result = enforce_intent(
        intent_kind="bad_intent",
        trace_id="trace_001",
        payload={"token": "ghp_abcdef123456"},
        allowed_intents=frozenset({"bad_intent"}),
    )
    assert not result.allowed
    assert result.refusal_kind == "raw_secret_refused"


def test_scanner_details_never_contain_raw_values() -> None:
    result = scan_bridge_payload({"raw_prompt": "very secret content here"})
    assert not result.safe
    assert "very secret content here" not in result.detail


# ── Read-only intents pass enforcement ────────────────────────────────────


def test_read_only_intent_with_valid_capability_passes() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        trace_id="trace_001",
        mutation_class="read_only",
        capability_required=["projection.read"],
        allowed_intents=frozenset({"refresh_projection"}),
    )
    assert result.allowed


# ── Malformed JSON / invalid input path ──────────────────────────────────


def test_enforcement_handles_empty_payload_gracefully() -> None:
    result = enforce_intent(
        intent_kind="", trace_id="trace_001", allowed_intents=frozenset({"known"})
    )
    assert not result.allowed


def test_enforcement_handles_none_capability() -> None:
    result = enforce_intent(
        intent_kind="refresh_projection",
        trace_id="trace_001",
        mutation_class="read_only",
        capability_required=None,
        allowed_intents=frozenset({"refresh_projection"}),
    )
    assert result.allowed


# ── Lifecycle event emission does not crash ──────────────────────────────


def test_refusal_envelope_kind_is_error() -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind="unknown_intent_kind",
        reason_code="unknown_intent_kind",
        human_safe_message="Intent is not recognised.",
    )
    assert refusal["kind"] == "error"


# ── Frontend static protocol alignment ───────────────────────────────────


def test_refusal_kind_constants_exist() -> None:
    from rig_relay.desktop.bridge_refusals import _REFUSAL_KINDS

    assert len(_REFUSAL_KINDS) >= 13
    assert "unknown_intent_kind" in _REFUSAL_KINDS
    assert "credentialed_provider_mutation_refused" in _REFUSAL_KINDS
    assert "raw_secret_refused" in _REFUSAL_KINDS


@pytest.mark.parametrize(
    "refusal_kind",
    [
        "unknown_intent_kind",
        "invalid_schema_version",
        "missing_trace_id",
        "duplicate_message_id",
        "oversized_payload",
        "missing_capability",
        "mutation_class_refused",
        "credentialed_provider_mutation_refused",
        "release_affecting_mutation_refused",
        "external_network_mutation_refused",
        "unsafe_payload_refused",
        "raw_secret_refused",
        "raw_path_refused",
        "internal_error",
    ],
)
def test_all_refusal_kinds_produce_valid_envelope(refusal_kind: str) -> None:
    refusal = build_bridge_refusal_envelope(
        refusal_kind=refusal_kind,
        reason_code=refusal_kind,
        human_safe_message=f"Refusal: {refusal_kind}.",
        trace_id="trace_001",
    )
    validate(instance=refusal, schema=_envelope_schema())

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
FRONTEND_DIR = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop" / "js"
)


# ── Schema existence and parseability ──────────────────────────────────────


def test_frontend_intent_schema_exists() -> None:
    path = SCHEMAS_DIR / "rig.relay.frontend_intent.v1.schema.json"
    assert path.exists(), f"Frontend intent schema missing: {path}"


def test_bridge_envelope_schema_exists() -> None:
    path = SCHEMAS_DIR / "rig.relay.bridge_envelope.v1.schema.json"
    assert path.exists(), f"Bridge envelope schema missing: {path}"


def test_backend_projection_patch_schema_exists() -> None:
    path = SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json"
    assert path.exists(), f"Backend projection patch schema missing: {path}"


def test_bridge_lifecycle_event_schema_exists() -> None:
    path = SCHEMAS_DIR / "rig.relay.bridge_lifecycle_event.v1.schema.json"
    assert path.exists(), f"Bridge lifecycle event schema missing: {path}"


# ── Frontend protocol module alignment ────────────────────────────────────


def test_frontend_protocol_envelope_js_exists() -> None:
    path = FRONTEND_DIR / "protocol" / "envelope.js"
    assert path.exists(), f"Frontend envelope module missing: {path}"
    content = path.read_text(encoding="utf-8")
    assert len(content) > 0


def test_frontend_envelope_schema_version_matches_backend() -> None:
    envelope_js = FRONTEND_DIR / "protocol" / "envelope.js"
    content = envelope_js.read_text(encoding="utf-8")
    assert "rig.relay.bridge_message.v1" in content, (
        "Frontend envelope.js must declare SCHEMA_VERSION matching backend"
    )


def test_frontend_kinds_align_with_backend() -> None:
    envelope_js = FRONTEND_DIR / "protocol" / "envelope.js"
    content = envelope_js.read_text(encoding="utf-8")
    expected_kinds = [
        "projection",
        "intent_request",
        "intent_ack",
        "intent_result",
        "lifecycle_event",
        "notification",
        "error",
        "heartbeat",
        "flow_control",
    ]
    for kind in expected_kinds:
        assert (
            kind.upper() in content or f'"{kind}"' in content or f"'{kind}'" in content
        ), f"Frontend envelope.js missing KIND for: {kind}"


def test_frontend_direction_constants_exist() -> None:
    envelope_js = FRONTEND_DIR / "protocol" / "envelope.js"
    content = envelope_js.read_text(encoding="utf-8")
    assert "FRONTEND_TO_BACKEND" in content
    assert "BACKEND_TO_FRONTEND" in content


def test_frontend_never_drop_kinds_not_empty() -> None:
    flow_control_js = FRONTEND_DIR / "protocol" / "flowControl.js"
    assert flow_control_js.exists()
    content = flow_control_js.read_text(encoding="utf-8")
    assert "NEVER_DROP" in content, "Flow control must define NEVER_DROP kinds"


def test_frontend_client_js_exists_and_has_dedup() -> None:
    path = FRONTEND_DIR / "protocol" / "client.js"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "_seenMessageIds" in content or "seenMessageIds" in content, (
        "Protocol client must track seen message IDs for dedup"
    )


# ── Frontend to backend schema-vocabulary alignment ────────────────────────


def test_mutation_class_names_consistent() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.frontend_intent.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    mutation_classes = schema["properties"]["mutation_class"]["enum"]
    expected = [
        "read_only",
        "safe_local_mutation",
        "dangerous_local_mutation",
        "external_network_mutation",
        "credentialed_provider_mutation",
        "release_affecting_mutation",
    ]
    assert sorted(mutation_classes) == sorted(expected)


def test_refusal_kinds_cover_all_known_errors() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.bridge_envelope.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    refusal_kinds = schema["properties"]["refusal"]["properties"]["refusal_kind"][
        "enum"
    ]
    expected_minimum = {
        "unknown_intent_kind",
        "invalid_schema_version",
        "unknown_kind",
        "missing_trace_id",
        "duplicate_message_id",
        "oversized_payload",
        "mutation_without_capability",
        "malformed_envelope",
        "redaction_violation",
    }
    assert expected_minimum.issubset(set(refusal_kinds)), (
        f"Missing refusal kinds: {expected_minimum - set(refusal_kinds)}"
    )


def test_lifecycle_events_cover_handshake_and_transport() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.bridge_lifecycle_event.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    events = schema["properties"]["event"]["enum"]
    assert "handshake_requested" in events
    assert "handshake_completed" in events
    assert "transport_connected" in events
    assert "transport_disconnected" in events


def test_projection_patch_sections_exist() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    sections = schema["properties"]["changed_sections"]["items"]["enum"]
    assert "current_state" in sections
    assert "queue" in sections
    assert "providers" in sections
    assert "release_gate" in sections


# ── Content-light enforcement across bridge ────────────────────────────────


def test_no_raw_paths_in_frontend_envelope_js() -> None:
    envelope_js = FRONTEND_DIR / "protocol" / "envelope.js"
    content = envelope_js.read_text(encoding="utf-8")
    assert "/Users/" not in content
    assert "C:\\" not in content


def test_no_hardcoded_secrets_in_frontend_protocol() -> None:
    for js_file in sorted((FRONTEND_DIR / "protocol").glob("*.js")):
        content = js_file.read_text(encoding="utf-8")
        for forbidden in [
            "sk-",
            "ghp_",
            "github_pat_",
            "api_key:",
            "secret:",
            "password:",
        ]:
            assert forbidden not in content, (
                f"{js_file.name} contains forbidden token pattern '{forbidden}'"
            )


def test_bridge_message_enforces_content_light() -> None:
    from rig_relay.desktop.bridge_protocol import (
        BridgeMessage,
        BridgeMessageDirection,
        BridgeMessageKind,
    )

    msg = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.HEARTBEAT,
        sequence=0,
    )
    assert msg.redaction_status == "content_light"


# ── Projection patch progressive rendering contract ───────────────────────


def test_projection_js_has_partial_patch_handler() -> None:
    proj_js = FRONTEND_DIR / "projection.js"
    content = proj_js.read_text(encoding="utf-8")
    assert "handleProjectionPatch" in content, (
        "projection.js must export handleProjectionPatch for progressive patches"
    )
    assert "COALESCE_PARTIAL_THRESHOLD" in content, (
        "projection.js must define coalescence threshold"
    )
    assert "_applyPartialSections" in content, (
        "projection.js must have partial section applier"
    )
    assert "_schedulePartial" in content, (
        "projection.js must have partial scheduling function"
    )


def test_projection_js_uses_request_animation_frame() -> None:
    proj_js = FRONTEND_DIR / "projection.js"
    content = proj_js.read_text(encoding="utf-8")
    assert "requestAnimationFrame" in content, (
        "projection.js must use requestAnimationFrame for batch scheduling"
    )


def test_projection_patch_schema_sections_align_with_patch_section_names() -> None:
    from rig_relay.desktop.projection import PATCH_SECTION_NAMES

    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    schema_sections = set(schema["properties"]["changed_sections"]["items"]["enum"])
    for section in PATCH_SECTION_NAMES:
        assert section in schema_sections, (
            f"PATCH_SECTION_NAMES member '{section}' missing from schema enum"
        )


def test_projection_patch_kinds_match_schema() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    patch_kinds = schema["properties"]["patch_kind"]["enum"]
    assert "full" in patch_kinds
    assert "partial" in patch_kinds
    assert "delta" in patch_kinds
    assert len(patch_kinds) == 3


def test_projection_patch_redaction_is_content_light() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    redaction = schema["properties"]["redaction_status"]["const"]
    assert redaction == "content_light"


def test_projection_patch_digest_format() -> None:
    schema = json.loads(
        (SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    digest_pattern = schema["properties"]["digest"]["pattern"]
    assert digest_pattern == "^sha256:[a-f0-9]{64}$"


def test_projection_js_frontend_progressive_patch_test_exists() -> None:
    path = (
        Path(__file__).resolve().parent.parent.parent
        / "tests"
        / "frontend"
        / "test_projection_patch_application.mjs"
    )
    assert path.exists(), f"Frontend progressive patch test missing: {path}"

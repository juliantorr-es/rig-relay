from __future__ import annotations

from rig_relay.profiles._resolver import resolve_profile
from rig_relay.profiles._session_receipt import build_session_resolution_receipt
from rig_relay.profiles.models import ProfileResolutionInput


def test_build_receipt_has_required_fields():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-1")
    required = [
        "schema_version",
        "receipt_id",
        "session_id",
        "provider",
        "model_id",
        "task_role",
        "selected_profile_id",
        "selected_profile_version",
        "resolution_confidence",
        "authority_evidence_posture",
        "profile_evaluation_status",
        "resolved_at",
        "receipt_digest",
    ]
    for field in required:
        assert field in receipt, f"Missing required field: {field}"


def test_receipt_content_light():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-2")
    forbidden_fields = {
        "raw_prompt",
        "raw_file_contents",
        "raw_secrets",
        "raw_model_output",
        "api_key",
        "access_token",
    }
    receipt_str = str(receipt)
    for field in forbidden_fields:
        assert field not in receipt_str.lower(), f"Forbidden field '{field}' found"


def test_receipt_digest_format_and_nonempty():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-3")
    assert receipt["receipt_digest"].startswith("sha256:")
    assert len(receipt["receipt_digest"]) > len("sha256:") + 10


def test_receipt_records_user_override():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="rig.native.governed.v1",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-4")
    assert receipt["is_user_override"] is True
    assert receipt["user_override_state"] == "active"


def test_receipt_capability_check_recorded():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-5")
    assert "required_capabilities_check" in receipt
    caps = receipt["required_capabilities_check"]
    assert isinstance(caps, dict)
    assert "requires_tool_use" in caps
    assert caps["requires_tool_use"] == "passed"


def test_receipt_for_non_override_is_none_state():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-6")
    assert receipt["user_override_state"] == "none"


def test_receipt_schema_version_correct():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    receipt = build_session_resolution_receipt(resolution, "session-7")
    assert receipt["schema_version"] == "rig.relay.session_resolution_receipt.v1"

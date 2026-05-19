from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema
import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.adversarial,
]

from rig_relay.acp._refusal_adapter import build_acp_refusal
from rig_relay.ci_evidence._producer import RunContext, _build_run_evidence
from rig_relay.integrations.github_provider._models import (
    GitHubOperationClass,
    GitHubProviderAuthState,
    GitHubProviderCapabilityDecision,
    GitHubProviderOperationRequest,
    GitHubVerdict,
)
from rig_relay.integrations.github_provider._receipts import (
    build_github_operation_receipt,
    validate_github_operation_receipt,
)
from rig_relay.protocols.mcp._refusal_adapter import evaluate_mcp_request
from rig_relay.sdk._models import RigRefusal

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEMAS = _REPO_ROOT / "docs" / "schemas"
_GOVERNANCE = _REPO_ROOT / "docs" / "json" / "governance"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS / name).read_text(encoding="utf-8"))


def _load_vocabulary() -> dict:
    return json.loads(
        (_GOVERNANCE / "refusal_vocabulary_v1.v1.json").read_text(encoding="utf-8")
    )


def _find_shared_class_for_refusal_code(refusal_code: str) -> str | None:
    vocab = _load_vocabulary()
    mappings = vocab.get("surface_mappings", [])
    for m in mappings:
        if m.get("original_code") == refusal_code:
            return cast(str, m.get("shared_class"))
    classes = vocab.get("shared_refusal_classes", [])
    code_lower = refusal_code.lower()
    for c in classes:
        if code_lower in c.get("class_id", "").replace("_", " "):
            return cast(str, c.get("class_id"))
        examples = c.get("example_original_codes", [])
        for ex in examples:
            if code_lower in ex.lower() or ex.lower() in code_lower:
                return cast(str, c.get("class_id"))
    if "unknown" in code_lower:
        return "unknown_capability"
    return None


def _assert_content_light(data: dict, json_str: str) -> None:
    forbidden = [
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "sk-",
        "api_key",
        "client_secret",
        "private_key",
        "access_token",
        "eyJ",
        "-----BEGIN",
    ]
    for fb in forbidden:
        assert fb not in json_str, (
            f"Forbidden token/secret pattern '{fb}' found in output"
        )
    assert data.get("content_light") is True, "content_light must be True"


# ═══ P0.1 bridge_to_sdk_to_mcp_refusal_trace_roundtrip ═════════════════════


_TRACE = "trace-test-v1-abc123def456"


def test_bridge_to_sdk_to_mcp_refusal_trace_roundtrip() -> None:
    bridge_context: dict[str, str] = {
        "trace_id": _TRACE,
        "parent_message_id": "msg_inbound_001",
        "frontend_session_id": "fs_test_001",
        "backend_session_id": "bs_test_001",
        "schema_version": "rig.relay.bridge_envelope.v1",
    }

    sdk_refusal = RigRefusal(
        refusal_code="mutation_refused_by_default",
        reason="Bridge received mutation intent for unknown_tool — refused by SDK policy",
        capability_id="mcp.mutation",
        trace_id=bridge_context["trace_id"],
    )
    sdk_dict = sdk_refusal.to_dict()
    sdk_json = json.dumps(sdk_dict, sort_keys=True)
    _assert_content_light(sdk_dict, sdk_json)

    mcp_result = evaluate_mcp_request(
        tool_name="rig.unknown_cross_surface_tool",
        request_dict={"arg": "test_val", "source": "cross-surface-hardening"},
        trace_id=bridge_context["trace_id"],
        session_id=bridge_context["backend_session_id"],
    )

    refusal_json = json.dumps(mcp_result, sort_keys=True)
    _assert_content_light(mcp_result, refusal_json)

    mcp_refusal_schema = _load_schema("rig.relay.mcp.refusal.v1.schema.json")
    jsonschema.validate(instance=mcp_result, schema=mcp_refusal_schema)

    assert mcp_result["schema_version"] == "rig.relay.mcp.refusal.v1"
    assert mcp_result["trace_id"] == _TRACE
    assert mcp_result["refusal_code"] in {
        "unknown_tool",
        "credentialed_tier",
        "destructive_tier",
        "mutation_tier",
    }
    assert mcp_result.get("content_light") is True

    shared_class = _find_shared_class_for_refusal_code(mcp_result["refusal_code"])
    assert shared_class is not None, (
        f"Refusal code '{mcp_result['refusal_code']}' not found in shared "
        f"refusal vocabulary surface_mappings"
    )

    assert bridge_context["trace_id"] == sdk_dict["trace_id"]
    assert bridge_context["trace_id"] == mcp_result["trace_id"]


# ═══ P0.2 sdk_to_acp_refusal_trace_roundtrip ═══════════════════════════


def test_sdk_to_acp_refusal_trace_roundtrip() -> None:
    sdk_refusal = RigRefusal(
        refusal_code="capability_missing",
        reason="SDK refused: capability not found in capability manifest",
        capability_id="acp.session.resume",
        trace_id=_TRACE,
    )
    sdk_dict = sdk_refusal.to_dict()
    sdk_json = json.dumps(sdk_dict, sort_keys=True)
    _assert_content_light(sdk_dict, sdk_json)

    acp_refusal = build_acp_refusal(
        refusal_code=sdk_refusal.refusal_code,
        reason=sdk_refusal.reason,
        method="acp.resume_session",
        trace_id=sdk_refusal.trace_id,
        session_id="bs_test_001",
    )

    acp_json = json.dumps(acp_refusal, sort_keys=True)
    _assert_content_light(acp_refusal, acp_json)

    acp_schema = _load_schema("rig.relay.acp.refusal.v1.schema.json")
    jsonschema.validate(instance=acp_refusal, schema=acp_schema)

    assert acp_refusal["schema_version"] == "rig.relay.acp.refusal.v1"
    assert acp_refusal["trace_id"] == _TRACE
    assert acp_refusal["refusal_code"] == "capability_missing"
    assert acp_refusal["method"] == "acp.resume_session"
    assert acp_refusal.get("content_light") is True

    assert sdk_dict["trace_id"] == acp_refusal["trace_id"]


# ═══ P0.3 provider_receipt_carries_trace_id_joinable ════════════════════


def test_provider_receipt_carries_trace_id_joinable() -> None:
    auth_state = GitHubProviderAuthState()
    request = GitHubProviderOperationRequest(
        operation_id="op-cross-surface-001",
        capability_id="github_repo_metadata_read",
        operation_kind="github_metadata_read",
        operation_class=GitHubOperationClass.REMOTE_READ,
        auth_state=auth_state,
        repository_hash="0" * 64,
        actor_hash="0" * 64,
    )
    decision = GitHubProviderCapabilityDecision(
        capability_id="github_repo_metadata_read",
        verdict=GitHubVerdict.ALLOWED,
        refusal_code="",
        reason="",
        requires_step_up=False,
        step_up_satisfied=True,
    )

    receipt = build_github_operation_receipt(
        request=request,
        decision=decision,
        trace_id=_TRACE,
        parent_trace_id="parent-trace-v1-999",
    )
    receipt_dict = receipt.to_dict()

    assert receipt_dict.get("trace_id") == _TRACE
    assert receipt_dict.get("parent_trace_id") == "parent-trace-v1-999"

    receipt_json = json.dumps(receipt_dict, sort_keys=True)
    _assert_content_light(receipt_dict, receipt_json)

    errors = validate_github_operation_receipt(receipt_dict)
    assert not errors, f"GitHub receipt schema validation errors: {errors}"

    assert receipt_dict["trace_id"] == _TRACE


# ═══ P0.4 ci_evidence_carries_correlation_id ═══════════════════════════


def test_ci_evidence_carries_correlation_id() -> None:
    ctx = RunContext(
        run_id="ci-cross-surface-001",
        runner_class="local",
        official_release=False,
        release_class="local_validation",
        git_branch="main",
        git_sha="0" * 40,
        git_dirty=False,
        workflow_name="cross-surface-hardening",
        workflow_ref="",
        workflow_sha="0" * 40,
        job_name="ci-hardening-job",
        event_name="",
        actor="test-agent",
        started_at="2026-05-19T00:00:00Z",
    )

    evidence_dir = Path("/tmp/rig-relay-ci-test-cross-surface-v1-1")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    run_data = _build_run_evidence(
        ctx, evidence_dir, trace_id=_TRACE, correlation_id="corr-cross-surface-v1-1-001"
    )

    assert run_data.get("trace_id") == _TRACE
    assert run_data.get("correlation_id") == "corr-cross-surface-v1-1-001"
    assert run_data["run_id"] == "ci-cross-surface-001"

    run_json = json.dumps(run_data, sort_keys=True)
    forbidden = [
        "ghp_",
        "sk-",
        "api_key",
        "client_secret",
        "private_key",
        "access_token",
    ]
    for fb in forbidden:
        assert fb not in run_json, f"Forbidden pattern '{fb}' found in CI run evidence"


# ═══ Content-light enforcement across all roundtrip paths ══════════════


def test_cross_surface_roundtrip_no_raw_payload_echoed() -> None:
    """No test artifact contains raw tokens, secrets, paths, or prompts."""
    payload_strings = [
        "/etc/passwd",
        "C:\\Windows\\System32",
        "SELECT * FROM",
        "eval(",
        "${",
        "`id`",
        "<script>",
    ]
    mcp_result = evaluate_mcp_request(
        "rig.unknown_cross_surface_tool",
        {"arg": "test_val"},
        _TRACE,
        "session-test-001",
    )
    mcp_json = json.dumps(mcp_result, sort_keys=True)
    for ps in payload_strings:
        assert ps not in mcp_json, (
            f"Potentially dangerous payload pattern '{ps}' found in MCP refusal"
        )

    acp_refusal = build_acp_refusal(
        refusal_code="test_refusal",
        reason="Test reason for content-light sweep",
        method="test.method",
        trace_id=_TRACE,
    )
    acp_json = json.dumps(acp_refusal, sort_keys=True)
    for ps in payload_strings:
        assert ps not in acp_json, (
            f"Potentially dangerous payload pattern '{ps}' found in ACP refusal"
        )

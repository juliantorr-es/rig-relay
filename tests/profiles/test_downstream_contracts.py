from __future__ import annotations

import json

from rig_relay.profiles._downstream_contracts import (
    ContextCapsuleBindingReceipt,
    ContextCapsuleBindingRequest,
    HarnessProfileStatusProjection,
    ProfileEvaluationObservation,
    ProfileSelectionMetrics,
    RuntimeProfileCapabilityObservation,
    WorkspaceProfileAssignmentReceipt,
    WorkspaceProfileAssignmentRequest,
    build_y0_projection,
    build_y1_assignment_request,
    build_y2_binding_request,
    build_y4_observation,
)
from rig_relay.profiles._resolver import resolve_profile
from rig_relay.profiles.models import ProfileResolutionInput


def _resolve_rig_native_openai():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        prefer_profile_id="rig.native.governed.v1",
        model_capabilities={"supports_tools": True},
    )
    return resolve_profile(inp)


def test_harnessprofilestatusprojection_has_all_required_fields_with_defaults():
    proj = HarnessProfileStatusProjection()
    assert proj.schema_version
    assert proj.generated_at
    assert proj.selected_profile_id == ""
    assert proj.selected_profile_display_name == ""
    assert proj.evidence_health == "unknown"
    assert isinstance(proj.warnings, list)


def test_workspaceprofileassignmentrequest_serializes_to_valid_json():
    req = WorkspaceProfileAssignmentRequest(
        request_id="req-test",
        workspace_id_ref="ws-test",
        agent_role="implementation",
        provider="openai",
        model_id="gpt-4o",
        selected_profile_digest="sha256:abc",
    )
    js = req.model_dump_json()
    parsed = json.loads(js)
    assert parsed["request_id"] == "req-test"
    assert parsed["provider"] == "openai"


def test_contextcapsulebindingrequest_fields_are_correct():
    req = ContextCapsuleBindingRequest(
        request_id="cb-req-1",
        context_capsule_digest="sha256:abc",
        required_envelope_strategy="rig_governed",
    )
    assert req.request_id == "cb-req-1"
    assert req.context_capsule_digest == "sha256:abc"
    assert req.stale_handling == "warn"
    assert req.required_envelope_strategy == "rig_governed"


def test_runtimeprofilecapabilityobservation_fields_are_correct():
    obs = RuntimeProfileCapabilityObservation(
        observation_id="obs-1",
        runtime_provider="openai",
        runtime_model="gpt-4o",
        selected_profile_id="rig.native.governed.v1",
        observed_outcome="success",
        evidence_health="healthy",
    )
    assert obs.observation_id == "obs-1"
    assert obs.runtime_provider == "openai"
    assert obs.runtime_model == "gpt-4o"
    assert obs.evidence_health == "healthy"


def test_profileevaluationobservation_has_correct_check_count_defaults():
    obs = ProfileEvaluationObservation(
        observation_id="obs-1",
        profile_id="rig.native.governed.v1",
        provider="openai",
        model_id="gpt-4o",
        task_role="implementation",
    )
    assert obs.evaluation_checks_passed == 0
    assert obs.evaluation_checks_total == 5


def test_profileselectionmetrics_initializes_with_zero_counts():
    metrics = ProfileSelectionMetrics()
    assert metrics.total_selections == 0
    assert metrics.experimental_profile_usage == 0
    assert metrics.admitted_profile_usage == 0
    assert metrics.selections_by_outcome == {}


def test_build_y0_projection_produces_valid_harnessprofilestatusprojection():
    resolution = _resolve_rig_native_openai()
    projection = build_y0_projection(resolution)
    assert isinstance(projection, HarnessProfileStatusProjection)
    assert projection.selected_profile_id == "rig.native.governed.v1"
    assert projection.provider == "openai"
    assert projection.model_id == "gpt-4o"
    assert projection.evidence_health in {
        "healthy",
        "missing",
        "degraded",
        "conflicting",
        "unknown",
    }


def test_build_y1_assignment_request_produces_valid_request():
    resolution = _resolve_rig_native_openai()
    req = build_y1_assignment_request("ws-test", resolution, "sha256:envelope")
    assert isinstance(req, WorkspaceProfileAssignmentRequest)
    assert req.workspace_id_ref == "ws-test"
    assert req.session_envelope_digest == "sha256:envelope"
    assert req.request_id


def test_build_y2_binding_request_produces_valid_request():
    req = build_y2_binding_request("sha256:capsule", "rig_governed")
    assert isinstance(req, ContextCapsuleBindingRequest)
    assert req.context_capsule_digest == "sha256:capsule"
    assert req.required_envelope_strategy == "rig_governed"
    assert req.request_id


def test_build_y4_observation_produces_valid_observation():
    obs = build_y4_observation("rig.native.governed.v1", "openai", "gpt-4o", "success")
    assert isinstance(obs, RuntimeProfileCapabilityObservation)
    assert obs.runtime_provider == "openai"
    assert obs.runtime_model == "gpt-4o"
    assert obs.observed_outcome == "success"
    assert obs.evidence_health == "healthy"
    assert obs.observation_id


def test_all_eight_models_serialize_and_deserialize_correctly():
    models: list[object] = [
        HarnessProfileStatusProjection(selected_profile_id="rig.native.governed.v1"),
        WorkspaceProfileAssignmentRequest(
            request_id="x",
            workspace_id_ref="x",
            agent_role="x",
            provider="x",
            model_id="x",
            selected_profile_digest="sha256:x",
        ),
        WorkspaceProfileAssignmentReceipt(
            receipt_id="x", request_id="x", workspace_id_ref="x"
        ),
        ContextCapsuleBindingRequest(request_id="x", context_capsule_digest="sha256:x"),
        ContextCapsuleBindingReceipt(receipt_id="x", request_id="x"),
        RuntimeProfileCapabilityObservation(
            observation_id="x",
            runtime_provider="x",
            runtime_model="x",
            selected_profile_id="x",
            observed_outcome="x",
        ),
        ProfileEvaluationObservation(
            observation_id="x",
            profile_id="x",
            provider="x",
            model_id="x",
            task_role="x",
        ),
        ProfileSelectionMetrics(),
    ]

    for model in models:
        js = model.model_dump_json()
        parsed = json.loads(js)
        assert parsed is not None

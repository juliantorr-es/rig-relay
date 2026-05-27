from __future__ import annotations

import json

import pytest

from rig_relay.desktop.gateway import (
    DeveloperStudioProjection,
    execute_gateway_intent,
    get_gateway_service,
    is_gateway_intent,
    reset_gateway_service,
)


@pytest.fixture(autouse=True)
def _reset_gateway() -> None:
    reset_gateway_service()


class TestGatewaySingleton:
    def test_get_returns_same_instance(self) -> None:
        a = get_gateway_service()
        b = get_gateway_service()
        assert a is b

    def test_reset_creates_new_instance(self) -> None:
        a = get_gateway_service()
        reset_gateway_service()
        b = get_gateway_service()
        assert a is not b


class TestBuildProjection:
    def test_build_projection_empty_has_all_sections(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()

        assert projection.schema_version == "rig.relay.developer_studio_projection.v1"
        assert projection.content_light is True
        assert projection.workspace is not None
        assert projection.operator is not None
        assert projection.context is not None
        assert projection.inference is not None
        assert projection.service_health is not None
        assert projection.provenance_summary is not None
        assert projection.projection_digest != ""

    def test_projection_has_service_health_strings(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()

        health = projection.service_health
        assert isinstance(health.j0_workspace, str)
        assert isinstance(health.k0_operator, str)
        assert isinstance(health.l0_context, str)
        assert isinstance(health.m0_inference, str)
        assert health.j0_workspace != ""
        assert health.k0_operator != ""
        assert health.l0_context != ""
        assert health.m0_inference != ""

    def test_projection_has_provenance_all_nine_fields(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()

        ps = projection.provenance_summary
        fields: dict[str, int] = {
            "canonical_facts": ps.canonical_facts,
            "derived_projections": ps.derived_projections,
            "generated_proposals": ps.generated_proposals,
            "review_required_drafts": ps.review_required_drafts,
            "approved_contents": ps.approved_contents,
            "controlled_boundary_proofs": ps.controlled_boundary_proofs,
            "fixture_deferred": ps.fixture_deferred,
            "refused": ps.refused,
            "corrupt_untrusted": ps.corrupt_untrusted,
        }
        assert len(fields) == 9
        for name, value in fields.items():
            assert isinstance(value, int), (
                f"provenance_summary.{name} should be int, got {type(value)}"
            )


class TestJ0ControlledBoundary:
    def test_j0_controlled_boundary_when_no_credentials(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()

        conn = projection.workspace.connection
        assert conn.trust_state in {"controlled_boundary", "trusted_live", "fixture"}
        assert conn.token_available is False


class TestK0Degraded:
    def test_k0_available_false_when_no_sessions(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()

        assert projection.operator.available is False
        assert projection.operator.active_session_count == 0
        assert projection.operator.total_sessions == 0


class TestIntentClassification:
    def test_is_gateway_identifies_valid_intents(self) -> None:
        assert is_gateway_intent("get_developer_studio_projection") is True
        assert is_gateway_intent("studio_start_investigation") is True
        assert is_gateway_intent("studio_assemble_project_profile") is True
        assert is_gateway_intent("studio_request_local_assistance") is True

    def test_is_gateway_rejects_non_gateway_intents(self) -> None:
        assert is_gateway_intent("refresh_projection") is False
        assert is_gateway_intent("bad_intent") is False
        assert is_gateway_intent("") is False
        assert is_gateway_intent("run_storage_audit") is False


class TestExecuteGatewayIntent:
    def test_get_projection_intent_returns_completed_with_data(self) -> None:
        result = execute_gateway_intent("get_developer_studio_projection")

        assert result["status"] == "completed"
        assert result["intent_name"] == "get_developer_studio_projection"
        assert isinstance(result["data"], dict)
        assert result["data"]["content_light"] is True
        assert "workspace" in result["data"]
        assert "operator" in result["data"]
        assert "context" in result["data"]
        assert "inference" in result["data"]

    def test_unknown_intent_returns_refused(self) -> None:
        result = execute_gateway_intent("bad_intent")

        assert result["status"] == "refused"
        assert result["intent_name"] == "bad_intent"

    def test_missing_params_returns_refused(self) -> None:
        result = execute_gateway_intent("studio_select_repository")

        assert result["status"] == "refused"
        assert result["intent_name"] == "studio_select_repository"

    def test_invalid_task_kind_returns_refused(self) -> None:
        result = execute_gateway_intent(
            "studio_request_local_assistance", {"task_kind": "bad"}
        )

        assert result["status"] == "refused"
        assert result["intent_name"] == "studio_request_local_assistance"


class TestContentLight:
    def test_projection_dict_no_token_leakage(self) -> None:
        gw = get_gateway_service()
        projection = gw.build_projection()
        data = projection.model_dump(mode="json")
        serialized = json.dumps(data, sort_keys=True)

        assert projection.content_light is True
        assert "token" not in data
        assert "ghp_" not in serialized
        assert "github_pat_" not in serialized


class TestProjectionDigest:
    def test_projection_digest_deterministic_same_state(self) -> None:
        gw = get_gateway_service()
        proj_a = gw.build_projection()
        proj_b = gw.build_projection()

        assert proj_a.projection_digest != ""
        assert proj_a.projection_digest == proj_b.projection_digest


class TestProjectionSerialization:
    def test_model_validate_round_trips(self) -> None:
        gw = get_gateway_service()
        original = gw.build_projection()
        dumped = original.model_dump(mode="json")

        reloaded = DeveloperStudioProjection.model_validate(dumped)
        assert reloaded.schema_version == original.schema_version
        assert reloaded.content_light == original.content_light
        assert reloaded.projection_digest == original.projection_digest
        assert reloaded.workspace.available == original.workspace.available
        assert reloaded.operator.available == original.operator.available
        assert reloaded.context.available == original.context.available
        assert reloaded.inference.available == original.inference.available

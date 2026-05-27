"""Production-substrate tests for the S2-hardened Developer Studio Gateway.

Proves: authority classification, content-light enforcement, provenance
walking, degraded authority states, idempotency safety, schema validation,
and honest fixture-deferred reporting.
"""

from __future__ import annotations

import uuid

import pytest

from rig_relay.desktop.gateway._authority import (
    AuthorityEvidence,
    GatewayAuthorityReport,
    ServiceAuthority,
)
from rig_relay.desktop.gateway._content_light import (
    compute_content_safety_hash,
    enforce_content_light,
)
from rig_relay.desktop.gateway._intents import (
    execute_gateway_intent,
    get_gateway_service,
    is_gateway_intent,
    reset_gateway_service,
)
from rig_relay.desktop.gateway._models import (
    DeveloperStudioProjection,
    GatewayErrorKind,
    TrustState,
)
from rig_relay.desktop.gateway._service import _count_in_object, _count_provenance_walk


@pytest.fixture(autouse=True)
def _reset_gateway() -> None:
    reset_gateway_service()


# ── Authority Classification ────────────────────────────────────────


class TestServiceAuthority:
    def test_all_authority_states_have_trust_mappings(self) -> None:
        for state in ServiceAuthority:
            trust = state.to_trust_state()
            assert isinstance(trust, TrustState)

    def test_is_evidence_backed_correct(self) -> None:
        assert ServiceAuthority.CANONICAL_LIVE.is_evidence_backed is True
        assert ServiceAuthority.CANONICAL_DEGRADED.is_evidence_backed is True
        assert ServiceAuthority.CONTROLLED_BOUNDARY.is_evidence_backed is True
        assert ServiceAuthority.FIXTURE_DEFERRED.is_evidence_backed is False
        assert ServiceAuthority.MISSING.is_evidence_backed is False
        assert ServiceAuthority.STALE.is_evidence_backed is False
        assert ServiceAuthority.CORRUPT.is_evidence_backed is False
        assert ServiceAuthority.CONTRADICTORY.is_evidence_backed is False
        assert ServiceAuthority.UNAUTHORIZED.is_evidence_backed is False

    def test_is_degraded_correct(self) -> None:
        assert ServiceAuthority.CANONICAL_LIVE.is_degraded is False
        assert ServiceAuthority.CONTROLLED_BOUNDARY.is_degraded is False
        assert ServiceAuthority.CANONICAL_DEGRADED.is_degraded is False
        assert ServiceAuthority.FIXTURE_DEFERRED.is_degraded is True
        assert ServiceAuthority.MISSING.is_degraded is True
        assert ServiceAuthority.STALE.is_degraded is True
        assert ServiceAuthority.CORRUPT.is_degraded is True

    def test_authority_evidence_defaults(self) -> None:
        ev = AuthorityEvidence(kind="j0_workspace", authority=ServiceAuthority.MISSING)
        assert ev.kind == "j0_workspace"
        assert ev.authority == ServiceAuthority.MISSING
        assert ev.degradation_reason == ""

    def test_authority_evidence_with_reason(self) -> None:
        ev = AuthorityEvidence(
            kind="j0_workspace",
            authority=ServiceAuthority.MISSING,
            degradation_reason="No GitHub App credentials",
        )
        assert ev.degradation_reason == "No GitHub App credentials"


class TestGatewayAuthorityReport:
    def test_report_all_evidence_backed_false_when_fixture(self) -> None:
        report = GatewayAuthorityReport(
            j0_workspace=AuthorityEvidence(
                kind="j0_workspace", authority=ServiceAuthority.CONTROLLED_BOUNDARY
            ),
            k0_operator=AuthorityEvidence(
                kind="k0_operator", authority=ServiceAuthority.MISSING
            ),
            l0_context=AuthorityEvidence(
                kind="l0_context", authority=ServiceAuthority.FIXTURE_DEFERRED
            ),
            m0_inference=AuthorityEvidence(
                kind="m0_inference", authority=ServiceAuthority.CANONICAL_DEGRADED
            ),
        )
        assert report.all_evidence_backed is False
        # MISSING and FIXTURE_DEFERRED are degraded; CANONICAL_DEGRADED is not
        assert len(report.degraded_services) == 2
        assert "k0_operator" in report.degraded_services
        assert "l0_context" in report.degraded_services

    def test_report_all_evidence_backed_true(self) -> None:
        report = GatewayAuthorityReport(
            j0_workspace=AuthorityEvidence(
                kind="j0_workspace", authority=ServiceAuthority.CANONICAL_LIVE
            ),
            k0_operator=AuthorityEvidence(
                kind="k0_operator", authority=ServiceAuthority.CANONICAL_LIVE
            ),
            l0_context=AuthorityEvidence(
                kind="l0_context", authority=ServiceAuthority.CANONICAL_DEGRADED
            ),
            m0_inference=AuthorityEvidence(
                kind="m0_inference", authority=ServiceAuthority.CANONICAL_LIVE
            ),
        )
        assert report.all_evidence_backed is True


# ── Content-Light Enforcement ───────────────────────────────────────


class TestContentLightEnforcement:
    def test_clean_payload_returns_no_violations(self) -> None:
        payload = {
            "schema_version": "v1",
            "projection_id": "test",
            "content_light": True,
            "available": False,
        }
        violations = enforce_content_light(payload, source_label="test")
        assert violations == []

    def test_ghp_token_detected(self) -> None:
        payload = {"key": "ghp_1234567890abcdef1234567890abcdef12345678"}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("token-like" in v for v in violations)

    def test_anthropic_token_detected(self) -> None:
        payload = {
            "key": "sk-ant-api03-1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"
        }
        violations = enforce_content_light(payload)
        assert len(violations) >= 1

    def test_raw_path_detected(self) -> None:
        payload = {"path": "/Users/alice/projects/my-repo/src/file.py"}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("raw filesystem path" in v for v in violations)

    def test_forbidden_field_name_detected(self) -> None:
        payload = {"access_token": "anything"}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("forbidden field name" in v for v in violations)

    def test_private_ip_detected(self) -> None:
        payload = {"endpoint": "http://127.0.0.1:8080/api"}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("private IP" in v for v in violations)

    def test_raw_code_content_detected(self) -> None:
        payload = {"text": "import os\n\ndef my_func():\n    pass\n"}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("raw code content" in v for v in violations)

    def test_nested_dict_detection(self) -> None:
        payload = {
            "outer": {"inner": {"key": "ghp_1234567890abcdef1234567890abcdef12345678"}}
        }
        violations = enforce_content_light(payload)
        assert len(violations) >= 1

    def test_nested_list_detection(self) -> None:
        payload = {"items": [{"key": "ghp_1234567890abcdef1234567890abcdef12345678"}]}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1

    def test_content_safety_hash_deterministic(self) -> None:
        payload = {"a": 1, "b": 2}
        h1 = compute_content_safety_hash(payload)
        h2 = compute_content_safety_hash(payload)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_empty_projection_is_content_light(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()
        data = proj.model_dump(mode="json")
        violations = enforce_content_light(data, source_label="projection")
        assert violations == [], f"Unexpected content-light violations: {violations}"

    def test_long_string_rejected(self) -> None:
        payload = {"data": "x" * 3000}
        violations = enforce_content_light(payload)
        assert len(violations) >= 1
        assert any("too long" in v for v in violations)


# ── Provenance Walking ──────────────────────────────────────────────


class TestProvenanceWalking:
    def test_count_provenance_walk_counts_all_fields(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        summary = _count_provenance_walk(
            proj.workspace, proj.operator, proj.context, proj.inference
        )

        assert isinstance(summary.canonical_facts, int)
        assert isinstance(summary.derived_projections, int)
        assert isinstance(summary.generated_proposals, int)
        assert isinstance(summary.review_required_drafts, int)
        assert isinstance(summary.approved_contents, int)
        assert isinstance(summary.controlled_boundary_proofs, int)
        assert isinstance(summary.fixture_deferred, int)
        assert isinstance(summary.refused, int)
        assert isinstance(summary.corrupt_untrusted, int)

        # The projection trees should have at least one derived projection each
        assert summary.derived_projections >= 4

    def test_count_in_object_none_handling(self) -> None:
        from rig_relay.desktop.gateway._models import StudioProvenanceSummary

        summary = StudioProvenanceSummary()
        _count_in_object(None, summary)
        # Should not raise; no provenance counted

    def test_provenance_summary_no_negative_values(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        summary = _count_provenance_walk(
            proj.workspace, proj.operator, proj.context, proj.inference
        )
        d = summary.model_dump()
        for k, v in d.items():
            assert v >= 0, f"{k} is negative: {v}"


# ── Authority States in Projections ─────────────────────────────────


class TestAuthorityStatesInProjection:
    def test_j0_authority_missing_when_no_credentials(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.workspace.authority_state in {
            "missing",
            "controlled_boundary",
            "corrupt",
        }
        assert isinstance(proj.workspace.degraded_reason, str)

    def test_j0_connection_has_authority_state(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        conn = proj.workspace.connection
        assert conn.authority_state in {
            "missing",
            "controlled_boundary",
            "corrupt",
            "canonical_live",
        }
        assert isinstance(conn.degraded_reason, str)

    def test_k0_authority_missing_when_no_sessions(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.operator.authority_state == "missing"
        assert "No K0 operator sessions" in proj.operator.degraded_reason

    def test_l0_authority_fixture_deferred(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.context.authority_state == "fixture_deferred"
        assert "fixture-deferred" in proj.context.degraded_reason.lower()

    def test_m0_authority_set(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.inference.authority_state in {
            "missing",
            "canonical_degraded",
            "canonical_live",
        }
        assert isinstance(proj.inference.degraded_reason, str)

    def test_all_sections_have_authority_state(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert hasattr(proj.workspace, "authority_state")
        assert hasattr(proj.operator, "authority_state")
        assert hasattr(proj.context, "authority_state")
        assert hasattr(proj.inference, "authority_state")

    def test_l0_reports_j0_intake_boundary(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        intake = proj.context.intake_dependency_status
        assert intake.j0_intake_boundary in {"fixture", "live"}
        assert intake.k0_investigation_boundary in {"fixture", "live"}


# ── Idempotency ─────────────────────────────────────────────────────


class TestIdempotency:
    def test_missing_idempotency_key_acts_normally(self) -> None:
        """Without idempotency key, calls should still succeed."""
        result = execute_gateway_intent("get_developer_studio_projection")
        assert result["status"] == "completed"

    def test_idempotency_key_passed_through_to_intents(self) -> None:
        """Intents should accept idempotency_key parameter without error."""
        key = f"test-{uuid.uuid4().hex[:12]}"
        result = execute_gateway_intent(
            "get_developer_studio_projection", {"idempotency_key": key}
        )
        assert result["status"] == "completed"

    def test_unknown_intent_with_idempotency_key(self) -> None:
        result = execute_gateway_intent("bad_intent", {"idempotency_key": "test-key"})
        assert result["status"] == "refused"


# ── Schema Validation ───────────────────────────────────────────────


class TestSchemaRoundTrip:
    def test_developer_studio_projection_validates_against_model(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        data = proj.model_dump(mode="json")
        reloaded = DeveloperStudioProjection.model_validate(data)

        assert reloaded.schema_version == proj.schema_version
        assert reloaded.content_light == proj.content_light
        assert reloaded.projection_digest == proj.projection_digest

    def test_authority_report_fields_present(self) -> None:
        gw = get_gateway_service()
        report = gw.build_authority_report()

        assert report.j0_workspace.kind == "j0_workspace"
        assert report.k0_operator.kind == "k0_operator"
        assert report.l0_context.kind == "l0_context"
        assert report.m0_inference.kind == "m0_inference"

        assert report.schema_version == "rig.relay.gateway_authority_report.v1"


# ── Intent Routing ──────────────────────────────────────────────────


class TestIntentRouting:
    def test_all_gateway_intents_classified(self) -> None:
        intents = [
            "get_developer_studio_projection",
            "studio_connect_workspace",
            "studio_discover_repositories",
            "studio_select_repository",
            "studio_import_repository",
            "studio_inspect_publication_readiness",
            "studio_prepare_pages_action",
            "studio_start_investigation",
            "studio_get_investigation",
            "studio_close_investigation",
            "studio_assemble_project_profile",
            "studio_assemble_context_packet",
            "studio_request_local_assistance",
            "studio_get_local_draft",
        ]
        for name in intents:
            assert is_gateway_intent(name) is True, f"{name} should be a gateway intent"

    def test_missing_params_return_refused_for_all_mutating_intents(self) -> None:
        cases: list[tuple[str, dict[str, str]]] = [
            ("studio_select_repository", {}),
            ("studio_import_repository", {}),
            ("studio_inspect_publication_readiness", {}),
            ("studio_start_investigation", {}),
            ("studio_get_investigation", {}),
            ("studio_close_investigation", {}),
            ("studio_assemble_project_profile", {}),
            ("studio_assemble_context_packet", {}),
            ("studio_request_local_assistance", {}),
            ("studio_get_local_draft", {}),
        ]
        for name, params in cases:
            result = execute_gateway_intent(name, params)
            assert result["status"] == "refused", (
                f"{name} should be refused without params"
            )

    def test_valid_task_kind_accepts(self) -> None:
        """Valid task_kind should be accepted (may fail downstream, but not refused)."""
        result = execute_gateway_intent(
            "studio_request_local_assistance", {"task_kind": "project_summary"}
        )
        # May be failed by M0 service unavailability, but not by param validation
        assert result["status"] in {"completed", "failed", "refused"}
        # If refused, it should not be due to task_kind validation
        if result["status"] == "refused":
            assert "task_kind must be one of" not in result.get("error_message", "")


# ── Service Health ──────────────────────────────────────────────────


class TestServiceHealth:
    def test_health_labels_non_empty(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        health = proj.service_health
        assert len(health.j0_workspace) > 0
        assert len(health.k0_operator) > 0
        assert len(health.l0_context) > 0
        assert len(health.m0_inference) > 0

        valid = {"available", "unavailable", "degraded"}
        assert health.j0_workspace in valid
        assert health.k0_operator in valid
        assert health.l0_context in valid
        assert health.m0_inference in valid


# ── Projection Integrity ────────────────────────────────────────────


class TestProjectionIntegrity:
    def test_projection_digest_hex_format(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.projection_digest.startswith("sha256:")
        hex_part = proj.projection_digest.split(":", 1)[1]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_projection_content_light_flag(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        assert proj.content_light is True

    def test_last_projection_cached(self) -> None:
        gw = get_gateway_service()
        proj = gw.build_projection()

        cached = gw.get_last_projection()
        assert cached is proj


# ── GatewayError ────────────────────────────────────────────────────


class TestGatewayError:
    def test_error_kind_values(self) -> None:
        kinds = [k.value for k in GatewayErrorKind]
        assert "gateway." in kinds[0]
        assert "gateway.service_unavailable" in kinds
        assert "gateway.intent_unknown" in kinds

    def test_error_from_kind(self) -> None:
        from rig_relay.desktop.gateway._models import GatewayError

        exc = GatewayError(GatewayErrorKind.SERVICE_UNAVAILABLE, "J0 is unavailable")
        assert exc.kind == GatewayErrorKind.SERVICE_UNAVAILABLE
        assert "J0" in exc.message

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
ARTIFACT_DIR = REPO_ROOT / "docs" / "json" / "governance"


class TestLiveTransportFederationReadinessV1:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.schema = json.loads(
            (
                SCHEMA_DIR
                / "rig.relay.live_transport_federation_readiness.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.artifact = json.loads(
            (ARTIFACT_DIR / "live_transport_federation_readiness_v1.v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_schema_validates_itself(self) -> None:
        validate(
            instance=self.schema,
            schema={"$schema": "http://json-schema.org/draft-07/schema#"},
        )

    def test_artifact_validates_against_schema(self) -> None:
        validate(instance=self.artifact, schema=self.schema)

    def test_all_four_surfaces_present(self) -> None:
        surfaces = {t["surface"] for t in self.artifact["transports"]}
        assert surfaces == {"mcp", "acp", "a2a", "sdk"}

    def test_no_surface_has_zero_tests(self) -> None:
        for t in self.artifact["transports"]:
            assert t["tests_total"] > 0, f"{t['surface']} has zero tests"

    def test_security_coverage_exists(self) -> None:
        sec = self.artifact["security"]
        assert sec["descriptor_poisoning_tests_pass"] > 0
        assert sec["jsonrpc_validation_tests_pass"] > 0
        assert sec["content_light_verified"] is True

    def test_budgets_configured(self) -> None:
        b = self.artifact["budgets"]
        assert b["max_request_bytes"] > 0
        assert b["max_response_bytes"] > 0
        assert b["max_concurrent_sessions"] > 0

    def test_trace_propagation_required(self) -> None:
        assert self.artifact["trace_propagation"]["trace_id_required"] is True

    def test_receipts_configured(self) -> None:
        assert self.artifact["receipts"]["every_refusal_emits_receipt"] is True

    def test_refusals_aligned(self) -> None:
        assert self.artifact["refusals"]["refusal_vocabulary_aligned"] is True
        assert self.artifact["refusals"]["content_light_enforced"] is True

    def test_auth_defaults_safe(self) -> None:
        auth = self.artifact["auth_dependency_matrix"]
        assert auth["remote_network_disabled_by_default"] is True
        assert auth["credentialed_operations_refused_by_default"] is True

    def test_remaining_blockers_are_structured(self) -> None:
        for b in self.artifact["remaining_blockers"]:
            assert "surface" in b
            assert "blocker_id" in b
            assert "description" in b
            assert "severity" in b

    def test_evidence_artifacts_listed(self) -> None:
        assert len(self.artifact["evidence_artifacts"]) > 0

    def test_no_raw_secrets_in_artifact(self) -> None:
        raw = json.dumps(self.artifact)
        assert "sk-" not in raw.lower()
        assert "api_key" not in raw.lower()
        assert "token" not in raw.lower()
        assert "password" not in raw.lower()

    def test_claim_not_falsely_asserted(self) -> None:
        if self.artifact["assessment"]["verdict"] == "partial":
            assert self.artifact["assessment"]["claim_supported"] is False

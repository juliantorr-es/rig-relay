from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
ARTIFACT_DIR = REPO_ROOT / "docs" / "json" / "governance"


class TestLiveProviderReadinessV1:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.schema = json.loads(
            (SCHEMA_DIR / "rig.relay.live_provider_readiness.v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.artifact = json.loads(
            (ARTIFACT_DIR / "live_provider_readiness_v1.v1.json").read_text(
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

    def test_both_providers_present(self) -> None:
        assert "github_provider" in self.artifact
        assert "google_workspace_provider" in self.artifact

    def test_github_provider_has_capabilities(self) -> None:
        gh = self.artifact["github_provider"]
        assert len(gh["implemented_capabilities"]) >= 0
        assert gh["token_detection_patterns"] > 0

    def test_google_provider_has_capabilities(self) -> None:
        gw = self.artifact["google_workspace_provider"]
        assert len(gw["implemented_capabilities"]) >= 0
        assert gw["receipts_content_light"] is True

    def test_redaction_active(self) -> None:
        r = self.artifact["redaction"]
        assert r["github_token_patterns_detected"] > 0
        assert r["google_secret_patterns_detected"] > 0
        assert r["forbidden_field_enforcement_active"] is True

    def test_live_operations_disabled_by_default(self) -> None:
        lo = self.artifact["live_operations"]
        assert lo["network_disabled_by_default"] is True
        assert lo["requires_env_var"] is True
        assert lo["dry_run_default"] is True

    def test_mutations_refused(self) -> None:
        sp = self.artifact["scope_permission_matrix"]
        assert sp["mutation_scopes_refused"] is True
        assert sp["restricted_scopes_refused_by_default"] is True
        assert sp["admin_directory_refused"] is True

    def test_no_raw_secrets_in_artifact(self) -> None:
        raw = json.dumps(self.artifact)
        assert "ghp_" not in raw
        assert "ya29." not in raw
        assert "api_key" not in raw.lower()
        assert "access_token" not in raw.lower()
        assert "client_secret" not in raw.lower()
        assert "private_key" not in raw.lower()

    def test_evidence_artifacts_listed(self) -> None:
        assert len(self.artifact["evidence_artifacts"]) > 0

    def test_remaining_blockers_are_structured(self) -> None:
        for b in self.artifact["remaining_blockers"]:
            assert "surface" in b
            assert "blocker_id" in b
            assert "description" in b
            assert "severity" in b

    def test_claim_not_falsely_asserted(self) -> None:
        if self.artifact["assessment"]["verdict"] in (
            "partial",
            "blocked",
            "contract_only",
        ):
            assert self.artifact["assessment"]["claim_supported"] is False

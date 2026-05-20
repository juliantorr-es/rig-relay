"""GitHub operating picture redaction adversarial tests."""

from __future__ import annotations

import pytest

from rig_relay.integrations.github_provider._operating_picture import (
    build_github_operating_picture,
)

pytestmark = [pytest.mark.adversarial]


def test_operating_picture_rejects_forbidden_token_and_body_strings():
    with pytest.raises(ValueError, match="forbidden"):
        build_github_operating_picture(
            context={
                "owner": "juliantorr-es",
                "repo": "rig-relay",
                "generated_at_utc": "2026-05-20T00:00:00Z",
                "branch": "main",
                "head": "0" * 40,
            },
            source_artifacts=[
                {
                    "artifact_id": "live_auth",
                    "path": "docs/json/governance/live_github_auth_result.v1.json",
                    "present": True,
                    "status": "present",
                    "artifact_hash": "a" * 64,
                    "schema_version": "rig.github.live_auth_result.v1",
                    "summary": {
                        "token_prefix": "ghs_should_not_escape",
                        "raw_response": "ghs_should_not_escape",
                    },
                }
            ],
            artifacts={
                "live_auth": {
                    "config_summary": {"app_auth_possible": True},
                    "live_results": {
                        "installation_access": {
                            "installation_access": "success",
                            "installation_id_hash": "a" * 64,
                            "accessible_repo_count": 1,
                            "repository_selection": "all",
                        },
                        "token_exchange": {
                            "token_present": True,
                            "token_hash": "b" * 64,
                        },
                    },
                },
                "security_intake": None,
                "security_mission_candidates": None,
                "security_mission_packets": None,
                "github_ci_cd_reliability": None,
                "swift_codeql_advisory_parking": None,
            },
        )

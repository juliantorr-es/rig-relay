"""GitHub security work item redaction adversarial tests."""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._security_work_items import (
    project_github_security_work_items,
)

pytestmark = [pytest.mark.adversarial]


def test_projection_output_never_contains_raw_secret_strings():
    intake = {
        "schema_version": "rig.github.security_intake.v1",
        "generated_at": "2026-05-19T00:00:00Z",
        "auth_mode": "app_installation",
        "owner_hash": "owner-hash",
        "repo_hash": "repo-hash",
        "installation_id_hash": "installation-hash",
        "trace_id": "trace-id",
        "receipt_id": "receipt-id",
        "dry_run": False,
        "content_light": True,
        "remote_mutation": False,
        "source_surfaces": [
            {
                "surface": "code_scanning",
                "status": "collected",
                "required_permission": "Code scanning alerts read",
                "remote_mutation": False,
            }
        ],
        "counts": {
            "code_scanning_open": 1,
            "code_scanning_total": 1,
            "dependabot_open": 0,
            "dependabot_total": 0,
            "refused_surfaces": 0,
        },
        "alerts": {
            "code_scanning": [
                {
                    "classification": "code_scanning",
                    "alert_number": 42,
                    "state": "open",
                    "created_at": "2020-02-13T12:29:18Z",
                    "updated_at": "2020-02-13T12:29:18Z",
                    "fixed_at": "",
                    "dismissed_at": "",
                    "rule_id_hash": "rule-hash",
                    "rule_severity": "error",
                    "rule_security_severity_level": "high",
                    "tool_name": "CodeQL",
                    "most_recent_instance_ref_hash": "ref-hash",
                    "file_path_hash": "path-hash",
                    "start_line": 1,
                    "end_line": 2,
                    "html_url_hash": "html-hash",
                    "suggested_group_kind": "codeql_security_fix_needed",
                    "raw_body": "ghs_should_not_appear",
                    "token_prefix": "ghs_should_not_appear",
                    "authorization": "Bearer ghs_should_not_appear",
                }
            ],
            "dependabot": [],
        },
        "patch_candidate_groups": [],
        "refusals": [],
    }

    report = project_github_security_work_items(
        intake,
        source_artifact_path="docs/json/governance/github_security_intake_result.v1.json",
        generated_at_utc="2026-05-19T00:00:00Z",
    )

    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
        '"access_token"',
        '"token_prefix"',
        '"authorization"',
        '"client_secret"',
        '"private_key"',
        '"raw_response"',
        '"raw_body"',
        '"patch"',
        '"diff"',
        '"contents"',
        '"code_snippet"',
        "diff --git",
    ):
        assert forbidden not in serialized

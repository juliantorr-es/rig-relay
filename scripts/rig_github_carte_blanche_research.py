#!/usr/bin/env python3
"""Rig Relay GitHub carte blanche research — emit structured research artifacts.

Generates 8 schema-governed artifacts mapping maximum GitHub integration surface
under full trust (carte blanche). Research-only; no live API calls, no mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "json" / "governance"

_FORBIDDEN_FIELDS = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "contents",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
})


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _load_git_metadata() -> tuple[str | None, str | None]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch or None, head or None
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _assert_content_light(val: Any) -> None:
    if isinstance(val, dict):
        for k, v in val.items():
            if k in _FORBIDDEN_FIELDS:
                raise ValueError(f"forbidden_key: {k}")
            _assert_content_light(v)
    elif isinstance(val, list):
        for item in val:
            _assert_content_light(item)
    elif isinstance(val, str):
        for pattern in (
            "ghp_",
            "gho_",
            "ghu_",
            "ghs_",
            "ghr_",
            "github_pat_",
            "ya29.",
            "1//",
            "BEGIN PRIVATE KEY",
        ):
            if pattern in val:
                raise ValueError(f"forbidden_pattern: {pattern}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# =============================================================================
# RESEARCH DATA
# =============================================================================

_PERMISSIONS = [
    {
        "permission_id": "contents",
        "permission_name": "Contents",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "repo_file_read",
            "repo_tree_read",
            "blob_read",
            "default_branch_read",
            "file_list_read",
        ],
        "enabled_write_lanes": [
            "repo_file_write",
            "branch_create",
            "commit_push",
            "blob_create",
            "pr_file_update",
            "commit_create",
        ],
        "enabled_automation_lanes": [
            "auto_commit_patch",
            "evidence_backed_pr",
            "changelog_update",
            "readme_update",
            "docs_sync",
        ],
        "enabled_security_lanes": [
            "security_policy_update",
            "codeowners_update",
            "dependabot_config_update",
            "workflow_file_update",
        ],
        "enabled_ci_lanes": ["ci_config_update", "actions_workflow_update"],
        "enabled_release_lanes": [
            "release_notes_write",
            "changelog_write",
            "build_config_update",
        ],
        "maximum_product_value": "high",
        "mutation_risk": "high",
        "supply_chain_risk": "high",
        "governance_required": "extreme",
        "implementation_priority": 1,
        "recommended_policy": "approval_required_every_mutation; receipt per commit; dry_run_preview_first",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/repos/contents",
            "https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps",
        ],
        "remaining_unknowns": ["Git LFS interaction with installation tokens"],
    },
    {
        "permission_id": "metadata",
        "permission_name": "Metadata",
        "permission_scope": "repository",
        "available_access_levels": ["read"],
        "enabled_read_lanes": [
            "repo_metadata_read",
            "topics_read",
            "description_read",
            "language_read",
            "license_read",
            "visibility_read",
        ],
        "enabled_write_lanes": [],
        "enabled_automation_lanes": [],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "medium",
        "mutation_risk": "none",
        "supply_chain_risk": "none",
        "governance_required": "minimal",
        "implementation_priority": 1,
        "recommended_policy": "always_allowed; read-only; foundational for operating picture",
        "official_docs_refs": ["https://docs.github.com/en/rest/repos/repos"],
        "remaining_unknowns": [],
    },
    {
        "permission_id": "pull_requests",
        "permission_name": "Pull Requests",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "pr_list_read",
            "pr_detail_read",
            "pr_review_read",
            "pr_comment_read",
            "pr_status_read",
            "pr_diff_read",
        ],
        "enabled_write_lanes": [
            "pr_create",
            "pr_update",
            "pr_close",
            "pr_reopen",
            "pr_merge",
            "pr_review_create",
            "pr_comment_create",
            "pr_assign",
            "pr_label",
            "pr_milestone",
        ],
        "enabled_automation_lanes": [
            "auto_pr_creation",
            "pr_triage",
            "pr_review_assignment",
            "pr_merge_queue",
            "pr_staleness_management",
        ],
        "enabled_security_lanes": [
            "security_patch_pr",
            "dependabot_pr_management",
            "codeql_fix_pr",
        ],
        "enabled_ci_lanes": [
            "pr_ci_trigger",
            "pr_status_check",
            "pr_checks_integration",
        ],
        "enabled_release_lanes": ["release_pr_creation", "version_bump_pr"],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "medium",
        "governance_required": "elevated",
        "implementation_priority": 2,
        "recommended_policy": "read always; write requires approval except label/assign; merge requires explicit human approval",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/pulls",
            "https://docs.github.com/en/graphql/reference/objects#pullrequest",
        ],
        "remaining_unknowns": [
            "merge queue API availability for GitHub Apps",
            "auto-merge behavior with installation tokens",
        ],
    },
    {
        "permission_id": "issues",
        "permission_name": "Issues",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "issue_list_read",
            "issue_detail_read",
            "issue_comment_read",
            "issue_timeline_read",
        ],
        "enabled_write_lanes": [
            "issue_create",
            "issue_update",
            "issue_close",
            "issue_reopen",
            "issue_comment",
            "issue_assign",
            "issue_label",
            "issue_milestone",
            "issue_lock",
        ],
        "enabled_automation_lanes": [
            "auto_issue_triage",
            "issue_inbox_zero",
            "issue_staleness_close",
            "issue_label_routing",
            "issue_duplicate_detection",
        ],
        "enabled_security_lanes": [
            "security_issue_creation",
            "vulnerability_disclosure_issue",
        ],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "high",
        "mutation_risk": "low",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 3,
        "recommended_policy": "read always; write allowed with evidence for label/assign/close/reopen; create requires human approval",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/issues",
            "https://docs.github.com/en/graphql/reference/objects#issue",
        ],
        "remaining_unknowns": [
            "issue forms beta API support",
            "sub-issues API availability",
        ],
    },
    {
        "permission_id": "actions",
        "permission_name": "Actions",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "workflow_list_read",
            "workflow_run_read",
            "workflow_log_read",
            "workflow_artifact_read",
            "workflow_job_read",
        ],
        "enabled_write_lanes": [
            "workflow_dispatch",
            "workflow_rerun",
            "workflow_cancel",
            "workflow_file_write",
        ],
        "enabled_automation_lanes": [
            "ci_failure_diagnosis",
            "ci_repair_loop",
            "workflow_health_monitor",
            "ci_config_optimizer",
        ],
        "enabled_security_lanes": ["ci_security_audit", "workflow_permission_review"],
        "enabled_ci_lanes": [
            "ci_pipeline_management",
            "build_trigger",
            "test_result_analysis",
        ],
        "enabled_release_lanes": ["release_build_trigger", "artifact_upload_trigger"],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "high",
        "governance_required": "elevated",
        "implementation_priority": 3,
        "recommended_policy": "read always; dispatch/rerun requires approval; workflow file write requires separate Content permission + approval",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/actions",
            "https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions",
        ],
        "remaining_unknowns": [
            "OIDC token interaction with installation tokens",
            "reusable workflow API availability",
        ],
    },
    {
        "permission_id": "security_events",
        "permission_name": "Security Events",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "code_scanning_alert_read",
            "secret_scanning_alert_read",
            "security_advisory_read",
        ],
        "enabled_write_lanes": [
            "code_scanning_alert_dismiss",
            "code_scanning_alert_reopen",
            "secret_scanning_alert_dismiss",
        ],
        "enabled_automation_lanes": [
            "codeql_alert_triage",
            "secret_scanning_queue_manager",
            "security_advisory_draft",
        ],
        "enabled_security_lanes": [
            "security_queue_burn_down",
            "vulnerability_alert_routing",
            "security_posture_report",
        ],
        "enabled_ci_lanes": ["security_ci_integration"],
        "enabled_release_lanes": [],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "low",
        "governance_required": "elevated",
        "implementation_priority": 2,
        "recommended_policy": "read always; dismiss/reopen only with evidence audit trail; never dismiss without linked fix PR",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/code-scanning",
            "https://docs.github.com/en/rest/secret-scanning",
        ],
        "remaining_unknowns": [
            "secret scanning alert dismissal API for installation tokens",
            "push protection bypass API",
        ],
    },
    {
        "permission_id": "dependabot_alerts",
        "permission_name": "Dependabot Alerts",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["dependabot_alert_list", "dependabot_alert_detail"],
        "enabled_write_lanes": ["dependabot_alert_dismiss", "dependabot_alert_reopen"],
        "enabled_automation_lanes": [
            "dependabot_queue_burn_down",
            "auto_dependency_update_pr",
        ],
        "enabled_security_lanes": [
            "supply_chain_vulnerability_tracking",
            "dependency_health_report",
        ],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "high",
        "mutation_risk": "low",
        "supply_chain_risk": "medium",
        "governance_required": "standard",
        "implementation_priority": 2,
        "recommended_policy": "read always; dismiss with evidence of fix; prioritize auto-update PRs",
        "official_docs_refs": ["https://docs.github.com/en/rest/dependabot/alerts"],
        "remaining_unknowns": ["dependabot version update config API stability"],
    },
    {
        "permission_id": "administration",
        "permission_name": "Administration",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "repo_settings_read",
            "branch_protection_read",
            "ruleset_read",
            "webhook_read",
            "deploy_key_read",
        ],
        "enabled_write_lanes": [
            "repo_settings_update",
            "branch_protection_update",
            "ruleset_update",
            "webhook_manage",
        ],
        "enabled_automation_lanes": [
            "branch_protection_audit",
            "ruleset_compliance_check",
            "settings_drift_detection",
        ],
        "enabled_security_lanes": [
            "security_setting_audit",
            "branch_protection_hardening",
        ],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "medium",
        "mutation_risk": "high",
        "supply_chain_risk": "high",
        "governance_required": "extreme",
        "implementation_priority": 6,
        "recommended_policy": "read-only by default; write requires super-admin-level approval; never auto-apply",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/repos/repos",
            "https://docs.github.com/en/rest/branches/branch-protection",
        ],
        "remaining_unknowns": [
            "ruleset management API completeness",
            "custom deployment protection rules API",
        ],
    },
    {
        "permission_id": "pages",
        "permission_name": "Pages",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "pages_status_read",
            "pages_build_read",
            "pages_deployment_read",
        ],
        "enabled_write_lanes": [
            "pages_build_trigger",
            "pages_source_update",
            "pages_cname_update",
        ],
        "enabled_automation_lanes": [
            "auto_docs_publish",
            "static_site_pipeline",
            "pages_health_monitor",
        ],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": ["pages_build_ci_trigger"],
        "enabled_release_lanes": ["docs_release_publish", "changelog_site_update"],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 4,
        "recommended_policy": "publish after docs build passes; preview before publish; never publish unapproved content",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/pages",
            "https://docs.github.com/en/pages",
        ],
        "remaining_unknowns": [
            "custom GitHub Pages deployment API",
            "branch-based pages API",
        ],
    },
    {
        "permission_id": "deployments",
        "permission_name": "Deployments",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "deployment_status_read",
            "deployment_list_read",
            "environment_read",
        ],
        "enabled_write_lanes": ["deployment_create", "deployment_status_update"],
        "enabled_automation_lanes": [
            "deployment_health_monitor",
            "deployment_rollback_detection",
        ],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": ["deployment_ci_integration"],
        "enabled_release_lanes": [
            "release_deployment_tracking",
            "environment_promotion",
        ],
        "maximum_product_value": "medium",
        "mutation_risk": "high",
        "supply_chain_risk": "medium",
        "governance_required": "elevated",
        "implementation_priority": 5,
        "recommended_policy": "read always; status update allowed; deployment create requires approval",
        "official_docs_refs": ["https://docs.github.com/en/rest/deployments"],
        "remaining_unknowns": ["environment protection rules API"],
    },
    {
        "permission_id": "webhooks",
        "permission_name": "Webhooks",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "webhook_list_read",
            "webhook_config_read",
            "webhook_delivery_read",
        ],
        "enabled_write_lanes": ["webhook_create", "webhook_update", "webhook_delete"],
        "enabled_automation_lanes": [
            "webhook_event_observer",
            "event_replay_reconciliation",
        ],
        "enabled_security_lanes": ["webhook_secret_audit"],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 7,
        "recommended_policy": "read webhook state; manage webhook registrations; validate webhook secrets",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/repos/webhooks",
            "https://docs.github.com/en/webhooks",
        ],
        "remaining_unknowns": ["webhook delivery redelivery API for Apps"],
    },
    {
        "permission_id": "members",
        "permission_name": "Members",
        "permission_scope": "organization",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "org_member_list",
            "team_member_list",
            "collaborator_list",
        ],
        "enabled_write_lanes": [],
        "enabled_automation_lanes": ["membership_audit", "access_review"],
        "enabled_security_lanes": ["org_access_posture"],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "medium",
        "mutation_risk": "none",
        "supply_chain_risk": "none",
        "governance_required": "minimal",
        "implementation_priority": 6,
        "recommended_policy": "read-only in v1; membership changes require org admin",
        "official_docs_refs": ["https://docs.github.com/en/rest/orgs/members"],
        "remaining_unknowns": [],
    },
    {
        "permission_id": "organization_administration",
        "permission_name": "Organization Administration",
        "permission_scope": "organization",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["org_settings_read", "org_audit_log_read"],
        "enabled_write_lanes": [],
        "enabled_automation_lanes": [],
        "enabled_security_lanes": ["org_security_audit", "org_2fa_audit"],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "low",
        "mutation_risk": "high",
        "supply_chain_risk": "high",
        "governance_required": "extreme",
        "implementation_priority": 8,
        "recommended_policy": "read-only audit only; write requires org admin approval",
        "official_docs_refs": ["https://docs.github.com/en/rest/orgs"],
        "remaining_unknowns": ["org-level API token requirements"],
    },
    {
        "permission_id": "projects",
        "permission_name": "Projects",
        "permission_scope": "organization",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "project_v2_list",
            "project_item_read",
            "project_view_read",
        ],
        "enabled_write_lanes": [
            "project_item_create",
            "project_item_update",
            "project_item_delete",
        ],
        "enabled_automation_lanes": [
            "project_board_auto_triage",
            "issue_to_project_routing",
        ],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": ["release_board_management"],
        "maximum_product_value": "medium",
        "mutation_risk": "low",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 5,
        "recommended_policy": "read always; item management with evidence; auto-routing allowed",
        "official_docs_refs": [
            "https://docs.github.com/en/issues/planning-and-tracking-with-projects"
        ],
        "remaining_unknowns": ["Projects v2 API completeness for GitHub Apps"],
    },
    {
        "permission_id": "secrets",
        "permission_name": "Secrets",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["actions_secret_names_read"],
        "enabled_write_lanes": [
            "actions_secret_create",
            "actions_secret_update",
            "actions_secret_delete",
        ],
        "enabled_automation_lanes": [],
        "enabled_security_lanes": ["secret_rotation_reminder"],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "low",
        "mutation_risk": "high",
        "supply_chain_risk": "extreme",
        "governance_required": "extreme",
        "implementation_priority": 8,
        "recommended_policy": "never read secret values; manage secret existence only; rotation advisory only",
        "official_docs_refs": ["https://docs.github.com/en/rest/actions/secrets"],
        "remaining_unknowns": [],
    },
    {
        "permission_id": "statuses",
        "permission_name": "Commit Statuses",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": [
            "commit_status_read",
            "check_run_read",
            "check_suite_read",
        ],
        "enabled_write_lanes": ["commit_status_create"],
        "enabled_automation_lanes": ["status_health_monitor", "ci_status_aggregator"],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": ["ci_status_reporting"],
        "enabled_release_lanes": ["release_commit_verification"],
        "maximum_product_value": "medium",
        "mutation_risk": "low",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 3,
        "recommended_policy": "read always; status creation for evidence-backed checks only",
        "official_docs_refs": [
            "https://docs.github.com/en/rest/commits/statuses",
            "https://docs.github.com/en/rest/checks",
        ],
        "remaining_unknowns": ["check suite re-request API for Apps"],
    },
    {
        "permission_id": "repository_hooks",
        "permission_name": "Repository Webhooks",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["webhook_list_read", "webhook_delivery_read"],
        "enabled_write_lanes": [
            "webhook_create",
            "webhook_update",
            "webhook_delete",
            "webhook_ping",
        ],
        "enabled_automation_lanes": [
            "webhook_event_observer",
            "event_driven_github_ops",
        ],
        "enabled_security_lanes": ["webhook_secret_validation"],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "high",
        "mutation_risk": "medium",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 7,
        "recommended_policy": "manage webhook registrations; validate signatures always",
        "official_docs_refs": ["https://docs.github.com/en/rest/repos/webhooks"],
        "remaining_unknowns": [],
    },
    {
        "permission_id": "repository_projects",
        "permission_name": "Repository Projects",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["project_list_read"],
        "enabled_write_lanes": ["project_create_update"],
        "enabled_automation_lanes": [],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "low",
        "mutation_risk": "low",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 8,
        "recommended_policy": "read allowed; write requires approval",
        "official_docs_refs": ["https://docs.github.com/en/rest/projects"],
        "remaining_unknowns": ["Projects classic vs v2 migration API"],
    },
    {
        "permission_id": "discussions",
        "permission_name": "Discussions",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["discussion_list_read", "discussion_comment_read"],
        "enabled_write_lanes": [
            "discussion_create",
            "discussion_comment",
            "discussion_answer_mark",
        ],
        "enabled_automation_lanes": ["discussion_moderation", "qa_thread_closure"],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": ["release_discussion_announcement"],
        "maximum_product_value": "medium",
        "mutation_risk": "low",
        "supply_chain_risk": "low",
        "governance_required": "standard",
        "implementation_priority": 5,
        "recommended_policy": "read always; write allowed with evidence",
        "official_docs_refs": [
            "https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions"
        ],
        "remaining_unknowns": ["GraphQL-only limitations", "discussion category API"],
    },
    {
        "permission_id": "codespaces",
        "permission_name": "Codespaces",
        "permission_scope": "repository",
        "available_access_levels": ["read", "write"],
        "enabled_read_lanes": ["codespace_list_read"],
        "enabled_write_lanes": [],
        "enabled_automation_lanes": [],
        "enabled_security_lanes": [],
        "enabled_ci_lanes": [],
        "enabled_release_lanes": [],
        "maximum_product_value": "low",
        "mutation_risk": "none",
        "supply_chain_risk": "none",
        "governance_required": "minimal",
        "implementation_priority": 8,
        "recommended_policy": "read-only observation",
        "official_docs_refs": ["https://docs.github.com/en/rest/codespaces"],
        "remaining_unknowns": [],
    },
]

_SURFACES = [
    {
        "surface_id": "repo_metadata",
        "human_name": "Repository Metadata",
        "value_proposition": "Complete read-only view of repository settings, topics, description, language, license",
        "developer_pain_removed": "Scattered across Settings tabs; no programmatic summary",
        "read_operations": ["GET /repos/{owner}/{repo}"],
        "write_operations": [],
        "destructive_operations": [],
        "required_permissions": ["metadata:read"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "hash repo name, owner; store topic list as strings",
        "evidence_strategy": "operating picture snapshot",
        "first_slice": "repo_operating_picture",
        "mature_lane": "multi_repo_inventory",
        "out_of_scope_boundary": "private repo content",
        "risk_level": "low",
        "recommended_phase": "phase_0",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "repo_topics",
        "human_name": "Repository Topics",
        "value_proposition": "Programmatic topic management for discoverability",
        "developer_pain_removed": "Manual topic entry; no bulk management",
        "read_operations": ["GET /repos/{owner}/{repo}/topics"],
        "write_operations": ["PUT /repos/{owner}/{repo}/topics"],
        "destructive_operations": [],
        "required_permissions": ["metadata:read", "administration:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "topic strings only; no private data",
        "evidence_strategy": "topic diff receipt",
        "first_slice": "public_surface_program",
        "mature_lane": "repo_discovery_optimizer",
        "out_of_scope_boundary": "none",
        "risk_level": "low",
        "recommended_phase": "phase_1",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "profile_readme",
        "human_name": "Profile README",
        "value_proposition": "Maintain developer profile README as a living portfolio surface",
        "developer_pain_removed": "Profile README rot; no automated update pipeline",
        "read_operations": ["GET /repos/{user}/{user}/contents/README.md"],
        "write_operations": ["PUT /repos/{user}/{user}/contents/README.md"],
        "destructive_operations": [],
        "required_permissions": ["contents:read", "contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "hash profile content; store stats in claims index",
        "evidence_strategy": "evidence-backed claims index",
        "first_slice": "profile_readme_audit",
        "mature_lane": "profile_portfolio_maintainer",
        "out_of_scope_boundary": "private profile info",
        "risk_level": "medium",
        "recommended_phase": "phase_1",
        "remaining_unknowns": ["profile repo naming convention API"],
    },
    {
        "surface_id": "project_readme",
        "human_name": "Project README",
        "value_proposition": "Keep project README current with badges, claims, installation instructions",
        "developer_pain_removed": "Badge rot; stale installation docs; manual claim updates",
        "read_operations": ["GET /repos/{owner}/{repo}/readme"],
        "write_operations": ["PUT /repos/{owner}/{repo}/contents/README.md"],
        "destructive_operations": [],
        "required_permissions": ["contents:read", "contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "section hashes; badge status mapping",
        "evidence_strategy": "surface audit",
        "first_slice": "readme_surface_audit",
        "mature_lane": "public_surface_maintainer",
        "out_of_scope_boundary": "README content extraction",
        "risk_level": "medium",
        "recommended_phase": "phase_1",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "repo_description",
        "human_name": "Repository Description & Homepage",
        "value_proposition": "Keep repository description and homepage URL current",
        "developer_pain_removed": "Forgetting to update description after pivot",
        "read_operations": ["GET /repos/{owner}/{repo}"],
        "write_operations": ["PATCH /repos/{owner}/{repo}"],
        "destructive_operations": [],
        "required_permissions": ["administration:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "description string hash",
        "evidence_strategy": "description diff receipt",
        "first_slice": "public_surface_program",
        "mature_lane": "repo_metadata_maintainer",
        "out_of_scope_boundary": "visibility changes",
        "risk_level": "medium",
        "recommended_phase": "phase_1",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "github_pages",
        "human_name": "GitHub Pages",
        "value_proposition": "Automated docs site publishing with preview and rollback",
        "developer_pain_removed": "Manual Pages deploy; broken builds unnoticed; no preview",
        "read_operations": [
            "GET /repos/{owner}/{repo}/pages",
            "GET /repos/{owner}/{repo}/pages/builds",
        ],
        "write_operations": [
            "POST /repos/{owner}/{repo}/pages/builds",
            "PUT /repos/{owner}/{repo}/pages",
        ],
        "destructive_operations": [],
        "required_permissions": ["pages:read", "pages:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["public_repos_only_free"],
        "content_light_strategy": "build status, domain hash, CNAME hash",
        "evidence_strategy": "build log hash, deploy receipt",
        "first_slice": "pages_status_monitor",
        "mature_lane": "docs_site_publisher",
        "out_of_scope_boundary": "custom domain management",
        "risk_level": "medium",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "releases",
        "human_name": "Releases",
        "value_proposition": "Automated release management with changelog, assets, and evidence",
        "developer_pain_removed": "Manual release drafting; forgetting release notes; asset upload tedium",
        "read_operations": [
            "GET /repos/{owner}/{repo}/releases",
            "GET /repos/{owner}/{repo}/releases/latest",
        ],
        "write_operations": [
            "POST /repos/{owner}/{repo}/releases",
            "PATCH /repos/{owner}/{repo}/releases/{id}",
            "POST upload release asset",
        ],
        "destructive_operations": ["DELETE /repos/{owner}/{repo}/releases/{id}"],
        "required_permissions": ["contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": True,
        "plan_limitations": [],
        "content_light_strategy": "release tag hash, name hash, body hash",
        "evidence_strategy": "release receipt with asset hashes",
        "first_slice": "release_draft_assistant",
        "mature_lane": "release_manager",
        "out_of_scope_boundary": "delete releases by default",
        "risk_level": "high",
        "recommended_phase": "phase_5",
        "remaining_unknowns": ["release asset upload with installation token"],
    },
    {
        "surface_id": "issues",
        "human_name": "Issues",
        "value_proposition": "Full issue lifecycle management with triage, labeling, and routing",
        "developer_pain_removed": "Issue backlog; manual triage; no auto-labeling; duplicate detection missing",
        "read_operations": [
            "GET /repos/{owner}/{repo}/issues",
            "GET /repos/{owner}/{repo}/issues/{number}",
        ],
        "write_operations": [
            "POST /repos/{owner}/{repo}/issues",
            "PATCH /repos/{owner}/{repo}/issues/{number}",
        ],
        "destructive_operations": [],
        "required_permissions": ["issues:read", "issues:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": True,
        "plan_limitations": [],
        "content_light_strategy": "issue number, title hash, state, label list; never body content",
        "evidence_strategy": "issue action receipt",
        "first_slice": "issue_triage_inbox_zero",
        "mature_lane": "issue_triage_manager",
        "out_of_scope_boundary": "reading issue bodies without explicit opt-in",
        "risk_level": "low",
        "recommended_phase": "phase_3",
        "remaining_unknowns": ["issue locking API for Apps"],
    },
    {
        "surface_id": "pull_requests",
        "human_name": "Pull Requests",
        "value_proposition": "Evidence-backed PR creation, review, and merge management",
        "developer_pain_removed": "No automated PR creation from evidence; manual review assignment; stale PR tracking missing",
        "read_operations": [
            "GET /repos/{owner}/{repo}/pulls",
            "GET /repos/{owner}/{repo}/pulls/{number}",
        ],
        "write_operations": [
            "POST /repos/{owner}/{repo}/pulls",
            "PATCH /repos/{owner}/{repo}/pulls/{number}",
            "POST merge",
        ],
        "destructive_operations": [],
        "required_permissions": [
            "pull_requests:read",
            "pull_requests:write",
            "contents:write",
        ],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": True,
        "plan_limitations": [],
        "content_light_strategy": "PR number, title hash, state, branch refs, SHA hashes; never diff content in artifacts",
        "evidence_strategy": "pr_creation_receipt with evidence refs",
        "first_slice": "evidence_backed_pr",
        "mature_lane": "pull_request_copilot",
        "out_of_scope_boundary": "auto-merge without approval",
        "risk_level": "high",
        "recommended_phase": "phase_3",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "branch_protection",
        "human_name": "Branch Protection",
        "value_proposition": "Audit and maintain branch protection rules",
        "developer_pain_removed": "No visibility into protection drift; manual rule review",
        "read_operations": ["GET /repos/{owner}/{repo}/branches/{branch}/protection"],
        "write_operations": ["PUT /repos/{owner}/{repo}/branches/{branch}/protection"],
        "destructive_operations": ["DELETE protection"],
        "required_permissions": ["administration:read", "administration:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": ["public_repos_free"],
        "content_light_strategy": "rule names, counts; never settings details in public artifacts",
        "evidence_strategy": "protection drift report",
        "first_slice": "branch_protection_audit",
        "mature_lane": "branch_hygiene_operator",
        "out_of_scope_boundary": "auto-apply protection changes",
        "risk_level": "high",
        "recommended_phase": "phase_6",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "rulesets",
        "human_name": "Repository Rulesets",
        "value_proposition": "Manage repository-level rules for branch/tag protection at scale",
        "developer_pain_removed": "No programmatic ruleset management; drift undetected",
        "read_operations": ["GET /repos/{owner}/{repo}/rulesets"],
        "write_operations": ["POST /repos/{owner}/{repo}/rulesets", "PUT ruleset"],
        "destructive_operations": ["DELETE ruleset"],
        "required_permissions": ["administration:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "ruleset name, enforcement level, target; never bypass list in public",
        "evidence_strategy": "ruleset compliance report",
        "first_slice": "ruleset_audit",
        "mature_lane": "repo_hygiene_operator",
        "out_of_scope_boundary": "auto-apply ruleset changes",
        "risk_level": "high",
        "recommended_phase": "phase_6",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "dependabot_config",
        "human_name": "Dependabot Configuration",
        "value_proposal": "Manage Dependabot version/security update configuration",
        "value_proposition": "Programmatic Dependabot config management",
        "developer_pain_removed": "Manual dependabot.yml editing; version update schedule management",
        "read_operations": [
            "GET /repos/{owner}/{repo}/contents/.github/dependabot.yml"
        ],
        "write_operations": ["PUT dependabot.yml"],
        "destructive_operations": [],
        "required_permissions": ["contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "config hash; package ecosystem list",
        "evidence_strategy": "config change receipt",
        "first_slice": "dependabot_config_audit",
        "mature_lane": "dependabot_manager",
        "out_of_scope_boundary": "none",
        "risk_level": "medium",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "codeql_config",
        "human_name": "CodeQL Configuration",
        "value_proposition": "Manage CodeQL analysis configuration",
        "developer_pain_removed": "CodeQL misconfiguration; query suite management",
        "read_operations": ["GET codeql config file"],
        "write_operations": ["PUT codeql config file"],
        "destructive_operations": [],
        "required_permissions": ["contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": ["default_setup_only_free"],
        "content_light_strategy": "config hash; query suite list",
        "evidence_strategy": "config audit receipt",
        "first_slice": "codeql_config_audit",
        "mature_lane": "codeql_manager",
        "out_of_scope_boundary": "none",
        "risk_level": "medium",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "code_scanning_alerts",
        "human_name": "Code Scanning Alerts",
        "value_proposition": "Full code scanning alert lifecycle: triage, fix PR, dismiss",
        "developer_pain_removed": "Alert backlog; no automated fix pipeline; manual dismissal",
        "read_operations": ["GET /repos/{owner}/{repo}/code-scanning/alerts"],
        "write_operations": ["PATCH alert state"],
        "destructive_operations": [],
        "required_permissions": ["security_events:read", "security_events:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["default_setup_only_free", "advanced_setup_enterprise"],
        "content_light_strategy": "alert number, rule id, severity, state; never code snippet",
        "evidence_strategy": "alert state change receipt",
        "first_slice": "codeql_alert_burn_down",
        "mature_lane": "security_queue_manager",
        "out_of_scope_boundary": "reading alert code snippets into artifacts",
        "risk_level": "medium",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "secret_scanning_alerts",
        "human_name": "Secret Scanning Alerts",
        "value_proposition": "Full secret scanning alert lifecycle management",
        "developer_pain_removed": "Alert fatigue; manual secret revocation; no automated tracking",
        "read_operations": ["GET /repos/{owner}/{repo}/secret-scanning/alerts"],
        "write_operations": ["PATCH alert state"],
        "destructive_operations": [],
        "required_permissions": ["security_events:read", "security_events:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["enterprise_for_push_protection"],
        "content_light_strategy": "alert number, secret type, state; NEVER secret value or location",
        "evidence_strategy": "alert state receipt with resolution evidence",
        "first_slice": "secret_boundary_manager",
        "mature_lane": "secret_boundary_manager",
        "out_of_scope_boundary": "reading secret values; exposing secret locations in public artifacts",
        "risk_level": "high",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "dependabot_alerts",
        "human_name": "Dependabot Alerts",
        "value_proposition": "Supply chain vulnerability tracking and automated fix PRs",
        "developer_pain_removed": "Dependency vulnerability backlog; manual update PR review",
        "read_operations": ["GET /repos/{owner}/{repo}/dependabot/alerts"],
        "write_operations": ["PATCH alert state"],
        "destructive_operations": [],
        "required_permissions": ["dependabot_alerts:read", "dependabot_alerts:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": [],
        "content_light_strategy": "alert number, package name, severity, state; never vulnerable code",
        "evidence_strategy": "alert fix receipt with PR reference",
        "first_slice": "dependabot_queue_burn_down",
        "mature_lane": "dependabot_manager",
        "out_of_scope_boundary": "auto-dismiss without fix",
        "risk_level": "medium",
        "recommended_phase": "phase_2",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "security_advisories",
        "human_name": "Security Advisories",
        "value_proposition": "Repository security advisory lifecycle management",
        "developer_pain_removed": "Manual advisory drafting; no automated CVE request pipeline",
        "read_operations": ["GET /repos/{owner}/{repo}/security-advisories"],
        "write_operations": ["POST create advisory", "PATCH advisory"],
        "destructive_operations": [],
        "required_permissions": ["security_events:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["public_repos_only"],
        "content_light_strategy": "advisory GHSA ID, severity, state; never full description",
        "evidence_strategy": "advisory state receipt",
        "first_slice": "security_advisory_draft_assistant",
        "mature_lane": "security_queue_manager",
        "out_of_scope_boundary": "publishing advisories without review",
        "risk_level": "high",
        "recommended_phase": "phase_2",
        "remaining_unknowns": ["CVE request API availability for Apps"],
    },
    {
        "surface_id": "actions_workflows",
        "human_name": "Actions Workflows",
        "value_proposition": "CI workflow health monitoring, dispatch, and optimization",
        "developer_pain_removed": "CI failures unnoticed; manual reruns; workflow drift",
        "read_operations": [
            "GET /repos/{owner}/{repo}/actions/workflows",
            "GET runs",
            "GET logs",
        ],
        "write_operations": ["POST dispatch", "POST rerun", "POST cancel"],
        "destructive_operations": [],
        "required_permissions": ["actions:read", "actions:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["free_minutes_limited"],
        "content_light_strategy": "workflow name, run ID, conclusion; never log content in artifacts",
        "evidence_strategy": "workflow_run receipt with conclusion hash",
        "first_slice": "ci_health_monitor",
        "mature_lane": "ci_actions_operator",
        "out_of_scope_boundary": "reading workflow logs into artifacts",
        "risk_level": "medium",
        "recommended_phase": "phase_4",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "workflow_files",
        "human_name": "Workflow File Management",
        "value_proposition": "Edit GitHub Actions workflow files under governance",
        "developer_pain_removed": "Manual YAML editing; workflow permission drift",
        "read_operations": ["GET workflow file contents"],
        "write_operations": ["PUT workflow file"],
        "destructive_operations": [],
        "required_permissions": ["contents:write", "workflows:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "file hash; change description",
        "evidence_strategy": "workflow change receipt with diff hash",
        "first_slice": "workflow_security_audit",
        "mature_lane": "ci_actions_operator",
        "out_of_scope_boundary": "auto-apply workflow changes without review",
        "risk_level": "high",
        "recommended_phase": "phase_4",
        "remaining_unknowns": [
            "workflows permission requirement for installation tokens"
        ],
    },
    {
        "surface_id": "collaborators",
        "human_name": "Collaborators",
        "value_proposition": "Repository collaborator audit and access review",
        "developer_pain_removed": "Unknown who has access; stale collaborator permissions",
        "read_operations": ["GET /repos/{owner}/{repo}/collaborators"],
        "write_operations": ["PUT add collaborator", "DELETE collaborator"],
        "destructive_operations": [],
        "required_permissions": ["members:read", "members:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "collaborator count; permission level distribution; never usernames in public",
        "evidence_strategy": "access review report",
        "first_slice": "collaborator_audit",
        "mature_lane": "org_hygiene_operator",
        "out_of_scope_boundary": "auto-remove collaborators",
        "risk_level": "high",
        "recommended_phase": "phase_6",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "deploy_keys",
        "human_name": "Deploy Keys",
        "value_proposition": "Audit deploy key usage and staleness",
        "developer_pain_removed": "Forgotten deploy keys; no usage tracking",
        "read_operations": ["GET /repos/{owner}/{repo}/keys"],
        "write_operations": ["POST create key", "DELETE key"],
        "destructive_operations": [],
        "required_permissions": ["administration:read", "administration:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "key ID hash, title hash, created_at; never key material",
        "evidence_strategy": "deploy key audit report",
        "first_slice": "deploy_key_audit",
        "mature_lane": "repo_hygiene_operator",
        "out_of_scope_boundary": "creating deploy keys",
        "risk_level": "high",
        "recommended_phase": "phase_6",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "environments",
        "human_name": "Environments & Deployments",
        "value_proposition": "Environment protection and deployment status monitoring",
        "developer_pain_removed": "Environment drift; deployment status unknown",
        "read_operations": [
            "GET /repos/{owner}/{repo}/environments",
            "GET deployments",
        ],
        "write_operations": ["POST create deployment status"],
        "destructive_operations": [],
        "required_permissions": ["deployments:read", "deployments:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": True,
        "plan_limitations": ["public_repos_only_free"],
        "content_light_strategy": "environment name hash, deployment status",
        "evidence_strategy": "deployment receipt",
        "first_slice": "deployment_status_monitor",
        "mature_lane": "release_manager",
        "out_of_scope_boundary": "auto-create deployments",
        "risk_level": "medium",
        "recommended_phase": "phase_5",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "organization_members",
        "human_name": "Organization Members & Teams",
        "value_proposition": "Organization membership audit and access posture",
        "developer_pain_removed": "No org-level access visibility; stale membership",
        "read_operations": ["GET /orgs/{org}/members", "GET /orgs/{org}/teams"],
        "write_operations": [],
        "destructive_operations": [],
        "required_permissions": ["members:read"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": True,
        "webhook_support": True,
        "plan_limitations": [],
        "content_light_strategy": "member count, role distribution; never member logins in public",
        "evidence_strategy": "org access posture report",
        "first_slice": "org_membership_audit",
        "mature_lane": "org_hygiene_operator",
        "out_of_scope_boundary": "auto-modify membership",
        "risk_level": "medium",
        "recommended_phase": "phase_6",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "traffic_insights",
        "human_name": "Traffic & Insights",
        "value_proposition": "Repository traffic and referral analytics",
        "developer_pain_removed": "No visibility into repo views, clones, referrers",
        "read_operations": [
            "GET /repos/{owner}/{repo}/traffic/views",
            "GET clones",
            "GET referrers",
        ],
        "write_operations": [],
        "destructive_operations": [],
        "required_permissions": ["metadata:read"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "view count, clone count; never referrer URLs in public",
        "evidence_strategy": "traffic snapshot",
        "first_slice": "traffic_insights_dashboard",
        "mature_lane": "telemetry_insights_operator",
        "out_of_scope_boundary": "logging referrer details",
        "risk_level": "low",
        "recommended_phase": "phase_7",
        "remaining_unknowns": [],
    },
    {
        "surface_id": "community_health",
        "human_name": "Community Health Files",
        "value_proposition": "Maintain community health files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY)",
        "developer_pain_removed": "Missing or stale community files; manual updates",
        "read_operations": ["GET community profile", "GET individual files"],
        "write_operations": ["PUT file contents"],
        "destructive_operations": [],
        "required_permissions": ["contents:read", "contents:write"],
        "auth_mode": "installation_token",
        "REST_support": True,
        "GraphQL_support": False,
        "webhook_support": False,
        "plan_limitations": [],
        "content_light_strategy": "file present boolean, file hash",
        "evidence_strategy": "community health scorecard",
        "first_slice": "community_health_audit",
        "mature_lane": "community_health_maintainer",
        "out_of_scope_boundary": "none",
        "risk_level": "low",
        "recommended_phase": "phase_1",
        "remaining_unknowns": [],
    },
]

_MUTATIONS = [
    {
        "mutation_lane_id": "branch_create",
        "user_visible_value": "Create feature/fix branches for evidence-backed changes",
        "official_endpoint": "POST /repos/{owner}/{repo}/git/refs",
        "required_permission": "contents:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "operating_picture_snapshot",
            "evidence_backed_claims_index",
        ],
        "required_approval_level": "none_for_read_only_worktree",
        "rollback_strategy": "delete branch if unmerged",
        "dry_run_strategy": "create branch in local worktree first",
        "receipt_fields": ["branch_name_hash", "base_sha", "ref_sha"],
        "dangerous_failure_modes": [
            "pushing_to_default_branch_by_accident",
            "force_push_on_existing_branch",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "contract tests with fake git references",
    },
    {
        "mutation_lane_id": "commit_file_changes",
        "user_visible_value": "Commit file changes with evidence-backed change description",
        "official_endpoint": "PUT /repos/{owner}/{repo}/contents/{path}",
        "required_permission": "contents:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "evidence_backed_claims_index",
            "dry_run_preview",
        ],
        "required_approval_level": "human_review_and_approval",
        "rollback_strategy": "revert commit via new commit",
        "dry_run_strategy": "local patch application preview",
        "receipt_fields": [
            "file_path_hash",
            "before_sha",
            "after_sha_probable",
            "commit_message_hash",
        ],
        "dangerous_failure_modes": [
            "overwriting_other_agents_work",
            "committing_secrets",
            "large_binary_files",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real worktree fixtures",
    },
    {
        "mutation_lane_id": "open_pull_request",
        "user_visible_value": "Open evidence-backed PR from research/fix branch",
        "official_endpoint": "POST /repos/{owner}/{repo}/pulls",
        "required_permission": "pull_requests:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "evidence_backed_claims_index",
            "dry_run_diff_review",
        ],
        "required_approval_level": "human_review_before_open",
        "rollback_strategy": "close PR if rejected",
        "dry_run_strategy": "preview PR body and diff locally",
        "receipt_fields": [
            "pr_number",
            "pr_url_hash",
            "head_branch_hash",
            "base_branch_hash",
        ],
        "dangerous_failure_modes": [
            "opening_pr_on_wrong_base_branch",
            "including_secrets_in_pr_body",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo fixtures",
    },
    {
        "mutation_lane_id": "merge_pull_request",
        "user_visible_value": "Merge approved PR when all checks pass and explicit approval received",
        "official_endpoint": "PUT /repos/{owner}/{repo}/pulls/{number}/merge",
        "required_permission": "contents:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": ["pr_status_check_report", "approval_receipt"],
        "required_approval_level": "explicit_human_merge_approval",
        "rollback_strategy": "revert merge commit",
        "dry_run_strategy": "check mergeability via API before merge",
        "receipt_fields": ["pr_number", "merge_sha", "merge_method"],
        "dangerous_failure_modes": [
            "merging_into_protected_branch_without_checks",
            "merge_conflict_resolution_error",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo and branch protection fixtures",
    },
    {
        "mutation_lane_id": "create_issue",
        "user_visible_value": "Create issues for discovered work, vulnerabilities, or maintenance tasks",
        "official_endpoint": "POST /repos/{owner}/{repo}/issues",
        "required_permission": "issues:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": ["evidence_backed_finding"],
        "required_approval_level": "none_for_internal_created_issues",
        "rollback_strategy": "close issue if created in error",
        "dry_run_strategy": "preview issue body locally",
        "receipt_fields": ["issue_number", "issue_title_hash"],
        "dangerous_failure_modes": [
            "creating_duplicate_issues",
            "including_sensitive_data_in_issue_body",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo fixtures",
    },
    {
        "mutation_lane_id": "label_issue_or_pr",
        "user_visible_value": "Apply labels for triage routing and status tracking",
        "official_endpoint": "POST /repos/{owner}/{repo}/issues/{number}/labels",
        "required_permission": "issues:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": ["label_classification_rules"],
        "required_approval_level": "none_automatic_under_policy",
        "rollback_strategy": "remove label",
        "dry_run_strategy": "predict label assignments before applying",
        "receipt_fields": ["issue_number", "applied_labels", "removed_labels"],
        "dangerous_failure_modes": [
            "applying_wrong_labels_at_scale",
            "conflicting_label_sets",
        ],
        "recommended_initial_state": "automatic_under_policy",
        "test_strategy": "contract tests with label classification fixtures",
    },
    {
        "mutation_lane_id": "create_release",
        "user_visible_value": "Create GitHub Releases with changelog and evidence-backed release notes",
        "official_endpoint": "POST /repos/{owner}/{repo}/releases",
        "required_permission": "contents:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "release_notes_draft",
            "changelog_diff",
            "validation_suite_results",
        ],
        "required_approval_level": "human_release_approval",
        "rollback_strategy": "delete release; recreate with corrected data",
        "dry_run_strategy": "preview release body and tag locally",
        "receipt_fields": ["release_id", "tag_name", "release_body_hash"],
        "dangerous_failure_modes": [
            "tagging_wrong_commit",
            "overwriting_existing_release",
            "uploading_wrong_assets",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo release fixtures",
    },
    {
        "mutation_lane_id": "trigger_workflow_dispatch",
        "user_visible_value": "Trigger CI workflows on demand with evidence-backed parameters",
        "official_endpoint": "POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches",
        "required_permission": "actions:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": ["ci_trigger_justification"],
        "required_approval_level": "human_approval_for_production_triggers",
        "rollback_strategy": "cancel triggered run",
        "dry_run_strategy": "validate workflow dispatch inputs locally",
        "receipt_fields": ["workflow_id", "dispatch_ref", "inputs_hash"],
        "dangerous_failure_modes": [
            "triggering_production_deployment_pipeline",
            "exhausting_ci_minutes",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo CI fixtures",
    },
    {
        "mutation_lane_id": "update_repository_description",
        "user_visible_value": "Update repository description from evidence-backed claims index",
        "official_endpoint": "PATCH /repos/{owner}/{repo}",
        "required_permission": "administration:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "evidence_backed_claims_index",
            "description_draft",
        ],
        "required_approval_level": "human_review",
        "rollback_strategy": "revert to previous description",
        "dry_run_strategy": "preview new description",
        "receipt_fields": ["before_hash", "after_hash", "field_changed"],
        "dangerous_failure_modes": ["accidentally_changing_visibility_or_settings"],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo fixtures",
    },
    {
        "mutation_lane_id": "dismiss_code_scanning_alert",
        "user_visible_value": "Dismiss code scanning alerts with evidence of fix or false positive determination",
        "official_endpoint": "PATCH /repos/{owner}/{repo}/code-scanning/alerts/{number}",
        "required_permission": "security_events:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "fix_evidence_report",
            "false_positive_analysis",
        ],
        "required_approval_level": "human_for_dismissal_no_fix",
        "rollback_strategy": "reopen alert",
        "dry_run_strategy": "preview dismissal reason before applying",
        "receipt_fields": ["alert_number", "new_state", "dismissal_reason_hash"],
        "dangerous_failure_modes": [
            "dismissing_critical_vulnerability_without_fix",
            "bulk_dismissing_real_alerts",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "contract tests with alert fixture data",
    },
    {
        "mutation_lane_id": "update_workflow_file",
        "user_visible_value": "Edit GitHub Actions workflow files for security hardening or optimization",
        "official_endpoint": "PUT /repos/{owner}/{repo}/contents/.github/workflows/{file}",
        "required_permission": "contents:write + workflows:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": [
            "workflow_security_audit_report",
            "dry_run_diff",
        ],
        "required_approval_level": "human_review_mandatory",
        "rollback_strategy": "revert workflow file commit",
        "dry_run_strategy": "local workflow validation with act or similar",
        "receipt_fields": ["file_path_hash", "before_sha", "after_sha_probable"],
        "dangerous_failure_modes": [
            "breaking_ci_pipeline",
            "introducing_security_regression",
            "exposing_secrets_in_workflow",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo CI workflow fixtures",
    },
    {
        "mutation_lane_id": "publish_github_pages_content",
        "user_visible_value": "Publish updated docs site content after approval",
        "official_endpoint": "POST /repos/{owner}/{repo}/pages/builds or PUT content",
        "required_permission": "pages:write + contents:write",
        "auth_mode": "installation_token",
        "can_be_done_by_github_app": True,
        "requires_user_oauth": False,
        "required_preflight_artifacts": ["static_site_build_report", "content_preview"],
        "required_approval_level": "human_review_before_publish",
        "rollback_strategy": "trigger re-deploy of previous commit",
        "dry_run_strategy": "local static site build preview",
        "receipt_fields": ["build_status", "deployment_hash"],
        "dangerous_failure_modes": [
            "publishing_broken_site",
            "publishing_stale_content",
            "exposing_private_docs",
        ],
        "recommended_initial_state": "approval_required",
        "test_strategy": "integration with real repo Pages fixtures",
    },
]

_WEBHOOKS = [
    {
        "event_name": "installation",
        "permission_required": "none (app-level)",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "refresh_operating_picture",
            "validate_installation_access",
            "update_repo_inventory",
        ],
        "local_artifacts_to_update": ["operating_picture", "repo_inventory"],
        "followup_api_reads": ["list_accessible_repos", "probe_installation_access"],
        "possible_mutations": [],
        "dedupe_key": "installation_id+action",
        "replay_strategy": "idempotency check via installation state",
        "webhook_signature_required": True,
        "queue_strategy": "immediate_processing",
        "telemetry_value": "high",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#installation"
        ],
    },
    {
        "event_name": "push",
        "permission_required": "contents:read",
        "payload_sensitivity": "high",
        "useful_relay_reactions": [
            "update_commit_vs_evidence_index",
            "trigger_surface_audit",
            "check_for_config_changes",
        ],
        "local_artifacts_to_update": [
            "operating_picture",
            "evidence_index",
            "surface_audit_cache",
        ],
        "followup_api_reads": ["get_commit_details", "compare_commits"],
        "possible_mutations": ["open_branch_for_fix_if_security_event"],
        "dedupe_key": "repository_id+after_sha",
        "replay_strategy": "compare commit SHA; skip if already processed",
        "webhook_signature_required": True,
        "queue_strategy": "batch_by_repo_with_debounce",
        "telemetry_value": "high",
        "risk_level": "medium",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#push"
        ],
    },
    {
        "event_name": "pull_request",
        "permission_required": "pull_requests:read",
        "payload_sensitivity": "high",
        "useful_relay_reactions": [
            "pr_triage",
            "update_pr_queue",
            "check_pr_against_evidence",
            "auto_label",
        ],
        "local_artifacts_to_update": ["pr_queue", "operating_picture"],
        "followup_api_reads": ["get_pr_details", "get_pr_reviews", "get_pr_commits"],
        "possible_mutations": [
            "add_pr_labels",
            "request_reviewers",
            "post_review_comment",
        ],
        "dedupe_key": "repository_id+pr_number+action",
        "replay_strategy": "fetch latest PR state; compare with stored state",
        "webhook_signature_required": True,
        "queue_strategy": "priority_queue_by_action",
        "telemetry_value": "high",
        "risk_level": "medium",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request"
        ],
    },
    {
        "event_name": "issues",
        "permission_required": "issues:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "issue_triage",
            "auto_label_by_content",
            "route_to_project_board",
        ],
        "local_artifacts_to_update": ["issue_queue", "operating_picture"],
        "followup_api_reads": [
            "get_issue_details",
            "get_issue_comments",
            "get_issue_timeline",
        ],
        "possible_mutations": ["add_labels", "assign_to_user", "add_to_project"],
        "dedupe_key": "repository_id+issue_number+action",
        "replay_strategy": "fetch current issue state; skip duplicates",
        "webhook_signature_required": True,
        "queue_strategy": "standard_queue_with_priority",
        "telemetry_value": "high",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#issues"
        ],
    },
    {
        "event_name": "pull_request_review",
        "permission_required": "pull_requests:read",
        "payload_sensitivity": "high",
        "useful_relay_reactions": [
            "update_pr_merge_readiness",
            "track_review_approval_status",
            "notify_author",
        ],
        "local_artifacts_to_update": ["pr_queue", "review_tracker"],
        "followup_api_reads": ["get_pr_reviews", "get_pr_status"],
        "possible_mutations": ["auto_merge_if_approved_and_checks_pass"],
        "dedupe_key": "pr_number+review_id",
        "replay_strategy": "compare review state with stored state",
        "webhook_signature_required": True,
        "queue_strategy": "priority_immediate",
        "telemetry_value": "high",
        "risk_level": "medium",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review"
        ],
    },
    {
        "event_name": "code_scanning_alert",
        "permission_required": "security_events:read",
        "payload_sensitivity": "critical",
        "useful_relay_reactions": [
            "triage_alert",
            "group_alert_with_existing_patch_candidates",
            "update_security_queue",
        ],
        "local_artifacts_to_update": ["security_queue", "operating_picture"],
        "followup_api_reads": ["get_alert_details", "get_alert_instances"],
        "possible_mutations": ["create_fix_pr", "dismiss_false_positive_with_evidence"],
        "dedupe_key": "repository_id+alert_number",
        "replay_strategy": "fetch alert state; process only if changed",
        "webhook_signature_required": True,
        "queue_strategy": "priority_critical_immediate",
        "telemetry_value": "high",
        "risk_level": "high",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#code_scanning_alert"
        ],
    },
    {
        "event_name": "secret_scanning_alert",
        "permission_required": "security_events:read",
        "payload_sensitivity": "critical",
        "useful_relay_reactions": [
            "log_alert_without_secret_value",
            "notify_maintainer",
            "track_revocation_status",
        ],
        "local_artifacts_to_update": ["security_queue", "secret_boundary_ledger"],
        "followup_api_reads": ["get_alert_details", "get_alert_locations"],
        "possible_mutations": [],
        "dedupe_key": "repository_id+alert_number",
        "replay_strategy": "fetch alert state; log but never store payload details",
        "webhook_signature_required": True,
        "queue_strategy": "immediate_log_only",
        "telemetry_value": "high",
        "risk_level": "restricted",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#secret_scanning_alert"
        ],
    },
    {
        "event_name": "dependabot_alert",
        "permission_required": "dependabot_alerts:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "update_dependency_queue",
            "auto_create_dependency_update_pr",
            "track_fix_timeline",
        ],
        "local_artifacts_to_update": ["dependency_queue", "operating_picture"],
        "followup_api_reads": ["get_alert_details", "get_dependabot_updates"],
        "possible_mutations": ["dismiss_with_fix_evidence", "create_update_pr"],
        "dedupe_key": "repository_id+alert_number",
        "replay_strategy": "fetch alert state; process changed alerts",
        "webhook_signature_required": True,
        "queue_strategy": "batch_hourly",
        "telemetry_value": "medium",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#dependabot_alert"
        ],
    },
    {
        "event_name": "workflow_run",
        "permission_required": "actions:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "ci_health_update",
            "failure_diagnosis",
            "auto_rerun_flaky_tests",
        ],
        "local_artifacts_to_update": ["ci_health_index", "operating_picture"],
        "followup_api_reads": ["get_workflow_run_logs", "get_workflow_jobs"],
        "possible_mutations": [
            "rerun_workflow_if_flaky",
            "cancel_run_if_security_issue",
        ],
        "dedupe_key": "repository_id+run_id",
        "replay_strategy": "check run status; skip completed runs",
        "webhook_signature_required": True,
        "queue_strategy": "standard_event_queue",
        "telemetry_value": "high",
        "risk_level": "medium",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run"
        ],
    },
    {
        "event_name": "check_run",
        "permission_required": "checks:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "aggregate_ci_status",
            "track_check_history",
            "detect_check_regression",
        ],
        "local_artifacts_to_update": ["ci_health_index", "check_history"],
        "followup_api_reads": ["get_check_run_details", "get_check_run_annotations"],
        "possible_mutations": ["rerequest_check_suite"],
        "dedupe_key": "repository_id+check_run_id",
        "replay_strategy": "compare check status with stored state",
        "webhook_signature_required": True,
        "queue_strategy": "batch_by_repo",
        "telemetry_value": "medium",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run"
        ],
    },
    {
        "event_name": "release",
        "permission_required": "contents:read",
        "payload_sensitivity": "low",
        "useful_relay_reactions": [
            "update_release_inventory",
            "validate_release_vs_evidence",
            "trigger_docs_site_update",
        ],
        "local_artifacts_to_update": ["release_index", "operating_picture"],
        "followup_api_reads": ["get_release_details", "get_release_assets"],
        "possible_mutations": ["update_docs_site_for_release", "notify_subscribers"],
        "dedupe_key": "repository_id+release_id",
        "replay_strategy": "compare release state; skip duplicates",
        "webhook_signature_required": True,
        "queue_strategy": "standard_queue",
        "telemetry_value": "high",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#release"
        ],
    },
    {
        "event_name": "deployment_status",
        "permission_required": "deployments:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "track_deployment_history",
            "detect_deployment_failures",
            "update_environment_status",
        ],
        "local_artifacts_to_update": ["deployment_index", "operating_picture"],
        "followup_api_reads": ["get_deployment_details", "get_environment_details"],
        "possible_mutations": ["rollback_deployment_if_failure_detected"],
        "dedupe_key": "repository_id+deployment_id+status",
        "replay_strategy": "compare status with stored state",
        "webhook_signature_required": True,
        "queue_strategy": "immediate_processing",
        "telemetry_value": "medium",
        "risk_level": "medium",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#deployment_status"
        ],
    },
    {
        "event_name": "page_build",
        "permission_required": "pages:read",
        "payload_sensitivity": "low",
        "useful_relay_reactions": [
            "verify_pages_build_status",
            "log_build_error_for_diagnosis",
            "trigger_retry_if_transient",
        ],
        "local_artifacts_to_update": ["pages_build_history", "operating_picture"],
        "followup_api_reads": ["get_pages_build_details", "get_pages_status"],
        "possible_mutations": ["retrigger_build_if_error_transient"],
        "dedupe_key": "repository_id+build_id",
        "replay_strategy": "check build status; skip completed builds",
        "webhook_signature_required": True,
        "queue_strategy": "standard_queue",
        "telemetry_value": "medium",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#page_build"
        ],
    },
    {
        "event_name": "repository",
        "permission_required": "metadata:read",
        "payload_sensitivity": "low",
        "useful_relay_reactions": [
            "update_repo_metadata_cache",
            "detect_repo_visibility_change",
            "detect_archive_or_delete",
        ],
        "local_artifacts_to_update": ["repo_inventory", "operating_picture"],
        "followup_api_reads": ["get_repo_details", "list_repo_topics"],
        "possible_mutations": [],
        "dedupe_key": "repository_id+action",
        "replay_strategy": "fetch latest repo state; compare with cache",
        "webhook_signature_required": True,
        "queue_strategy": "batch_offline_reconciliation",
        "telemetry_value": "high",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository"
        ],
    },
    {
        "event_name": "membership",
        "permission_required": "members:read",
        "payload_sensitivity": "high",
        "useful_relay_reactions": [
            "update_org_access_posture",
            "detect_permission_changes",
            "audit_membership_changes",
        ],
        "local_artifacts_to_update": ["org_access_posture", "operating_picture"],
        "followup_api_reads": ["get_org_members", "get_team_members"],
        "possible_mutations": [],
        "dedupe_key": "organization_id+user_id+action",
        "replay_strategy": "fetch current membership; compare with stored",
        "webhook_signature_required": True,
        "queue_strategy": "batch_daily_reconciliation",
        "telemetry_value": "high",
        "risk_level": "high",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#membership"
        ],
    },
    {
        "event_name": "security_advisory",
        "permission_required": "security_events:read",
        "payload_sensitivity": "high",
        "useful_relay_reactions": [
            "track_advisory_lifecycle",
            "validate_advisory_vs_code_scanning",
            "update_security_posture",
        ],
        "local_artifacts_to_update": ["security_queue", "operating_picture"],
        "followup_api_reads": ["get_advisory_details", "get_advisory_cve"],
        "possible_mutations": [],
        "dedupe_key": "repository_id+advisory_id",
        "replay_strategy": "fetch advisory state; process changed advisories",
        "webhook_signature_required": True,
        "queue_strategy": "priority_immediate",
        "telemetry_value": "high",
        "risk_level": "high",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#security_advisory"
        ],
    },
    {
        "event_name": "discussion",
        "permission_required": "discussions:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "track_discussion_activity",
            "detect_unanswered_questions",
            "route_to_issue_if_actionable",
        ],
        "local_artifacts_to_update": ["discussion_tracker", "operating_picture"],
        "followup_api_reads": ["get_discussion_details", "get_discussion_comments"],
        "possible_mutations": ["mark_as_answered", "create_issue_from_discussion"],
        "dedupe_key": "repository_id+discussion_number",
        "replay_strategy": "compare discussion state with stored",
        "webhook_signature_required": True,
        "queue_strategy": "batch_hourly",
        "telemetry_value": "medium",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#discussion"
        ],
    },
    {
        "event_name": "star",
        "permission_required": "metadata:read",
        "payload_sensitivity": "low",
        "useful_relay_reactions": [
            "update_repo_popularity_metrics",
            "detect_viral_events",
        ],
        "local_artifacts_to_update": ["telemetry_index"],
        "followup_api_reads": [],
        "possible_mutations": [],
        "dedupe_key": "repository_id+user_id+action",
        "replay_strategy": "aggregate only; skip dedupe at scale",
        "webhook_signature_required": True,
        "queue_strategy": "aggregate_batch_hourly",
        "telemetry_value": "low",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#star"
        ],
    },
    {
        "event_name": "issues",
        "permission_required": "issues:read",
        "payload_sensitivity": "medium",
        "useful_relay_reactions": [
            "issue_triage",
            "auto_label_by_content",
            "route_to_project_board",
        ],
        "local_artifacts_to_update": ["issue_queue", "operating_picture"],
        "followup_api_reads": ["get_issue_details", "get_issue_comments"],
        "possible_mutations": ["add_labels", "assign_to_user"],
        "dedupe_key": "repository_id+issue_number+action",
        "replay_strategy": "fetch current issue state; skip duplicates",
        "webhook_signature_required": True,
        "queue_strategy": "standard_queue_with_priority",
        "telemetry_value": "high",
        "risk_level": "low",
        "source_docs_refs": [
            "https://docs.github.com/en/webhooks/webhook-events-and-payloads#issues"
        ],
    },
]

_PLATFORM_LIMITS = [
    {
        "limitation_id": "PLAT-001",
        "affected_surface": "installation_token_user_oauth_gap",
        "limitation_type": "requires_user_oauth",
        "description": "Some GitHub operations cannot be performed by installation tokens and require user-to-server OAuth (e.g., user-level profile updates, starring repos, following users)",
        "source_docs_refs": [
            "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/about-authentication-with-a-github-app"
        ],
        "workaround": "Request user OAuth when needed; store user token alongside installation token",
        "product_implication": "Profile README updates and user-level operations require OAuth grant",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-002",
        "affected_surface": "installation_token_expiry",
        "limitation_type": "rate_limited",
        "description": "Installation access tokens expire after 1 hour; apps must regenerate tokens. Enterprise installation tokens cannot be scoped down.",
        "source_docs_refs": [
            "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app"
        ],
        "workaround": "Automatic token rotation with expiration tracking; cache token and regenerate when approaching expiry",
        "product_implication": "Long-running operations must handle token refresh transparently",
        "risk_if_ignored": "high",
    },
    {
        "limitation_id": "PLAT-003",
        "affected_surface": "secret_scanning_push_protection",
        "limitation_type": "enterprise_only",
        "description": "Push protection for custom patterns requires GitHub Advanced Security which is enterprise-only",
        "source_docs_refs": [
            "https://docs.github.com/en/enterprise-cloud@latest/code-security/secret-scanning"
        ],
        "workaround": "Use standard secret scanning; push protection limited to GHAS customers",
        "product_implication": "Secret boundary manager features may be tier-limited",
        "risk_if_ignored": "low",
    },
    {
        "limitation_id": "PLAT-004",
        "affected_surface": "actions_minutes_limits",
        "limitation_type": "plan_limited",
        "description": "GitHub Actions has free minute limits; Relay CI operations could exhaust minutes if not rate-limited",
        "source_docs_refs": [
            "https://docs.github.com/en/billing/managing-billing-for-github-actions"
        ],
        "workaround": "Track workflow minutes; add throttling; warn before exhaustion",
        "product_implication": "CI operator modes must include cost governance",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-005",
        "affected_surface": "rate_limits",
        "limitation_type": "rate_limited",
        "description": "GitHub API rate limits: 5000 requests/hour for authenticated users, lower for installation tokens per repository. Secondary rate limits may apply.",
        "source_docs_refs": [
            "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api"
        ],
        "workaround": "Implement rate limit tracking; backoff; batch where possible; use conditional requests",
        "product_implication": "Bulk operations must be throttled; observability on rate limit consumption required",
        "risk_if_ignored": "high",
    },
    {
        "limitation_id": "PLAT-006",
        "affected_surface": "graphql_complexity",
        "limitation_type": "rate_limited",
        "description": "GraphQL API has point-based rate limiting separate from REST; complex queries may exceed limits",
        "source_docs_refs": [
            "https://docs.github.com/en/graphql/overview/rate-limits-and-node-limits-for-the-graphql-api"
        ],
        "workaround": "Calculate query cost before execution; paginate; use REST fallback",
        "product_implication": "GraphQL-first features need cost estimation",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-007",
        "affected_surface": "webhook_payload_size",
        "limitation_type": "docs_ambiguous",
        "description": "Webhook payload maximum size is 25 MB; larger payloads may be truncated. Some large PR or push events may exceed this.",
        "source_docs_refs": ["https://docs.github.com/en/webhooks/about-webhooks"],
        "workaround": "Use webhook as trigger only; fetch full data via API",
        "product_implication": "Event-driven ops must re-fetch data via API, not rely on payload completeness",
        "risk_if_ignored": "low",
    },
    {
        "limitation_id": "PLAT-008",
        "affected_surface": "profile_readme_repo_discovery",
        "limitation_type": "API_unavailable",
        "description": "No API endpoint to discover a user's profile README repo name; convention is {username}/{username}",
        "source_docs_refs": [
            "https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-github-profile/managing-your-profile-readme"
        ],
        "workaround": "Hardcode convention as primary; fall back to user input",
        "product_implication": "Profile README automation may need repo name input",
        "risk_if_ignored": "low",
    },
    {
        "limitation_id": "PLAT-009",
        "affected_surface": "pages_custom_domain_management",
        "limitation_type": "API_unavailable",
        "description": "Some GitHub Pages custom domain operations require repository admin or are not available via API",
        "source_docs_refs": ["https://docs.github.com/en/rest/pages"],
        "workaround": "Document manual steps; leverage Pages API for core operations",
        "product_implication": "Full Pages automation may require manual intervention for domain setup",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-010",
        "affected_surface": "merge_queue_api",
        "limitation_type": "API_unavailable",
        "description": "Merge queue functionality is in limited beta and may not have stable API support for GitHub Apps",
        "source_docs_refs": [
            "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue"
        ],
        "workaround": "Watch for GA; use PR merge API in the meantime",
        "product_implication": "Auto-merge pipeline may be less reliable until GA",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-011",
        "affected_surface": "projects_v2_api",
        "limitation_type": "docs_ambiguous",
        "description": "Projects v2 API is still evolving; some operations may be GraphQL-only or have limited App support",
        "source_docs_refs": [
            "https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-projects"
        ],
        "workaround": "Use GraphQL API for Projects v2; test permission compatibility",
        "product_implication": "Project board automation may need workarounds",
        "risk_if_ignored": "low",
    },
    {
        "limitation_id": "PLAT-012",
        "affected_surface": "audit_log_api",
        "limitation_type": "enterprise_only",
        "description": "Organization audit log API requires GitHub Enterprise; not available on free/team plans",
        "source_docs_refs": [
            "https://docs.github.com/en/rest/orgs/orgs#get-the-audit-log-for-an-organization"
        ],
        "workaround": "Simulate audit trail from webhook events for non-enterprise users",
        "product_implication": "Audit features enterprise-gated",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-013",
        "affected_surface": "package_publishing",
        "limitation_type": "permission_unclear",
        "description": "GitHub Packages publishing via GitHub Apps may require additional write:packages permission which is separate from repo permissions",
        "source_docs_refs": ["https://docs.github.com/en/rest/packages"],
        "workaround": "Request write:packages permission explicitly; test package registration flow",
        "product_implication": "Package release operator needs explicit package permission",
        "risk_if_ignored": "medium",
    },
    {
        "limitation_id": "PLAT-014",
        "affected_surface": "issue_forms_beta",
        "limitation_type": "docs_ambiguous",
        "description": "Issue forms (YAML-defined templates) are partially supported through the contents API but not via dedicated API",
        "source_docs_refs": [
            "https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests"
        ],
        "workaround": "Manage issue form YAML files via Contents API",
        "product_implication": "Issue template management works through file API",
        "risk_if_ignored": "low",
    },
]

_ROADMAP = [
    {
        "phase_id": "phase_0",
        "goal": "Research siphon: build carte blanche research artifacts documenting maximum integration surface",
        "included_lanes": [
            "research_artifact_generation",
            "permission_value_matrix",
            "surface_lane_inventory",
            "mutation_catalog",
            "webhook_event_matrix",
            "platform_limits_registry",
        ],
        "excluded_lanes": [
            "all_mutation_lanes",
            "all_live_api_calls",
            "all_webhook_subscriptions",
        ],
        "required_permissions": ["metadata:read"],
        "required_artifacts": ["all_8_carte_blanche_artifacts"],
        "required_tests": ["governance_artifact_tests", "adversarial_redaction_tests"],
        "required_UI": "none",
        "mutation_policy": "no_remote_mutation",
        "telemetry_value": "high_for_research_governance",
        "release_gate": "all_artifacts_schema_valid_and_redaction_clean",
        "success_definition": "Schema-governed research substrate showing how to use every meaningful GitHub permission to its fullest product value",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_1",
        "goal": "Public surface program: audit, maintain, and publish all public repository surfaces",
        "included_lanes": [
            "profile_readme_maintainer",
            "project_readme_maintainer",
            "repo_metadata_auditor",
            "repo_topics_manager",
            "community_health_maintainer",
            "badge_status_block_manager",
            "surface_audit_runner",
        ],
        "excluded_lanes": [
            "mutation_lanes_except_content_write",
            "issue_pr_management",
            "security_queue_management",
            "ci_operations",
        ],
        "required_permissions": [
            "contents:read",
            "contents:write",
            "metadata:read",
            "administration:write",
        ],
        "required_artifacts": [
            "operating_picture",
            "surface_audit",
            "evidence_backed_claims_index",
            "surface_packets",
        ],
        "required_tests": [
            "integration_public_surface",
            "governance_surface_audit",
            "adversarial_content_injection",
        ],
        "required_UI": "surface_dashboard_chips",
        "mutation_policy": "approval_required_for_all_writes; dry_run_preview_mandatory",
        "telemetry_value": "high_for_developer_presence",
        "release_gate": "public_surface_audit_clean_and_claims_index_ready",
        "success_definition": "Relay can audit, propose, and publish updates to all public repository surfaces with evidence-backed claims",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_2",
        "goal": "Security queue manager: full security alert lifecycle management",
        "included_lanes": [
            "code_scanning_alert_triage",
            "secret_scanning_boundary_manager",
            "dependabot_alert_manager",
            "security_advisory_draft_assistant",
            "security_policy_maintainer",
            "codeql_config_manager",
            "dependabot_config_manager",
        ],
        "excluded_lanes": [
            "auto_dismiss_without_fix",
            "auto_merge_security_fixes",
            "org_level_security",
        ],
        "required_permissions": [
            "security_events:read",
            "security_events:write",
            "dependabot_alerts:read",
            "dependabot_alerts:write",
            "contents:read",
            "contents:write",
        ],
        "required_artifacts": [
            "security_intake",
            "security_queue",
            "patch_candidate_groups",
            "security_packet_runner_plan",
            "security_packet_execution",
        ],
        "required_tests": [
            "integration_security_intake",
            "governance_security_packets",
            "adversarial_alert_injection",
        ],
        "required_UI": "security_queue_dashboard",
        "mutation_policy": "alert_dismissal_requires_evidence; fix_pr_creation_requires_approval; never_dismiss_without_linked_fix",
        "telemetry_value": "high_for_security_posture",
        "release_gate": "security_queue_burn_down_demonstrated_on_test_repo",
        "success_definition": "Relay maintains a healthy security queue with evidence-backed dismissals and fix proposals",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_3",
        "goal": "Issue and PR operator: triage issues, manage PR lifecycle, evidence-backed proposals",
        "included_lanes": [
            "issue_triage_manager",
            "issue_auto_labeler",
            "issue_project_router",
            "pr_review_copilot",
            "evidence_backed_pr_creator",
            "stale_issue_cleaner",
            "stale_pr_manager",
        ],
        "excluded_lanes": [
            "auto_merge_without_approval",
            "auto_close_without_review",
            "pr_body_content_reading_without_opt_in",
        ],
        "required_permissions": [
            "issues:read",
            "issues:write",
            "pull_requests:read",
            "pull_requests:write",
            "contents:write",
        ],
        "required_artifacts": [
            "issue_queue",
            "pr_queue",
            "evidence_backed_claims_index",
            "operating_picture",
        ],
        "required_tests": [
            "integration_issue_triage",
            "integration_pr_workflow",
            "governance_pr_receipts",
            "adversarial_pr_injection",
        ],
        "required_UI": "issue_pr_dashboard",
        "mutation_policy": "label_assign_auto_allowed; create_requires_evidence; merge_requires_explicit_approval",
        "telemetry_value": "high_for_developer_productivity",
        "release_gate": "issue_inbox_zero_and_evidence_backed_pr_opened_on_test_repo",
        "success_definition": "Relay reduces issue backlog and creates evidence-backed PRs that reviewers can trust",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_4",
        "goal": "CI/Actions operator: workflow health, dispatch, failure diagnosis, configuration management",
        "included_lanes": [
            "ci_health_monitor",
            "workflow_dispatch_manager",
            "ci_failure_diagnosis",
            "workflow_config_auditor",
            "ci_cost_governor",
        ],
        "excluded_lanes": [
            "auto_edit_workflow_without_review",
            "exhausting_ci_minutes",
            "secrets_management",
        ],
        "required_permissions": ["actions:read", "actions:write", "contents:read"],
        "required_artifacts": [
            "ci_health_index",
            "actions_queue",
            "workflow_config_audit_report",
        ],
        "required_tests": [
            "integration_ci_health",
            "governance_workflow_receipts",
            "adversarial_ci_injection",
        ],
        "required_UI": "ci_dashboard",
        "mutation_policy": "rerun_flaky_allowed; dispatch_requires_approval; workflow_file_edit_requires_approval_and_contents_permission",
        "telemetry_value": "high_for_ci_visibility",
        "release_gate": "ci_health_dashboard_populated_from_test_repo",
        "success_definition": "Relay monitors CI health across repos and can diagnose and propose fixes for common failures",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_5",
        "goal": "Release and Pages operator: automated release management and docs site publishing",
        "included_lanes": [
            "release_manager",
            "release_notes_generator",
            "changelog_maintainer",
            "docs_site_publisher",
            "deployment_status_monitor",
            "environment_health_monitor",
        ],
        "excluded_lanes": [
            "auto_publish_without_review",
            "custom_domain_setup",
            "delete_releases",
        ],
        "required_permissions": [
            "contents:write",
            "pages:read",
            "pages:write",
            "deployments:read",
            "deployments:write",
        ],
        "required_artifacts": [
            "release_index",
            "changelog",
            "docs_build_report",
            "release_receipts",
        ],
        "required_tests": [
            "integration_release_workflow",
            "integration_pages_publish",
            "governance_release_receipts",
        ],
        "required_UI": "release_dashboard_and_pages_preview",
        "mutation_policy": "release_draft_auto_prepared; publish_requires_approval; pages_publish_requires_build_pass_and_approval",
        "telemetry_value": "high_for_release_automation",
        "release_gate": "evidence_backed_release_created_and_docs_site_published_on_test_repo",
        "success_definition": "Relay manages the release train from draft to publish, keeping changelog and docs site in sync",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_6",
        "goal": "Repo and org hygiene operator: branch protection, rulesets, collaborators, org membership audit",
        "included_lanes": [
            "branch_protection_auditor",
            "ruleset_compliance_checker",
            "collaborator_access_auditor",
            "deploy_key_auditor",
            "org_membership_auditor",
            "team_access_review",
            "stale_branch_detector",
        ],
        "excluded_lanes": [
            "auto_apply_protection_changes",
            "auto_remove_collaborators",
            "auto_modify_org_membership",
        ],
        "required_permissions": ["administration:read", "members:read"],
        "required_artifacts": [
            "org_access_posture",
            "branch_protection_report",
            "ruleset_compliance_report",
            "access_review_report",
        ],
        "required_tests": [
            "integration_repo_hygiene",
            "integration_org_audit",
            "governance_access_receipts",
        ],
        "required_UI": "hygiene_dashboard",
        "mutation_policy": "read_only_by_default; proposals_only; no_auto_apply",
        "telemetry_value": "medium_for_org_governance",
        "release_gate": "org_access_posture_and_repo_hygiene_reports_generated",
        "success_definition": "Relay provides visibility into repo and org health without making changes",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_7",
        "goal": "Event-driven GitHub ops: webhook observer, event correlation, telemetry pipeline",
        "included_lanes": [
            "webhook_event_observer",
            "event_replay_reconciliation",
            "telemetry_insights_operator",
            "traffic_analytics_dashboard",
            "multi_repo_correlation_engine",
        ],
        "excluded_lanes": [
            "auto_generated_commits_from_events",
            "event_based_mutation_without_approval",
        ],
        "required_permissions": ["webhooks:read", "metadata:read"],
        "required_artifacts": [
            "webhook_event_envelope_log",
            "telemetry_index",
            "cross_repo_correlation_index",
        ],
        "required_tests": [
            "integration_webhook_events",
            "governance_event_receipts",
            "adversarial_webhook_injection",
        ],
        "required_UI": "event_observer_dashboard",
        "mutation_policy": "observation_only; no_mutation_from_events",
        "telemetry_value": "high_for_platform_intelligence",
        "release_gate": "webhook_events_observed_and_correlated_on_test_repo",
        "success_definition": "Relay turns GitHub events into an inspectable operating substrate",
        "remaining_seams": [],
    },
    {
        "phase_id": "phase_8",
        "goal": "Multi-repo developer chief of staff: full GitHub operating layer across all repos and orgs",
        "included_lanes": [
            "all_previous_phase_lanes",
            "multi_repo_orchestration",
            "cross_repo_release_sync",
            "org_wide_security_posture",
            "developer_portfolio_dashboard",
            "council_adversarial_review",
        ],
        "excluded_lanes": ["unreviewed_mutations", "org_settings_changes"],
        "required_permissions": [
            "all_read_permissions",
            "all_approved_write_permissions",
        ],
        "required_artifacts": [
            "all_artifact_types",
            "multi_repo_operating_picture",
            "developer_portfolio_index",
        ],
        "required_tests": ["full_integration_suite", "cross_repo_orchestration_tests"],
        "required_UI": "chief_of_staff_dashboard",
        "mutation_policy": "full_governance_with_approval_chains_and_receipts",
        "telemetry_value": "high_for_full_product",
        "release_gate": "all_test_repos_have_healthy_operating_pictures_and_security_queues",
        "success_definition": "Relay is the governed GitHub chief-of-staff: repos are healthy, surfaces are current, security queues move, CI is visible, releases flow, and evidence backs every claim",
        "remaining_seams": [],
    },
]

_COMPETITIVE = [
    {
        "feature_id": "public_surface_maintainer",
        "product_value": "high",
        "trust_requirement": "low",
        "viral_potential": "high",
        "complexity": "low",
        "risk": "low",
        "recommended_phase": "phase_1",
        "reason": "Immediately useful; visible proof on profile; low risk; high viral potential",
    },
    {
        "feature_id": "issue_triage_inbox_zero",
        "product_value": "high",
        "trust_requirement": "low",
        "viral_potential": "medium",
        "complexity": "medium",
        "risk": "low",
        "recommended_phase": "phase_3",
        "reason": "Solves universal maintainer pain; safe read+label operations first",
    },
    {
        "feature_id": "evidence_backed_pr",
        "product_value": "high",
        "trust_requirement": "high",
        "viral_potential": "high",
        "complexity": "medium",
        "risk": "medium",
        "recommended_phase": "phase_3",
        "reason": "Most ambitious visible feature; requires strong governance; builds trust over time",
    },
    {
        "feature_id": "security_queue_burn_down",
        "product_value": "high",
        "trust_requirement": "medium",
        "viral_potential": "medium",
        "complexity": "medium",
        "risk": "medium",
        "recommended_phase": "phase_2",
        "reason": "Critical for enterprise credibility; alert management is table-stakes security posture",
    },
    {
        "feature_id": "dependabot_manager",
        "product_value": "medium",
        "trust_requirement": "low",
        "viral_potential": "low",
        "complexity": "low",
        "risk": "low",
        "recommended_phase": "phase_2",
        "reason": "Obvious automation; low risk; builds supply chain security story",
    },
    {
        "feature_id": "ci_actions_operator",
        "product_value": "high",
        "trust_requirement": "medium",
        "viral_potential": "medium",
        "complexity": "high",
        "risk": "medium",
        "recommended_phase": "phase_4",
        "reason": "Powerful for teams; high complexity; CI ecosystem deep understanding needed",
    },
    {
        "feature_id": "release_manager",
        "product_value": "high",
        "trust_requirement": "high",
        "viral_potential": "medium",
        "complexity": "medium",
        "risk": "high",
        "recommended_phase": "phase_5",
        "reason": "High value but high risk; releases are irreversible; governance paramount",
    },
    {
        "feature_id": "docs_site_publisher",
        "product_value": "medium",
        "trust_requirement": "medium",
        "viral_potential": "medium",
        "complexity": "medium",
        "risk": "low",
        "recommended_phase": "phase_5",
        "reason": "Visible proof of automation; safe because previewable; builds integrated experience",
    },
    {
        "feature_id": "org_hygiene_operator",
        "product_value": "medium",
        "trust_requirement": "extreme",
        "viral_potential": "low",
        "complexity": "medium",
        "risk": "high",
        "recommended_phase": "phase_6",
        "reason": "Enterprise-targeted; requires org admin trust; read-only first",
    },
    {
        "feature_id": "multi_repo_chief_of_staff",
        "product_value": "high",
        "trust_requirement": "extreme",
        "viral_potential": "high",
        "complexity": "high",
        "risk": "high",
        "recommended_phase": "phase_8",
        "reason": "Ultimate product; requires proven trust track record across all phases",
    },
    {
        "feature_id": "profile_portfolio_maintainer",
        "product_value": "high",
        "trust_requirement": "low",
        "viral_potential": "high",
        "complexity": "low",
        "risk": "low",
        "recommended_phase": "phase_1",
        "reason": "Immediate personal value; visible on GitHub profile; low risk; high viral sharing",
    },
    {
        "feature_id": "community_health_maintainer",
        "product_value": "medium",
        "trust_requirement": "low",
        "viral_potential": "low",
        "complexity": "low",
        "risk": "low",
        "recommended_phase": "phase_1",
        "reason": "Table-stakes open source hygiene; safe file updates; low risk",
    },
    {
        "feature_id": "webhook_event_observer",
        "product_value": "high",
        "trust_requirement": "medium",
        "viral_potential": "low",
        "complexity": "high",
        "risk": "medium",
        "recommended_phase": "phase_7",
        "reason": "Backend infrastructure; not user-visible directly; enables reactive features",
    },
]

_DATA_MODEL = [
    {
        "artifact_id": "GitHubInstallationSnapshot",
        "purpose": "Point-in-time snapshot of a GitHub App installation: repos, permissions, token state",
        "canonical_path_suggestion": "docs/json/governance/github_installation_snapshot_v1.v1.json",
        "schema_needed": True,
        "source_inputs": [
            "installation_token_exchange_response",
            "list_accessible_repos_response",
        ],
        "downstream_consumers": [
            "operating_picture",
            "permission_ledger",
            "rate_limit_ledger",
        ],
        "content_light_constraints": "hash installation_id, repo names, token hash; never raw token or private key",
        "mutation_status_fields": ["remote_mutation: false", "local_mutation: false"],
    },
    {
        "artifact_id": "GitHubRepoOperatingPicture",
        "purpose": "Complete local view of a single repo: metadata, surfaces, issues, PRs, security, CI, releases",
        "canonical_path_suggestion": "already exists as github_operating_picture_v1",
        "schema_needed": True,
        "source_inputs": [
            "repo_metadata",
            "security_intake",
            "surface_audit",
            "mission_candidates",
            "packet_runner_plan",
        ],
        "downstream_consumers": ["provider_registry", "release_gate", "dashboard"],
        "content_light_constraints": "all identifiers hashed; no file contents, patches, diffs, code snippets",
        "mutation_status_fields": ["remote_mutation: false", "local_mutation: false"],
    },
    {
        "artifact_id": "GitHubSecurityQueue",
        "purpose": "Normalized security alert queue across code scanning, secret scanning, dependabot",
        "canonical_path_suggestion": "already exists via security_intake_result",
        "schema_needed": True,
        "source_inputs": [
            "code_scanning_alerts",
            "secret_scanning_alerts",
            "dependabot_alerts",
        ],
        "downstream_consumers": ["security_packet_runner", "dashboard"],
        "content_light_constraints": "alert metadata only; never alert code snippets, secret values, or file locations",
        "mutation_status_fields": ["dismissed_by", "dismissal_evidence_hash"],
    },
    {
        "artifact_id": "GitHubMutationReceipt",
        "purpose": "Governed receipt for every remote mutation performed by Relay",
        "canonical_path_suggestion": "already exists via github_provider_operation_receipt",
        "schema_needed": True,
        "source_inputs": [
            "mutation_request",
            "mutation_response",
            "preflight_artifacts",
            "approval_chain",
        ],
        "downstream_consumers": ["audit_log", "evidence_ledger"],
        "content_light_constraints": "mutation description hash; before/after SHA; never raw response body",
        "mutation_status_fields": [
            "mutation_id",
            "status",
            "before_sha",
            "after_sha",
            "approval_chain_hashes",
        ],
    },
    {
        "artifact_id": "GitHubWebhookEventEnvelope",
        "purpose": "Content-light wrapper for received webhook events with signature validation metadata",
        "canonical_path_suggestion": ".build/rig-relay/evidence/webhook_events.jsonl",
        "schema_needed": True,
        "source_inputs": ["webhook_payload", "signature_header", "event_type_header"],
        "downstream_consumers": ["event_observer", "telemetry_pipeline"],
        "content_light_constraints": "event type, action, resource IDs hashed; NEVER raw payload body; NEVER secret values or PII from payloads",
        "mutation_status_fields": ["signature_validated", "replayed", "processed"],
    },
    {
        "artifact_id": "GitHubPermissionLedger",
        "purpose": "Ledger of all permission grants, token scopes, and permission posture over time",
        "canonical_path_suggestion": "docs/json/governance/github_permission_ledger_v1.v1.jsonl",
        "schema_needed": True,
        "source_inputs": [
            "installation_token_permissions",
            "app_permission_grants",
            "token_narrowing_requests",
        ],
        "downstream_consumers": [
            "operating_picture",
            "permission_posture_report",
            "release_gate",
        ],
        "content_light_constraints": "permission names and levels as strings; never token values or private key references",
        "mutation_status_fields": ["grant_id", "grant_status", "scope_hash"],
    },
    {
        "artifact_id": "GitHubRateLimitLedger",
        "purpose": "Track rate limit consumption, remaining budget, and throttling events",
        "canonical_path_suggestion": ".build/rig-relay/evidence/rate_limit_ledger.jsonl",
        "schema_needed": True,
        "source_inputs": ["x-ratelimit-remaining headers", "x-ratelimit-reset headers"],
        "downstream_consumers": ["throttle_controller", "telemetry_dashboard"],
        "content_light_constraints": "rate limit counts only; never API key or token",
        "mutation_status_fields": [
            "limit_category",
            "remaining",
            "reset_at",
            "throttled",
        ],
    },
    {
        "artifact_id": "GitHubTelemetryEvent",
        "purpose": "Standardized telemetry event for all GitHub provider activity",
        "canonical_path_suggestion": "already exists as rig.relay.github.* events",
        "schema_needed": True,
        "source_inputs": [
            "operation_receipts",
            "webhook_envelopes",
            "mutation_receipts",
        ],
        "downstream_consumers": ["analytics_duckdb", "dashboard", "telemetry_pipeline"],
        "content_light_constraints": "event names, hashes, counts; NEVER raw API bodies, file contents, patches, secrets",
        "mutation_status_fields": ["event_name", "event_sha256", "artifact_hashes"],
    },
]


def _build_main_artifact(
    gen_at: str, branch: str | None, head: str | None
) -> dict[str, Any]:
    return {
        "schema_version": "rig.github.carte_blanche_research.v1",
        "generated_at": gen_at,
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "research_scope": "Maximum practical GitHub App permissions and user trust (carte blanche). Maps every meaningful GitHub permission, surface, mutation, webhook event, product mode, user journey, platform limit, and roadmap phase to Relay product value.",
        "assumption": "User intentionally grants Rig Relay full GitHub App permissions, read/write access where GitHub permits, webhook access, repository access, organization access where available, and full operational trust.",
        "official_docs_refs": [
            "https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps",
            "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/about-authentication-with-a-github-app",
            "https://docs.github.com/en/rest",
            "https://docs.github.com/en/graphql",
            "https://docs.github.com/en/webhooks",
            "https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/choosing-permissions-for-a-github-app",
            "https://docs.github.com/en/rest/overview/endpoints-available-for-github-app-installation-access-tokens",
            "https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions",
        ],
        "permission_count": len(_PERMISSIONS),
        "surface_lane_count": len(_SURFACES),
        "mutation_lane_count": len(_MUTATIONS),
        "webhook_event_count": len(_WEBHOOKS),
        "product_mode_count": 0,
        "user_journey_count": 0,
        "platform_limit_count": len(_PLATFORM_LIMITS),
        "roadmap_phase_count": len(_ROADMAP),
        "competitive_positioning": _COMPETITIVE,
        "artifacts_produced": [
            "docs/json/governance/github_carte_blanche_research_v1.v1.json",
            "docs/json/governance/github_carte_blanche_permission_value_matrix_v1.v1.json",
            "docs/json/governance/github_carte_blanche_surface_lane_matrix_v1.v1.json",
            "docs/json/governance/github_carte_blanche_endpoint_matrix_v1.v1.json",
            "docs/json/governance/github_carte_blanche_webhook_matrix_v1.v1.json",
            "docs/json/governance/github_carte_blanche_mutation_lanes_v1.v1.json",
            "docs/json/governance/github_carte_blanche_risk_register_v1.v1.json",
            "docs/json/governance/github_carte_blanche_product_roadmap_v1.v1.json",
        ],
        "source_artifacts_consulted": [
            "rig_relay/integrations/github_provider/ (all 20 files)",
            "docs/schemas/rig.github.*.schema.json",
            "docs/json/governance/github_*.json",
            "docs/json/integrations/github_app_integration_audit_v0.v1.json",
        ],
        "data_model_concepts": _DATA_MODEL,
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_FIELDS),
        },
        "summary": {
            "total_permissions_mapped": len(_PERMISSIONS),
            "total_surface_lanes": len(_SURFACES),
            "total_mutation_lanes": len(_MUTATIONS),
            "total_webhook_events": len(_WEBHOOKS),
            "total_product_modes": 0,
            "total_user_journeys": 0,
            "total_platform_limits": len(_PLATFORM_LIMITS),
            "total_roadmap_phases": len(_ROADMAP),
            "next_recommended_slice": "phase_1_public_surface_program",
        },
    }


def _build_matrix(
    version: str, items: list[dict[str, Any]], key: str, summary: dict[str, Any]
) -> dict[str, Any]:
    report = {
        "schema_version": version,
        "generated_at": _now_iso(),
        "content_light": True,
        "remote_mutation": False,
        f"total_{key}": len(items),
        key: items,
        "summary": summary,
    }
    _assert_content_light(report)
    return report


def emit_all_artifacts(
    gen_at: str | None = None, output_dir: Path = OUTPUT_DIR
) -> list[Path]:
    gen_at = gen_at or _now_iso()
    branch, head = _load_git_metadata()
    paths: list[Path] = []

    # Main research artifact
    main = _build_main_artifact(gen_at, branch, head)
    p = output_dir / "github_carte_blanche_research_v1.v1.json"
    _write_json(p, main)
    paths.append(p)

    # Permission-value matrix
    perm_summary = {
        "high_value_permissions": sum(
            1 for x in _PERMISSIONS if x["maximum_product_value"] == "high"
        ),
        "mutation_permissions": sum(
            1 for x in _PERMISSIONS if x.get("enabled_write_lanes")
        ),
        "read_only_permissions": sum(
            1 for x in _PERMISSIONS if not x.get("enabled_write_lanes")
        ),
        "org_level_permissions": sum(
            1 for x in _PERMISSIONS if x["permission_scope"] == "organization"
        ),
    }
    p = output_dir / "github_carte_blanche_permission_value_matrix_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_permission_value_matrix.v1",
            _PERMISSIONS,
            "permissions",
            perm_summary,
        ),
    )
    paths.append(p)

    # Surface lane matrix
    surf_summary = {
        "read_surfaces": sum(
            1
            for x in _SURFACES
            if x.get("read_operations") and not x.get("write_operations")
        ),
        "write_surfaces": sum(
            1
            for x in _SURFACES
            if x.get("write_operations") and not x.get("read_operations")
        ),
        "read_write_surfaces": sum(
            1
            for x in _SURFACES
            if x.get("read_operations") and x.get("write_operations")
        ),
        "webhook_surfaces": sum(1 for x in _SURFACES if x.get("webhook_support")),
    }
    p = output_dir / "github_carte_blanche_surface_lane_matrix_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_surface_lane_matrix.v1",
            _SURFACES,
            "surfaces",
            surf_summary,
        ),
    )
    paths.append(p)

    # Endpoint matrix (derived from surfaces)
    endpoints = [
        {
            "endpoint_id": f"EP-{i:03d}",
            "method": "GET",
            "path_template": s.get("read_operations", [""])[0]
            if s.get("read_operations")
            else "N/A",
            "required_permission": (s.get("required_permissions") or [""])[0]
            if s.get("required_permissions")
            else "unknown",
            "operation_class": "read_only"
            if not s.get("write_operations")
            else "remote_mutation",
            "works_with_github_app": True,
            "works_with_installation_token": True,
            "requires_user_oauth": False,
            "plan_limited": bool(s.get("plan_limitations")),
            "relay_lane": s.get("human_name", ""),
            "official_docs_ref": "",
            "rate_limit_category": "core",
            "risk_level": s.get("risk_level", "low"),
        }
        for i, s in enumerate(_SURFACES)
    ]
    ep_summary = {
        "read_endpoints": len(endpoints),
        "write_endpoints": 0,
        "mutation_endpoints": 0,
        "webhook_endpoints": 0,
    }
    p = output_dir / "github_carte_blanche_endpoint_matrix_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_endpoint_matrix.v1",
            endpoints,
            "endpoints",
            ep_summary,
        ),
    )
    paths.append(p)

    # Webhook matrix
    wh_summary = {
        "high_value_events": sum(
            1 for x in _WEBHOOKS if x["telemetry_value"] == "high"
        ),
        "mutation_triggering_events": sum(
            1 for x in _WEBHOOKS if x.get("possible_mutations")
        ),
        "security_events": sum(
            1
            for x in _WEBHOOKS
            if x["event_name"]
            in {
                "code_scanning_alert",
                "secret_scanning_alert",
                "dependabot_alert",
                "security_advisory",
            }
        ),
        "ci_events": sum(
            1
            for x in _WEBHOOKS
            if x["event_name"] in {"workflow_run", "check_run", "check_suite"}
        ),
        "repo_events": sum(
            1
            for x in _WEBHOOKS
            if x["event_name"] in {"push", "repository", "release", "page_build"}
        ),
    }
    p = output_dir / "github_carte_blanche_webhook_matrix_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_webhook_matrix.v1",
            _WEBHOOKS,
            "events",
            wh_summary,
        ),
    )
    paths.append(p)

    # Mutation lanes
    mut_summary = {
        "disabled_count": sum(
            1 for x in _MUTATIONS if x["recommended_initial_state"] == "disabled"
        ),
        "dry_run_count": sum(
            1 for x in _MUTATIONS if x["recommended_initial_state"] == "dry_run"
        ),
        "approval_required_count": sum(
            1
            for x in _MUTATIONS
            if x["recommended_initial_state"] == "approval_required"
        ),
        "automatic_count": sum(
            1
            for x in _MUTATIONS
            if x["recommended_initial_state"] == "automatic_under_policy"
        ),
    }
    p = output_dir / "github_carte_blanche_mutation_lanes_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_mutation_lanes.v1",
            _MUTATIONS,
            "mutations",
            mut_summary,
        ),
    )
    paths.append(p)

    # Risk register
    risk_summary = {
        "api_unavailable": sum(
            1 for x in _PLATFORM_LIMITS if x["limitation_type"] == "API_unavailable"
        ),
        "requires_user_oauth": sum(
            1 for x in _PLATFORM_LIMITS if x["limitation_type"] == "requires_user_oauth"
        ),
        "plan_limited": sum(
            1 for x in _PLATFORM_LIMITS if x["limitation_type"] == "plan_limited"
        ),
        "rate_limited": sum(
            1 for x in _PLATFORM_LIMITS if x["limitation_type"] == "rate_limited"
        ),
        "app_not_supported": sum(
            1
            for x in _PLATFORM_LIMITS
            if x["limitation_type"] in {"app_not_supported", "permission_unclear"}
        ),
    }
    p = output_dir / "github_carte_blanche_risk_register_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_risk_register.v1",
            _PLATFORM_LIMITS,
            "limits",
            risk_summary,
        ),
    )
    paths.append(p)

    # Roadmap
    road_summary = {
        "current_phase": "phase_0",
        "next_phase": "phase_1",
        "total_lanes_across_phases": sum(
            len(p.get("included_lanes", [])) for p in _ROADMAP
        ),
    }
    p = output_dir / "github_carte_blanche_product_roadmap_v1.v1.json"
    _write_json(
        p,
        _build_matrix(
            "rig.github.carte_blanche_product_roadmap.v1",
            _ROADMAP,
            "phases",
            road_summary,
        ),
    )
    paths.append(p)

    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-carte-blanche-research",
        description="Emit GitHub carte blanche research artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for artifacts.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=None,
        help="Override generation timestamp.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print summary of emitted artifacts."
    )
    args = parser.parse_args(argv)

    paths = emit_all_artifacts(gen_at=args.generated_at_utc, output_dir=args.output_dir)

    if args.summary:
        print(f"Emitted {len(paths)} research artifacts to {args.output_dir}:")
        for p in paths:
            print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

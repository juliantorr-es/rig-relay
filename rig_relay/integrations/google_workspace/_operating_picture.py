"""Google Workspace operating picture — local, deterministic, content-light."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.google_workspace._redaction import (
    _FORBIDDEN_OUTPUT_FIELDS,
    _SECRET_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LIVE_AUTH_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "live_google_auth_result.v1.json"
)
_DEFAULT_SCOPE_MANIFEST_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "google_workspace_scope_manifest_v1.v1.json"
)
_DEFAULT_CAPABILITY_MANIFEST_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "google_workspace_capability_manifest.v1.json"
)
_DEFAULT_CONTRACT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "integrations"
    / "google_workspace_contract_v1.v1.json"
)
_DEFAULT_READ_INTAKE_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_read_intake_v1.v1.json"
)
_DEFAULT_OUTPUT_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "google_workspace_operating_picture_v1.v1.json"
)

_SOURCE_PATH_KEYS = (
    "live_auth_json",
    "scope_manifest_json",
    "capability_manifest_json",
    "contract_json",
    "read_intake_json",
)

_GOOGLE_SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ya29\.[a-zA-Z0-9\-_]+"),
    re.compile(r"1//[a-zA-Z0-9\-_]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
)

# restricted scopes that require security assessment
_RESTRICTED_SCOPE_PREFIXES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://mail.google.com/",
)

_SENSITIVE_SCOPE_PREFIXES = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/admin.directory",
    "https://www.googleapis.com/auth/chat",
)

_LEAST_PRIVILEGE_MAX_SCOPE_COUNT = 5


class GoogleWorkspaceOperatingPictureError(Exception):
    """Raised when provider artifacts cannot be combined into an operating picture."""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_text(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return text if text else default
    text = str(value).strip()
    return text if text else default


def _scope_sensitivity(scope: str) -> str:
    if any(scope.startswith(prefix) for prefix in _RESTRICTED_SCOPE_PREFIXES):
        return "restricted"
    if any(scope.startswith(prefix) for prefix in _SENSITIVE_SCOPE_PREFIXES):
        return "sensitive"
    return "non_sensitive"


def _live_auth_summary(data: dict[str, Any]) -> dict[str, Any]:
    config_summary = data.get("config_summary")
    if not isinstance(config_summary, dict):
        config_summary = {}
    live_results = data.get("live_results")
    if not isinstance(live_results, dict):
        live_results = {}
    return {
        "oauth_configured": bool(config_summary.get("oauth_configured")),
        "pkce_available": True,
        "token_present": bool(
            config_summary.get("token_hash") or live_results.get("token_hash")
        ),
        "token_hash_present": bool(
            config_summary.get("token_hash") or live_results.get("token_hash")
        ),
        "refresh_token_present": False,
        "granted_scope_count": 0,
        "requested_scope_count": 0,
        "missing_required_scopes": [],
        "restricted_scope_count": 0,
        "sensitive_scope_count": 0,
        "consent_mode": "unknown",
        "public_release_ready": False,
        "config_issues": [
            issue.get("kind")
            for issue in data.get("issues", [])
            if isinstance(issue, dict) and issue.get("kind")
        ],
    }


def _scope_manifest_summary(data: dict[str, Any]) -> dict[str, Any]:
    scopes_list = data.get("scopes")
    if not isinstance(scopes_list, list):
        scopes_list = []
    restricted = 0
    sensitive = 0
    non_sensitive = 0
    for scope in scopes_list:
        if not isinstance(scope, dict):
            continue
        sensitivity = _normalize_text(scope.get("sensitivity"), "unknown") or "unknown"
        if sensitivity == "restricted":
            restricted += 1
        elif sensitivity == "sensitive":
            sensitive += 1
        elif sensitivity == "non_sensitive":
            non_sensitive += 1
    return {
        "total_scopes": len(scopes_list),
        "restricted_scope_count": restricted,
        "sensitive_scope_count": sensitive,
        "non_sensitive_scope_count": non_sensitive,
        "scopes_requiring_security_assessment": sum(
            1
            for s in scopes_list
            if isinstance(s, dict) and s.get("requires_security_assessment")
        ),
    }


def _capability_manifest_summary(data: dict[str, Any]) -> dict[str, Any]:
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    read_only = 0
    mutation = 0
    requires_dwd = 0
    for cap in capabilities:
        if not isinstance(cap, dict):
            continue
        op_class = _normalize_text(cap.get("operation_class"), "")
        if op_class and "read" in op_class:
            read_only += 1
        elif op_class and "mutation" in op_class:
            mutation += 1
        if cap.get("requires_domain_wide_delegation"):
            requires_dwd += 1
    return {
        "total_capabilities": len(capabilities),
        "read_only_capabilities": read_only,
        "mutation_capabilities_refused": mutation,
        "domain_wide_delegation_capabilities": requires_dwd,
        "default_policy": data.get("default_policy", {}),
    }


def _contract_summary(data: dict[str, Any]) -> dict[str, Any]:
    scope_taxonomy = data.get("scope_taxonomy")
    if not isinstance(scope_taxonomy, dict):
        scope_taxonomy = {}
    restricted_policy = scope_taxonomy.get("restricted_scope_policy")
    delegation_policy = data.get("delegation_policy")
    return {
        "implementation_status": data.get("implementation_status"),
        "auth_modes_count": len(data.get("auth_modes", [])),
        "restricted_scope_policy_live_refused": bool(
            restricted_policy.get("live_refused")
            if isinstance(restricted_policy, dict)
            else True
        ),
        "domain_wide_delegation_refused": bool(
            delegation_policy.get("domain_wide_delegation_refused_in_v1")
            if isinstance(delegation_policy, dict)
            else True
        ),
        "deferred_work_count": len(data.get("deferred_work", [])),
    }


def _read_intake_summary(data: dict[str, Any]) -> dict[str, Any]:
    surfaces = data.get("surfaces")
    if not isinstance(surfaces, list):
        surfaces = []
    present = 0
    refused = 0
    not_implemented = 0
    for s in surfaces:
        if not isinstance(s, dict):
            continue
        status = s.get("status")
        if status == "present":
            present += 1
        elif status == "refused":
            refused += 1
        elif status == "not_implemented":
            not_implemented += 1
    return {
        "dry_run": data.get("dry_run"),
        "live": data.get("live"),
        "total_surfaces": len(surfaces),
        "present_surfaces": present,
        "refused_surfaces": refused,
        "not_implemented_surfaces": not_implemented,
    }


def _artifact_summary(artifact_id: str, data: dict[str, Any]) -> dict[str, Any]:
    summarizers = {
        "live_auth": _live_auth_summary,
        "scope_manifest": _scope_manifest_summary,
        "capability_manifest": _capability_manifest_summary,
        "contract": _contract_summary,
        "read_intake": _read_intake_summary,
    }
    summarizer = summarizers.get(artifact_id)
    if summarizer is None:
        return {}
    return summarizer(data)


def _load_artifact(
    artifact_id: str, path: Path, *, expected_schema_version: str | None = None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    descriptor: dict[str, Any] = {
        "artifact_id": artifact_id,
        "path": str(path),
        "present": False,
        "status": "missing",
        "artifact_hash": None,
        "schema_version": None,
        "summary": None,
    }
    if not path.exists():
        return descriptor, None

    raw = read_safe(path, raise_on_error=True)
    artifact_hash = _sha256_file(path)
    descriptor["present"] = True
    descriptor["artifact_hash"] = artifact_hash

    try:
        data = json.loads(raw.text)
    except json.JSONDecodeError as exc:
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "json_decode_error"
        descriptor["error"] = str(exc)
        return descriptor, None

    if not isinstance(data, dict):
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "invalid_root_type"
        return descriptor, None

    descriptor["content_hash"] = _sha256_text(_stable_json(data))
    schema_version = _normalize_text(data.get("schema_version"))
    descriptor["schema_version"] = schema_version
    if expected_schema_version and schema_version != expected_schema_version:
        descriptor["status"] = "invalid"
        descriptor["error_kind"] = "schema_version_mismatch"
        descriptor["summary"] = _artifact_summary(artifact_id, data)
        return descriptor, data

    descriptor["status"] = "present"
    descriptor["summary"] = _artifact_summary(artifact_id, data)
    return descriptor, data


def _load_git_metadata(repo_root: Path) -> tuple[str | None, str | None]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch or None, head or None
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _artifact_descriptor_map(
    descriptors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(descriptor.get("artifact_id")): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict) and descriptor.get("artifact_id")
    }


def _build_auth_summary(
    live_auth: dict[str, Any] | None,
    scope_manifest: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "oauth_configured": False,
        "pkce_available": True,
        "token_present": False,
        "token_hash_present": False,
        "refresh_token_present": False,
        "granted_scope_count": 0,
        "requested_scope_count": 0,
        "missing_required_scopes": [],
        "restricted_scope_count": 0,
        "sensitive_scope_count": 0,
        "consent_mode": "unknown",
        "public_release_ready": False,
    }

    if isinstance(live_auth, dict):
        config_summary = live_auth.get("config_summary")
        if not isinstance(config_summary, dict):
            config_summary = {}
        base["oauth_configured"] = bool(config_summary.get("oauth_configured"))
        base["token_hash_present"] = bool(
            config_summary.get("token_hash") or live_auth.get("token_hash")
        )
        base["consent_mode"] = "external"
        if config_summary.get("service_account_configured"):
            base["consent_mode"] = "internal"

    if isinstance(scope_manifest, dict):
        scopes = scope_manifest.get("scopes")
        if isinstance(scopes, list):
            base["requested_scope_count"] = len(scopes)
            for scope_obj in scopes:
                if not isinstance(scope_obj, dict):
                    continue
                sensitivity = (
                    _normalize_text(scope_obj.get("sensitivity"), "unknown")
                    or "unknown"
                )
                if sensitivity == "restricted":
                    base["restricted_scope_count"] += 1
                elif sensitivity == "sensitive":
                    base["sensitive_scope_count"] += 1

    if isinstance(contract, dict):
        scope_taxonomy = contract.get("scope_taxonomy")
        if isinstance(scope_taxonomy, dict):
            restricted_policy = scope_taxonomy.get("restricted_scope_policy")
            if isinstance(restricted_policy, dict) and restricted_policy.get(
                "live_refused"
            ):
                base["missing_required_scopes"].append(
                    "restricted_scopes_refused_for_live"
                )

    base["public_release_ready"] = False
    return base


def _build_surface_summary(
    live_auth: dict[str, Any] | None,
    capability_manifest: dict[str, Any] | None,
    read_intake: dict[str, Any] | None,
) -> dict[str, Any]:
    surfaces = {
        "gmail_profile": {
            "surface": "gmail_profile",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "gmail_metadata": {
            "surface": "gmail_metadata",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "calendar_list": {
            "surface": "calendar_list",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "calendar_events_readonly": {
            "surface": "calendar_events_readonly",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "drive_metadata": {
            "surface": "drive_metadata",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "tasks_readonly": {
            "surface": "tasks_readonly",
            "status": "not_implemented",
            "evidence_paths": [],
        },
        "contacts_people_readonly": {
            "surface": "contacts_people_readonly",
            "status": "not_implemented",
            "evidence_paths": [],
        },
    }

    capability_paths = [
        "docs/json/integrations/google_workspace_capability_manifest.v1.json"
    ]

    if isinstance(capability_manifest, dict):
        capabilities = capability_manifest.get("capabilities")
        if isinstance(capabilities, list):
            cap_map: dict[str, str] = {}
            for cap in capabilities:
                if not isinstance(cap, dict):
                    continue
                cap_id = str(cap.get("capability_id", ""))
                cap_map[cap_id] = cap.get("scope_sensitivity", "non_sensitive")

            # Surface from capability manifest
            if "google_workspace.gmail.profile.get" in cap_map:
                surfaces["gmail_profile"]["status"] = "missing"
                surfaces["gmail_profile"]["evidence_paths"] = list(capability_paths)
            if "google_workspace.gmail.labels.list" in cap_map:
                surfaces["gmail_metadata"]["status"] = "missing"
                surfaces["gmail_metadata"]["evidence_paths"] = list(capability_paths)
            if "google_workspace.calendar.calendarList.list" in cap_map:
                surfaces["calendar_list"]["status"] = "missing"
                surfaces["calendar_list"]["evidence_paths"] = list(capability_paths)
            if "google_workspace.drive.files.list" in cap_map:
                surfaces["drive_metadata"]["status"] = "missing"
                surfaces["drive_metadata"]["evidence_paths"] = list(capability_paths)
            if "google_workspace.tasks.tasklists.list" in cap_map:
                surfaces["tasks_readonly"]["status"] = "missing"
                surfaces["tasks_readonly"]["evidence_paths"] = list(capability_paths)
            if "google_workspace.contacts.list" in cap_map:
                surfaces["contacts_people_readonly"]["status"] = "missing"
                surfaces["contacts_people_readonly"]["evidence_paths"] = list(
                    capability_paths
                )

    # Read intake overrides if present
    if isinstance(read_intake, dict):
        intake_surfaces = read_intake.get("surfaces")
        intake_paths = ["docs/json/governance/google_workspace_read_intake_v1.v1.json"]
        if isinstance(intake_surfaces, list):
            for s in intake_surfaces:
                if not isinstance(s, dict):
                    continue
                surface_name = str(s.get("surface", ""))
                status = str(s.get("status", "not_implemented"))
                mapping = {
                    "gmail_profile": "gmail_profile",
                    "gmail_labels": "gmail_metadata",
                    "calendar_list": "calendar_list",
                    "drive_files": "drive_metadata",
                    "tasklists": "tasks_readonly",
                    "contacts": "contacts_people_readonly",
                }
                mapped = mapping.get(surface_name)
                if mapped and mapped in surfaces:
                    surfaces[mapped]["status"] = status
                    surfaces[mapped]["evidence_paths"] = list(intake_paths)

    return surfaces


def _build_scope_posture(
    auth_summary: dict[str, Any], contract: dict[str, Any] | None
) -> dict[str, Any]:
    restricted_scopes_refused = True
    if isinstance(contract, dict):
        scope_taxonomy = contract.get("scope_taxonomy")
        if isinstance(scope_taxonomy, dict):
            restricted_policy = scope_taxonomy.get("restricted_scope_policy")
            if isinstance(restricted_policy, dict):
                restricted_scopes_refused = bool(
                    restricted_policy.get("live_refused", True)
                )

    return {
        "least_privilege_ready": auth_summary["restricted_scope_count"] == 0
        and auth_summary["requested_scope_count"] <= _LEAST_PRIVILEGE_MAX_SCOPE_COUNT,
        "broad_local_dev_posture": auth_summary["requested_scope_count"]
        > _LEAST_PRIVILEGE_MAX_SCOPE_COUNT,
        "public_release_ready": False,
        "verification_required": auth_summary["restricted_scope_count"] > 0
        or auth_summary["sensitive_scope_count"] > 0,
        "restricted_scopes_refused_or_deferred": restricted_scopes_refused,
    }


def _build_refusals(
    auth_summary: dict[str, Any],
    surface_summary: dict[str, Any],
    contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    refusals: list[dict[str, Any]] = []

    if auth_summary["missing_required_scopes"]:
        refusals.append({
            "refusal_kind": "missing_scope",
            "status": "refused",
            "reason": f"Missing required scopes: {', '.join(auth_summary['missing_required_scopes'])}",
            "evidence_paths": [
                "docs/json/integrations/google_workspace_scope_manifest_v1.v1.json"
            ],
        })

    if auth_summary["restricted_scope_count"] > 0:
        refusals.append({
            "refusal_kind": "restricted_scope_unverified",
            "status": "refused",
            "reason": "Restricted scopes present and not verified for public release. Security assessment required.",
            "evidence_paths": [
                "docs/json/integrations/google_workspace_contract_v1.v1.json"
            ],
        })

    dwd_refused = True
    if isinstance(contract, dict):
        delegation_policy = contract.get("delegation_policy")
        if isinstance(delegation_policy, dict):
            dwd_refused = bool(
                delegation_policy.get("domain_wide_delegation_refused_in_v1", True)
            )
    if dwd_refused:
        refusals.append({
            "refusal_kind": "domain_wide_delegation_deferred",
            "status": "refused",
            "reason": "Domain-wide delegation deferred to a later lane. Requires super admin authorization.",
            "evidence_paths": [
                "docs/json/integrations/google_workspace_contract_v1.v1.json"
            ],
        })

    refusals.append({
        "refusal_kind": "service_account_key_management_external",
        "status": "refused",
        "reason": "Service account key management is external to Rig Relay. Keys stored in keychain only.",
        "evidence_paths": [],
    })

    return refusals


def _build_next_actions(
    auth_summary: dict[str, Any],
    surface_summary: dict[str, Any],
    scope_posture: dict[str, Any],
    read_intake_present: bool,
) -> list[str]:
    actions: list[str] = []

    if not auth_summary["oauth_configured"] and not auth_summary["token_hash_present"]:
        actions.append("configure_oauth")
    elif not read_intake_present:
        actions.append("run_dry_run")
        actions.append("run_live_read_intake")
    elif auth_summary["missing_required_scopes"]:
        actions.append("request_scope")
    elif auth_summary["restricted_scope_count"] > 0:
        actions.append("split_public_scope_profiles")

    if scope_posture["verification_required"]:
        if "request_scope" not in actions:
            actions.append("run_live_read_intake")

    if not actions:
        actions.append("no_action")

    result: list[str] = []
    for action in actions:
        if action not in result:
            result.append(action)
    return result


def _assert_content_light(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_OUTPUT_FIELDS:
                raise ValueError(
                    f"forbidden_key_detected: operating picture contains forbidden field '{key}'"
                )
            _assert_content_light(item)
    elif isinstance(value, list):
        for item in value:
            _assert_content_light(item)
    elif isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    "forbidden_secret_like_string_detected: operating picture contains secret-like content"
                )
        for pattern in _GOOGLE_SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(
                    f"forbidden_content_detected: operating picture contains '{pattern.pattern}'"
                )


def build_google_workspace_operating_picture(
    *,
    context: dict[str, Any],
    source_artifacts: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    generated_at_utc = context.get("generated_at_utc") or _now_iso()
    branch = context.get("branch")
    head = context.get("head")

    auth_summary = _build_auth_summary(
        artifacts.get("live_auth"),
        artifacts.get("scope_manifest"),
        artifacts.get("contract"),
    )
    surface_summary = _build_surface_summary(
        artifacts.get("live_auth"),
        artifacts.get("capability_manifest"),
        artifacts.get("read_intake"),
    )
    scope_posture = _build_scope_posture(auth_summary, artifacts.get("contract"))
    refusals = _build_refusals(auth_summary, surface_summary, artifacts.get("contract"))
    next_actions = _build_next_actions(
        auth_summary,
        surface_summary,
        scope_posture,
        artifacts.get("read_intake") is not None,
    )

    evidence_paths = [
        descriptor["path"]
        for descriptor in sorted(
            source_artifacts, key=lambda item: str(item["artifact_id"])
        )
        if descriptor.get("present")
        and isinstance(descriptor.get("path"), str)
        and descriptor["path"]
    ]

    present_surfaces = sum(
        1
        for s in surface_summary.values()
        if isinstance(s, dict) and s.get("status") == "present"
    )
    missing_or_refused = sum(
        1
        for s in surface_summary.values()
        if isinstance(s, dict)
        and s.get("status") in {"missing", "refused", "not_implemented"}
    )

    report: dict[str, Any] = {
        "schema_version": "rig.google_workspace.operating_picture.v1",
        "generated_at": generated_at_utc,
        "branch": branch,
        "head": head,
        "content_light": True,
        "remote_mutation": False,
        "source_artifacts": sorted(
            source_artifacts, key=lambda item: str(item["artifact_id"])
        ),
        "auth_summary": auth_summary,
        "surface_summary": surface_summary,
        "scope_posture": scope_posture,
        "refusals": refusals,
        "next_recommended_actions": next_actions,
        "evidence_paths": evidence_paths,
        "redaction_status": {
            "content_light": True,
            "forbidden_strings_present": False,
            "redaction_rule_count": len(_FORBIDDEN_OUTPUT_FIELDS),
            "checked_artifact_count": len(source_artifacts),
        },
        "remaining_seams": [
            "gmail message body read remains refused until restricted scope assessment complete",
            "drive file content ingestion deferred; metadata-only in v1",
            "domain-wide delegation remains deferred to future lane",
            "calendar event descriptions remain hashed/omitted in v1",
            "contacts details remain hashed in v1",
            "service account key management is external to Rig Relay",
            "live network calls gated by RIG_LIVE_AUTH_TESTS=1",
        ],
    }

    auth_health = "auth_unconfigured"
    if auth_summary["oauth_configured"] or auth_summary["token_hash_present"]:
        auth_health = "oauth_configured"
    if auth_summary["missing_required_scopes"]:
        auth_health = "auth_partial"

    surface_health = "all_missing"
    if present_surfaces > 0:
        surface_health = "some_present"
    if missing_or_refused > 0 and present_surfaces > 0:
        surface_health = "partial_refusal"

    report["summary"] = {
        "auth_health": auth_health,
        "surface_health": surface_health,
        "scope_posture_conservative": scope_posture[
            "restricted_scopes_refused_or_deferred"
        ],
        "next_recommended_action": (next_actions[0] if next_actions else "no_action"),
    }

    _assert_content_light(report)
    return report


def _source_paths_from_mapping(
    source_paths: dict[str, Path | str] | None,
) -> dict[str, Path | str]:
    if source_paths is None:
        return {}
    return {
        key: value
        for key, value in source_paths.items()
        if key in _SOURCE_PATH_KEYS and value is not None
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_google_workspace_operating_picture_from_paths(
    *,
    source_paths: dict[str, Path | str] | None = None,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    source_paths = _source_paths_from_mapping(source_paths)
    source_specs = [
        (
            "live_auth",
            Path(source_paths.get("live_auth_json", _DEFAULT_LIVE_AUTH_JSON)),
            "rig.google_workspace.live_auth_refusal.v1",
        ),
        (
            "scope_manifest",
            Path(source_paths.get("scope_manifest_json", _DEFAULT_SCOPE_MANIFEST_JSON)),
            "rig.google_workspace.scope_manifest.v1",
        ),
        (
            "capability_manifest",
            Path(
                source_paths.get(
                    "capability_manifest_json", _DEFAULT_CAPABILITY_MANIFEST_JSON
                )
            ),
            "rig.google_workspace.capability_manifest.v1",
        ),
        (
            "contract",
            Path(source_paths.get("contract_json", _DEFAULT_CONTRACT_JSON)),
            "rig.google_workspace.contract.v1",
        ),
        (
            "read_intake",
            Path(source_paths.get("read_intake_json", _DEFAULT_READ_INTAKE_JSON)),
            "rig.google_workspace.read_intake.v1",
        ),
    ]

    descriptors: list[dict[str, Any]] = []
    live_auth = None
    scope_manifest = None
    capability_manifest = None
    contract = None
    read_intake = None

    for artifact_id, path, schema_version in source_specs:
        descriptor, data = _load_artifact(
            artifact_id, path, expected_schema_version=schema_version
        )
        descriptors.append(descriptor)
        match artifact_id:
            case "live_auth":
                live_auth = data
            case "scope_manifest":
                scope_manifest = data
            case "capability_manifest":
                capability_manifest = data
            case "contract":
                contract = data
            case "read_intake":
                read_intake = data

    branch, head = _load_git_metadata(repo_root)
    report = build_google_workspace_operating_picture(
        context={"generated_at_utc": generated_at_utc, "branch": branch, "head": head},
        source_artifacts=descriptors,
        artifacts={
            "live_auth": live_auth,
            "scope_manifest": scope_manifest,
            "capability_manifest": capability_manifest,
            "contract": contract,
            "read_intake": read_intake,
        },
    )
    return report


def write_google_workspace_operating_picture(
    path: Path | str = _DEFAULT_OUTPUT_JSON,
    *,
    source_paths: dict[str, Path | str] | None = None,
    generated_at_utc: str | None = None,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    report = build_google_workspace_operating_picture_from_paths(
        source_paths=source_paths,
        generated_at_utc=generated_at_utc,
        repo_root=repo_root,
    )
    output_path = Path(path)
    _write_json(output_path, report)
    return report


__all__ = [
    "GoogleWorkspaceOperatingPictureError",
    "build_google_workspace_operating_picture",
    "build_google_workspace_operating_picture_from_paths",
    "write_google_workspace_operating_picture",
]

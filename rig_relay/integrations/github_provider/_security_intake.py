"""GitHub security/quality intake — read-only, content-light alert ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from typing import Any
import uuid

import httpx

from rig_relay.integrations.github_provider._live_auth import (
    GitHubLiveAuthConfig,
    GitHubLiveAuthError,
    GitHubLiveReadOnlySmoke,
    GitHubLiveTokenExchanger,
)
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    hash_identifier,
    safe_summary,
)

_GITHUB_API_BASE = "https://api.github.com"
_CODE_SCANNING_ALERTS_PATH = "/repos/{owner}/{repo}/code-scanning/alerts"
_DEPENDABOT_ALERTS_PATH = "/repos/{owner}/{repo}/dependabot/alerts"

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_security_intake.py -v",
    "uv run pytest tests/adversarial/test_github_security_intake_redaction.py -v",
    "uv run pytest tests/governance/test_github_security_intake_artifact.py -v",
]


class GitHubSecurityIntakeError(Exception):
    """Raised when security intake collection fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _hash_or_empty(value: str) -> str:
    return hash_identifier(value) if value else ""


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _contains_codeql(tool_name: str) -> bool:
    return "codeql" in tool_name.lower()


def _looks_like_workflow_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(".github/workflows") or "workflow" in lowered


def _severity_bucket(severity: str) -> str:
    lowered = severity.lower()
    match lowered:
        case "critical" | "high" | "medium" | "moderate" | "low" | "warning" | "note":
            return lowered
        case _:
            return "unknown"


def _build_refusal(
    surface: str,
    reason: str,
    required_permission: str,
    *,
    status_code: int | None = None,
) -> dict[str, Any]:
    refusal: dict[str, Any] = {
        "surface": surface,
        "status": "refused",
        "reason": reason,
        "required_permission": required_permission,
        "remote_mutation": False,
    }
    if status_code is not None:
        refusal["status_code"] = status_code
    return refusal


def _build_surface(
    surface: str, status: str, required_permission: str, *, details: str = ""
) -> dict[str, Any]:
    item = {
        "surface": surface,
        "status": status,
        "required_permission": required_permission,
        "remote_mutation": False,
    }
    if details:
        item["details"] = details
    return item


def _count_refused_surfaces(source_surfaces: list[dict[str, Any]]) -> int:
    return sum(
        1 for item in source_surfaces if _as_str(item.get("status")) == "refused"
    )


def _code_scanning_endpoint(owner: str, repo: str) -> str:
    return _CODE_SCANNING_ALERTS_PATH.format(owner=owner, repo=repo)


def _dependabot_endpoint(owner: str, repo: str) -> str:
    return _DEPENDABOT_ALERTS_PATH.format(owner=owner, repo=repo)


def _normalize_code_scanning_alert(alert: dict[str, Any]) -> dict[str, Any]:
    rule = alert.get("rule", {}) if isinstance(alert.get("rule"), dict) else {}
    tool = alert.get("tool", {}) if isinstance(alert.get("tool"), dict) else {}
    instance = (
        alert.get("most_recent_instance", {})
        if isinstance(alert.get("most_recent_instance"), dict)
        else {}
    )
    location = (
        instance.get("location", {})
        if isinstance(instance.get("location"), dict)
        else {}
    )
    rule_security_level = _as_str(rule.get("security_severity_level"))
    if not rule_security_level:
        rule_security_level = _as_str(alert.get("security_severity_level"))
    file_path = _as_str(location.get("path"))
    most_recent_ref = _as_str(instance.get("ref"))
    suggested_group_kind = _classify_code_scanning_lane(alert)
    return {
        "classification": "code_scanning",
        "alert_number": _as_int(alert.get("number")),
        "state": _as_str(alert.get("state")),
        "created_at": _as_str(alert.get("created_at")),
        "updated_at": _as_str(alert.get("updated_at")),
        "fixed_at": _as_str(alert.get("fixed_at")),
        "dismissed_at": _as_str(alert.get("dismissed_at")),
        "rule_id_hash": _hash_or_empty(_as_str(rule.get("id"))),
        "rule_severity": _as_str(rule.get("severity")),
        "rule_security_severity_level": rule_security_level,
        "tool_name": _as_str(tool.get("name")),
        "most_recent_instance_ref_hash": _hash_or_empty(most_recent_ref),
        "file_path_hash": _hash_or_empty(file_path),
        "start_line": _as_int(location.get("start_line")),
        "end_line": _as_int(location.get("end_line")),
        "html_url_hash": _hash_or_empty(_as_str(alert.get("html_url"))),
        "suggested_group_kind": suggested_group_kind,
    }


def _normalize_dependabot_alert(alert: dict[str, Any]) -> dict[str, Any]:
    dependency = (
        alert.get("dependency", {}) if isinstance(alert.get("dependency"), dict) else {}
    )
    package = (
        dependency.get("package", {})
        if isinstance(dependency.get("package"), dict)
        else {}
    )
    advisory = (
        alert.get("security_advisory", {})
        if isinstance(alert.get("security_advisory"), dict)
        else {}
    )
    vulnerability = (
        alert.get("security_vulnerability", {})
        if isinstance(alert.get("security_vulnerability"), dict)
        else {}
    )
    identifiers = advisory.get("identifiers", [])
    ghsa_ids = [
        _as_str(item.get("value"))
        for item in identifiers
        if isinstance(item, dict) and _as_str(item.get("type")).upper() == "GHSA"
    ]
    cve_ids = [
        _as_str(item.get("value"))
        for item in identifiers
        if isinstance(item, dict) and _as_str(item.get("type")).upper() == "CVE"
    ]
    fixed_version = ""
    first_patched = vulnerability.get("first_patched_version", {})
    if isinstance(first_patched, dict):
        fixed_version = _as_str(first_patched.get("identifier"))
    package_ecosystem = _as_str(package.get("ecosystem"))
    package_name = _as_str(package.get("name"))
    return {
        "classification": "dependabot",
        "alert_number": _as_int(alert.get("number")),
        "state": _as_str(alert.get("state")),
        "severity": _as_str(alert.get("severity", vulnerability.get("severity", ""))),
        "created_at": _as_str(alert.get("created_at")),
        "updated_at": _as_str(alert.get("updated_at")),
        "fixed_at": _as_str(alert.get("fixed_at")),
        "dismissed_at": _as_str(alert.get("dismissed_at")),
        "package_ecosystem": package_ecosystem,
        "package_coordinate_hash": _hash_or_empty(
            f"{package_ecosystem}:{package_name}" if package_name else ""
        ),
        "package_name_hash": _hash_or_empty(package_name),
        "manifest_path_hash": _hash_or_empty(_as_str(dependency.get("manifest_path"))),
        "scope": _as_str(dependency.get("scope")),
        "ghsa_id_hash": _hash_or_empty(_as_str(advisory.get("ghsa_id"))),
        "ghsa_identifier_hashes": [_hash_or_empty(value) for value in ghsa_ids],
        "cve_identifier_hashes": [_hash_or_empty(value) for value in cve_ids],
        "fixed_version_available": bool(fixed_version),
        "fixed_version": fixed_version,
        "html_url_hash": _hash_or_empty(_as_str(alert.get("html_url"))),
    }


def _classify_code_scanning_lane(alert: dict[str, Any]) -> str:
    tool_name = _as_str(
        alert.get("tool", {}).get("name") if isinstance(alert.get("tool"), dict) else ""
    )
    instance = (
        alert.get("most_recent_instance", {})
        if isinstance(alert.get("most_recent_instance"), dict)
        else {}
    )
    location = (
        instance.get("location", {})
        if isinstance(instance.get("location"), dict)
        else {}
    )
    path = _as_str(location.get("path"))
    if _looks_like_workflow_path(path):
        return "workflow_or_ci_fix_needed"
    if _contains_codeql(tool_name):
        return "codeql_security_fix_needed"
    rule_severity = _severity_bucket(
        _as_str(
            alert.get("rule", {}).get("severity")
            if isinstance(alert.get("rule"), dict)
            else ""
        )
    )
    if rule_severity in {"critical", "high"}:
        return "code_quality_fix_needed"
    return "unknown_triage_needed"


def _classify_dependabot_lane() -> str:
    return "dependency_update_needed"


def _build_patch_candidate_group(
    group_kind: str, alert_refs: list[str], severity_summary: dict[str, int]
) -> dict[str, Any]:
    lane = {
        "dependency_update_needed": "dependency_management",
        "codeql_security_fix_needed": "codeql_fix_lane",
        "code_quality_fix_needed": "code_quality_lane",
        "workflow_or_ci_fix_needed": "workflow_or_ci_lane",
        "permission_blocked": "permission_follow_up",
        "unknown_triage_needed": "manual_triage",
    }.get(group_kind, "manual_triage")
    return {
        "group_kind": group_kind,
        "alert_refs": alert_refs,
        "severity_summary": severity_summary,
        "suggested_local_lane": lane,
        "required_local_validation_commands": list(_VALIDATION_COMMANDS),
    }


@dataclass(slots=True)
class GitHubSecurityIntakeCollector:
    timeout: float = 30.0

    def _request_json(
        self, path: str, token: str, params: dict[str, str] | None = None
    ) -> tuple[Any, dict[str, Any]]:
        url = f"{_GITHUB_API_BASE}{path}"
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "rig-relay-security-intake/1.0",
            },
            params=params,
            timeout=httpx.Timeout(self.timeout),
        )
        response.raise_for_status()
        links = {
            str(key): value for key, value in response.links.items() if key is not None
        }
        return response.json(), links

    def _collect_paginated_items(
        self, path: str, token: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        base_params = dict(params or {})
        while True:
            page_params = dict(base_params)
            page_params["per_page"] = "100"
            page_params["page"] = str(page)
            payload, links = self._request_json(path, token, page_params)
            if not isinstance(payload, list):
                raise GitHubSecurityIntakeError(
                    f"Expected list payload from {path}, got {type(payload).__name__}"
                )
            items.extend([item for item in payload if isinstance(item, dict)])
            if "next" not in links:
                break
            page += 1
        return items

    def _collect_alert_surface(
        self,
        surface: str,
        token: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        required_permission = (
            "Code scanning alerts read"
            if surface == "code_scanning"
            else "Dependabot alerts read"
        )
        try:
            raw_alerts = self._collect_paginated_items(path, token, params=params)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in {401, 403, 404, 422}:
                return (
                    [],
                    [],
                    _build_refusal(
                        surface,
                        "missing_permission_or_not_enabled",
                        required_permission,
                        status_code=e.response.status_code,
                    ),
                )
            raise GitHubSecurityIntakeError(
                f"GitHub API HTTP {e.response.status_code} for {surface}"
            ) from e
        except httpx.RequestError:
            return [], [], _build_refusal(surface, "network_error", required_permission)

        normalized: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        for alert in raw_alerts:
            if surface == "code_scanning":
                record = _normalize_code_scanning_alert(alert)
                group_kind = _classify_code_scanning_lane(alert)
                alert_ref = f"code_scanning#{record['alert_number']}"
            else:
                record = _normalize_dependabot_alert(alert)
                group_kind = _classify_dependabot_lane()
                alert_ref = f"dependabot#{record['alert_number']}"
            normalized.append(record)
            groups.append({
                "group_kind": group_kind,
                "alert_ref": alert_ref,
                "severity": _severity_bucket(
                    _as_str(record.get("severity", "unknown"))
                ),
            })
        return normalized, groups, None

    def _build_base_report(
        self,
        owner: str,
        repo: str,
        *,
        receipt_id: str,
        trace_id: str,
        dry_run: bool,
        installation_id_hash: str = "",
    ) -> dict[str, Any]:
        return {
            "schema_version": "rig.github.security_intake.v1",
            "generated_at": _now_iso(),
            "auth_mode": "app_installation",
            "owner_hash": _hash_or_empty(owner),
            "repo_hash": _hash_or_empty(repo),
            "installation_id_hash": installation_id_hash,
            "trace_id": trace_id,
            "receipt_id": receipt_id,
            "dry_run": dry_run,
            "content_light": True,
            "remote_mutation": False,
            "source_surfaces": [],
            "counts": {
                "code_scanning_open": 0,
                "code_scanning_total": 0,
                "dependabot_open": 0,
                "dependabot_total": 0,
                "refused_surfaces": 0,
            },
            "alerts": {"code_scanning": [], "dependabot": []},
            "patch_candidate_groups": [],
            "refusals": [],
        }

    def collect(
        self,
        owner: str,
        repo: str,
        *,
        live: bool = False,
        config: GitHubLiveAuthConfig | None = None,
        receipt_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        receipt_id = receipt_id or _new_uuid()
        trace_id = trace_id or _new_uuid()
        if not live:
            return self._collect_dry_run(
                owner, repo, receipt_id=receipt_id, trace_id=trace_id
            )
        return self._collect_live(
            owner,
            repo,
            config=config or GitHubLiveAuthConfig.from_environment(),
            receipt_id=receipt_id,
            trace_id=trace_id,
        )

    def _collect_dry_run(
        self, owner: str, repo: str, *, receipt_id: str, trace_id: str
    ) -> dict[str, Any]:
        report = self._build_base_report(
            owner, repo, receipt_id=receipt_id, trace_id=trace_id, dry_run=True
        )
        report["source_surfaces"] = [
            _build_surface(
                "code_scanning",
                "dry_run",
                "Code scanning alerts read",
                details="No network calls were made.",
            ),
            _build_surface(
                "dependabot",
                "dry_run",
                "Dependabot alerts read",
                details="No network calls were made.",
            ),
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            ),
        ]
        report["counts"]["refused_surfaces"] = _count_refused_surfaces(
            report["source_surfaces"]
        )
        report["refusals"].append(
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            )
        )
        return self._finalize(report)

    def _collect_live(
        self,
        owner: str,
        repo: str,
        *,
        config: GitHubLiveAuthConfig,
        receipt_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if os.environ.get("RIG_LIVE_AUTH_TESTS") != "1":
            return self._build_permission_refusal_report(
                owner,
                repo,
                receipt_id=receipt_id,
                trace_id=trace_id,
                reason="live_network_disabled",
            )

        report = self._build_base_report(
            owner, repo, receipt_id=receipt_id, trace_id=trace_id, dry_run=False
        )

        if not config._has_app_auth():
            report["refusals"].append(
                _build_refusal(
                    "authentication",
                    "missing_app_auth_configuration",
                    "GitHub App installation credentials",
                )
            )
            report["source_surfaces"] = [
                _build_surface(
                    "code_scanning",
                    "refused",
                    "Code scanning alerts read",
                    details="Auth configuration incomplete.",
                ),
                _build_surface(
                    "dependabot",
                    "refused",
                    "Dependabot alerts read",
                    details="Auth configuration incomplete.",
                ),
                _build_refusal(
                    "secret_scanning",
                    "missing_permission_or_not_enabled",
                    "Secret scanning alerts read",
                ),
            ]
            report["counts"]["refused_surfaces"] = _count_refused_surfaces(
                report["source_surfaces"]
            )
            return self._finalize(report)

        try:
            private_key = config.load_private_key()
        except GitHubLiveAuthError:
            report["refusals"].append(
                _build_refusal(
                    "authentication",
                    "private_key_load_failed",
                    "GitHub App installation credentials",
                )
            )
            report["source_surfaces"] = [
                _build_surface(
                    "code_scanning",
                    "refused",
                    "Code scanning alerts read",
                    details="Private key load failed.",
                ),
                _build_surface(
                    "dependabot",
                    "refused",
                    "Dependabot alerts read",
                    details="Private key load failed.",
                ),
                _build_refusal(
                    "secret_scanning",
                    "missing_permission_or_not_enabled",
                    "Secret scanning alerts read",
                ),
            ]
            report["counts"]["refused_surfaces"] = _count_refused_surfaces(
                report["source_surfaces"]
            )
            return self._finalize(report)

        exchanger = GitHubLiveTokenExchanger(timeout=self.timeout)
        try:
            token_result, raw_token = exchanger.exchange_installation_token(
                app_id=config.app_id or 0,
                installation_id=config.installation_id or 0,
                private_key_bytes=private_key,
            )
        except GitHubLiveAuthError:
            report["refusals"].append(
                _build_refusal(
                    "authentication",
                    "token_exchange_failed",
                    "GitHub App installation credentials",
                )
            )
            report["source_surfaces"] = [
                _build_surface(
                    "code_scanning",
                    "refused",
                    "Code scanning alerts read",
                    details="Token exchange failed.",
                ),
                _build_surface(
                    "dependabot",
                    "refused",
                    "Dependabot alerts read",
                    details="Token exchange failed.",
                ),
                _build_refusal(
                    "secret_scanning",
                    "missing_permission_or_not_enabled",
                    "Secret scanning alerts read",
                ),
            ]
            report["counts"]["refused_surfaces"] = _count_refused_surfaces(
                report["source_surfaces"]
            )
            return self._finalize(report)

        smoke = GitHubLiveReadOnlySmoke(timeout=self.timeout)
        installation_access = smoke.probe_installation_access(
            raw_token,
            installation_id=config.installation_id,
            repository_selection=_as_str(token_result.get("repository_selection")),
            permission_keys=sorted(token_result.get("permissions", {}).keys())
            if isinstance(token_result.get("permissions"), dict)
            else None,
        )
        if installation_access.get("error"):
            report["refusals"].append(
                _build_refusal(
                    "authentication",
                    _as_str(installation_access.get("error")),
                    "GitHub App installation credentials",
                    status_code=installation_access.get("status_code")
                    if isinstance(installation_access.get("status_code"), int)
                    else None,
                )
            )
            report["source_surfaces"] = [
                _build_surface(
                    "code_scanning",
                    "refused",
                    "Code scanning alerts read",
                    details="Installation access proof failed.",
                ),
                _build_surface(
                    "dependabot",
                    "refused",
                    "Dependabot alerts read",
                    details="Installation access proof failed.",
                ),
                _build_refusal(
                    "secret_scanning",
                    "missing_permission_or_not_enabled",
                    "Secret scanning alerts read",
                ),
            ]
            report["counts"]["refused_surfaces"] = _count_refused_surfaces(
                report["source_surfaces"]
            )
            return self._finalize(report)

        report["installation_access"] = safe_summary(installation_access)

        code_scanning_alerts, code_groups, code_refusal = self._collect_alert_surface(
            "code_scanning",
            raw_token,
            _code_scanning_endpoint(owner, repo),
            params={"state": "all"},
        )
        dependabot_alerts, dependabot_groups, dependabot_refusal = (
            self._collect_alert_surface(
                "dependabot",
                raw_token,
                _dependabot_endpoint(owner, repo),
                params={"state": "all"},
            )
        )

        report["alerts"]["code_scanning"] = code_scanning_alerts
        report["alerts"]["dependabot"] = dependabot_alerts
        report["counts"]["code_scanning_total"] = len(code_scanning_alerts)
        report["counts"]["dependabot_total"] = len(dependabot_alerts)
        report["counts"]["code_scanning_open"] = sum(
            1 for item in code_scanning_alerts if _as_str(item.get("state")) == "open"
        )
        report["counts"]["dependabot_open"] = sum(
            1 for item in dependabot_alerts if _as_str(item.get("state")) == "open"
        )

        report["source_surfaces"] = [
            _build_surface(
                "code_scanning",
                "collected" if not code_refusal else "refused",
                "Code scanning alerts read",
                details=(
                    f"{len(code_scanning_alerts)} alerts"
                    if not code_refusal
                    else "Permission or feature unavailable."
                ),
            ),
            _build_surface(
                "dependabot",
                "collected" if not dependabot_refusal else "refused",
                "Dependabot alerts read",
                details=(
                    f"{len(dependabot_alerts)} alerts"
                    if not dependabot_refusal
                    else "Permission or feature unavailable."
                ),
            ),
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            ),
        ]
        if code_refusal is not None:
            report["refusals"].append(code_refusal)
        if dependabot_refusal is not None:
            report["refusals"].append(dependabot_refusal)
        report["refusals"].append(
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            )
        )
        report["counts"]["refused_surfaces"] = _count_refused_surfaces(
            report["source_surfaces"]
        )
        report["patch_candidate_groups"] = self._build_patch_candidate_groups(
            code_scanning_alerts,
            dependabot_alerts,
            code_refusal=code_refusal,
            dependabot_refusal=dependabot_refusal,
            secret_refusal=report["refusals"][-1] if report["refusals"] else None,
        )
        return self._finalize(report)

    def _build_permission_refusal_report(
        self, owner: str, repo: str, *, receipt_id: str, trace_id: str, reason: str
    ) -> dict[str, Any]:
        report = self._build_base_report(
            owner, repo, receipt_id=receipt_id, trace_id=trace_id, dry_run=False
        )
        report["refusals"].append(
            _build_refusal(
                "authentication", reason, "GitHub App installation credentials"
            )
        )
        report["source_surfaces"] = [
            _build_surface(
                "code_scanning",
                "refused",
                "Code scanning alerts read",
                details="Live network is disabled.",
            ),
            _build_surface(
                "dependabot",
                "refused",
                "Dependabot alerts read",
                details="Live network is disabled.",
            ),
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            ),
        ]
        report["counts"]["refused_surfaces"] = _count_refused_surfaces(
            report["source_surfaces"]
        )
        report["refusals"].append(
            _build_refusal(
                "secret_scanning",
                "missing_permission_or_not_enabled",
                "Secret scanning alerts read",
            )
        )
        return self._finalize(report)

    def _build_patch_candidate_groups(
        self,
        code_scanning_alerts: list[dict[str, Any]],
        dependabot_alerts: list[dict[str, Any]],
        *,
        code_refusal: dict[str, Any] | None = None,
        dependabot_refusal: dict[str, Any] | None = None,
        secret_refusal: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[str]] = {
            "dependency_update_needed": [],
            "codeql_security_fix_needed": [],
            "code_quality_fix_needed": [],
            "workflow_or_ci_fix_needed": [],
            "permission_blocked": [],
            "unknown_triage_needed": [],
        }
        severities: dict[str, dict[str, int]] = {}

        def _bump(group_kind: str, ref: str, severity: str) -> None:
            groups[group_kind].append(ref)
            severity_bucket = _severity_bucket(severity)
            bucket = severities.setdefault(group_kind, {})
            bucket[severity_bucket] = bucket.get(severity_bucket, 0) + 1

        for alert in code_scanning_alerts:
            group_kind = _as_str(
                alert.get("suggested_group_kind", "unknown_triage_needed")
            )
            _bump(
                group_kind,
                f"code_scanning#{alert['alert_number']}",
                _as_str(
                    alert.get("rule_security_severity_level")
                    or alert.get("rule_severity")
                ),
            )

        for alert in dependabot_alerts:
            _bump(
                "dependency_update_needed",
                f"dependabot#{alert['alert_number']}",
                _as_str(alert.get("severity")),
            )

        refusal_refs = []
        if code_refusal is not None:
            refusal_refs.append("code_scanning:refused")
        if dependabot_refusal is not None:
            refusal_refs.append("dependabot:refused")
        if secret_refusal is not None:
            refusal_refs.append("secret_scanning:refused")
        if refusal_refs:
            _bump("permission_blocked", ",".join(refusal_refs), "unknown")

        result = []
        for group_kind, alert_refs in groups.items():
            if not alert_refs:
                continue
            result.append(
                _build_patch_candidate_group(
                    group_kind, alert_refs, severities.get(group_kind, {})
                )
            )
        return result

    def _finalize(self, report: dict[str, Any]) -> dict[str, Any]:
        assert_content_light_mapping(report)
        return safe_summary(report)


def build_github_security_intake_report(
    owner: str,
    repo: str,
    *,
    live: bool = False,
    config: GitHubLiveAuthConfig | None = None,
    receipt_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return GitHubSecurityIntakeCollector().collect(
        owner, repo, live=live, config=config, receipt_id=receipt_id, trace_id=trace_id
    )


__all__ = [
    "GitHubSecurityIntakeCollector",
    "_normalize_code_scanning_alert",
    "_normalize_dependabot_alert",
    "build_github_security_intake_report",
]

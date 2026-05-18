#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "SECURITY.md",
    "LICENSE",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "ATTRIBUTION.md",
    "pyproject.toml",
    ".gitignore",
    "docs/json/repository_policy.v1.json",
    "docs/json/license_policy.v1.json",
    "docs/json/release_gate/rc_candidate_verdict.v1.json",
    "docs/json/release_candidate/rc_golden_path_run.v1.json",
    "scripts/install.sh",
]

ALLOWED_MARKDOWN_EXCEPTIONS = {
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "ATTRIBUTION.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
}

FORBIDDEN_MARKDOWN_REPORT_PREFIXES = (
    "docs/audits/",
    "docs/reports/",
    "docs/roadmaps/",
    "docs/proofs/",
)

SECRET_PATTERNS = [
    ("secret.aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret.github_pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("secret.github_installation", re.compile(r"\bghs_[A-Za-z0-9]{36}\b")),
    ("secret.openai_key_like", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "secret.private_key_header",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    ),
]

LOCAL_PATH_PATTERN = re.compile(
    r"(?:/Users/[A-Za-z0-9_\-./]+|/home/[A-Za-z0-9_\-./]+|C:\\\\Users\\\\[A-Za-z0-9_\\.-]+)"
)

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".pdf",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".so",
    ".dll",
    ".dylib",
}

SCAN_SKIP_PREFIXES = (
    "tests/",
    "docs/pages/",
    "docs/collections/",
    "docs/assets/",
    "docs/audits/",
    "docs/conversations/",
    "docs/dogfood/",
    "docs/json/audits/",
    "docs/json/dogfood/",
    ".build/",
    ".rig/",
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_output(repo_root: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
    except Exception:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_names(on_data: object) -> set[str]:
    match on_data:
        case str():
            return {on_data}
        case list():
            return {str(v) for v in on_data}
        case dict():
            return {str(k) for k in on_data.keys()}
        case _:
            return set()


def _workflow_dispatch_inputs(on_data: object) -> set[str]:
    if not isinstance(on_data, dict):
        return set()
    dispatch = on_data.get("workflow_dispatch")
    if not isinstance(dispatch, dict):
        return set()
    inputs = dispatch.get("inputs")
    if not isinstance(inputs, dict):
        return set()
    return {str(k) for k in inputs.keys()}


def _is_sha_pinned(uses_value: str) -> bool:
    if "@" not in uses_value:
        return False
    ref = uses_value.rsplit("@", 1)[1]
    return re.fullmatch(r"[a-f0-9]{40}", ref) is not None


def _has_dangerous_write_permissions(
    permissions: object, has_pull_request: bool
) -> tuple[bool, str]:
    if isinstance(permissions, str):
        value = permissions.lower()
        if value == "write-all":
            return True, "write-all"
        if has_pull_request and value.endswith("write"):
            return True, value
        return False, ""

    if isinstance(permissions, dict):
        for scope, raw in permissions.items():
            if not isinstance(raw, str):
                continue
            value = raw.lower()
            if value == "write":
                if has_pull_request:
                    return True, f"{scope}: write"
                if str(scope) == "contents":
                    return True, f"{scope}: write"
            if value == "write-all":
                return True, f"{scope}: write-all"
    return False, ""


def scan_workflow_file(workflow_path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    try:
        import yaml

        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        findings.append(
            {
                "workflow": str(workflow_path),
                "severity": "high",
                "finding_id": "workflow.parse_error",
                "detail": f"Failed to parse workflow: {exc}",
            }
        )
        return findings

    if not isinstance(workflow, dict):
        findings.append(
            {
                "workflow": str(workflow_path),
                "severity": "high",
                "finding_id": "workflow.invalid_shape",
                "detail": "Workflow root must be an object",
            }
        )
        return findings

    on_data = workflow.get("on")
    event_names = _event_names(on_data)
    has_pull_request = "pull_request" in event_names
    dispatch_inputs = _workflow_dispatch_inputs(on_data)

    top_permissions = workflow.get("permissions")
    if top_permissions is None:
        findings.append(
            {
                "workflow": str(workflow_path),
                "severity": "low",
                "finding_id": "workflow.permissions_not_explicit",
                "detail": "Top-level permissions are not explicitly declared",
            }
        )

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return findings

    for job_name, job_value in jobs.items():
        if not isinstance(job_value, dict):
            continue

        effective_permissions = job_value.get("permissions", top_permissions)
        has_dangerous_permissions, detail = _has_dangerous_write_permissions(
            effective_permissions, has_pull_request
        )
        if has_dangerous_permissions:
            findings.append(
                {
                    "workflow": str(workflow_path),
                    "severity": "high",
                    "finding_id": "workflow.permissions_dangerous",
                    "detail": f"Job '{job_name}' has dangerous permissions ({detail})",
                }
            )

        job_if = str(job_value.get("if", ""))
        steps = job_value.get("steps")
        if not isinstance(steps, list):
            continue

        for step in steps:
            if not isinstance(step, dict):
                continue
            uses_value = step.get("uses")
            if not isinstance(uses_value, str):
                continue

            if not _is_sha_pinned(uses_value):
                findings.append(
                    {
                        "workflow": str(workflow_path),
                        "severity": "low",
                        "finding_id": "workflow.action_not_sha_pinned",
                        "detail": f"Job '{job_name}' step uses unpinned action '{uses_value}'",
                    }
                )

            if "pypa/gh-action-pypi-publish" in uses_value:
                step_if = str(step.get("if", ""))
                guard = f"{job_if} {step_if}"
                has_release_guard = "github.event_name == 'release'" in guard
                has_manual_guard = "publish_to_pypi" in guard

                if not has_release_guard and not has_manual_guard:
                    findings.append(
                        {
                            "workflow": str(workflow_path),
                            "severity": "high",
                            "finding_id": "workflow.pypi_publish_unrestricted",
                            "detail": (
                                f"Job '{job_name}' publishes to PyPI without explicit release/manual confirmation guard"
                            ),
                        }
                    )

                if "workflow_dispatch" in event_names and "publish_to_pypi" not in dispatch_inputs:
                    findings.append(
                        {
                            "workflow": str(workflow_path),
                            "severity": "medium",
                            "finding_id": "workflow.pypi_manual_input_missing",
                            "detail": (
                                "workflow_dispatch exists but publish_to_pypi input is not declared"
                            ),
                        }
                    )

    return findings


def detect_forbidden_markdown_paths(
    paths: list[str],
    allowed_exceptions: set[str] | None = None,
) -> list[str]:
    allowed = allowed_exceptions or ALLOWED_MARKDOWN_EXCEPTIONS
    forbidden: list[str] = []

    for raw_path in paths:
        path = raw_path.lstrip("./")
        if not path.endswith(".md"):
            continue
        if path in allowed:
            continue
        if any(path.startswith(prefix) for prefix in FORBIDDEN_MARKDOWN_REPORT_PREFIXES):
            forbidden.append(path)

    return sorted(set(forbidden))


def _parse_project_metadata(repo_root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    license_field = project.get("license")
    if isinstance(license_field, dict):
        license_text = str(license_field.get("text", ""))
    else:
        license_text = str(license_field or "")

    return {
        "name": str(project.get("name", "")),
        "version": str(project.get("version", "")),
        "license": license_text,
    }


def evaluate_security_policy(repo_root: Path) -> tuple[str, list[str]]:
    security_path = repo_root / "SECURITY.md"
    if not security_path.is_file():
        return "failed", ["SECURITY.md is missing"]

    text = security_path.read_text(encoding="utf-8")
    issues: list[str] = []

    if "security/advisories/new" not in text:
        issues.append("SECURITY.md does not include private GitHub advisory reporting URL")

    if "Do **not** report vulnerabilities" not in text and "Do not report vulnerabilities" not in text:
        issues.append("SECURITY.md does not clearly prohibit public vulnerability disclosure")

    if "0.1.0a1" not in text:
        issues.append("SECURITY.md does not explicitly list support scope for 0.1.0a1")

    return ("passed", []) if not issues else ("failed", issues)


def evaluate_license_consistency(repo_root: Path) -> tuple[str, list[str]]:
    issues: list[str] = []
    metadata = _parse_project_metadata(repo_root)

    if metadata["license"] != "AGPL-3.0-or-later":
        issues.append(f"pyproject license is '{metadata['license']}', expected AGPL-3.0-or-later")

    license_text = (repo_root / "LICENSE").read_text(encoding="utf-8")
    if "GNU AFFERO GENERAL PUBLIC LICENSE" not in license_text:
        issues.append("LICENSE does not contain GNU AGPL text")

    repository_policy = _read_json(repo_root / "docs/json/repository_policy.v1.json")
    if repository_policy.get("license") != "AGPL-3.0-or-later":
        issues.append("repository_policy.v1.json license is not AGPL-3.0-or-later")

    license_policy = _read_json(repo_root / "docs/json/license_policy.v1.json")
    if license_policy.get("public_license") != "AGPL-3.0-or-later":
        issues.append("license_policy.v1.json public_license is not AGPL-3.0-or-later")

    return ("passed", []) if not issues else ("failed", issues)


def check_install_script_source(script_text: str) -> list[str]:
    issues: list[str] = []

    if 'uv tool install "git+https://github.com/juliantorr-es/rig-relay.git"' not in script_text:
        issues.append("install.sh is not pinned to the expected GitHub source URL")

    if re.search(r"uv\s+tool\s+install\s+rig-relay(\s|$)", script_text):
        issues.append("install.sh uses plain package install target instead of git+ GitHub source")

    return issues


def evaluate_metadata_consistency(repo_root: Path) -> tuple[str, list[str]]:
    issues: list[str] = []
    metadata = _parse_project_metadata(repo_root)

    if metadata["name"] != "rig-relay":
        issues.append(f"pyproject name mismatch: {metadata['name']}")

    if metadata["version"] != "0.1.0a1":
        issues.append(f"pyproject version mismatch: {metadata['version']}")

    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")
    if "server/control-plane" not in readme_text:
        issues.append("README is missing server/control-plane architecture language")
    if "desktop cockpit" not in readme_text.lower():
        issues.append("README is missing desktop cockpit positioning")
    if "debug/admin/operator shims" not in readme_text:
        issues.append("README does not describe CLI as debug/admin/operator shims")

    if "[0.1.0a1]" not in (repo_root / "CHANGELOG.md").read_text(encoding="utf-8"):
        issues.append("CHANGELOG.md does not include the 0.1.0a1 section")

    repository_policy = _read_json(repo_root / "docs/json/repository_policy.v1.json")
    if repository_policy.get("repository") != "juliantorr-es/rig-relay":
        issues.append("repository_policy.v1.json repository value is stale")

    install_issues = check_install_script_source(
        (repo_root / "scripts/install.sh").read_text(encoding="utf-8")
    )
    issues.extend(install_issues)

    return ("passed", []) if not issues else ("failed", issues)


def _tracked_files(repo_root: Path) -> list[str]:
    output = _git_output(repo_root, ["ls-files"])
    if not output:
        return []
    return [line for line in output.splitlines() if line.strip()]


def _is_scan_skipped(path: str) -> bool:
    if any(path.startswith(prefix) for prefix in SCAN_SKIP_PREFIXES):
        return True
    if path.endswith(".lock"):
        return True
    suffix = Path(path).suffix.lower()
    return suffix in BINARY_SUFFIXES


def scan_secret_and_path_hygiene(repo_root: Path) -> tuple[str, list[str], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    high_count = 0
    medium_count = 0

    for rel_path in _tracked_files(repo_root):
        if _is_scan_skipped(rel_path):
            continue

        file_path = repo_root / rel_path
        if not file_path.is_file():
            continue
        if file_path.stat().st_size > 1_000_000:
            continue

        text = file_path.read_text(encoding="utf-8", errors="ignore")

        for finding_id, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(
                    {
                        "severity": "high",
                        "finding_id": finding_id,
                        "path": rel_path,
                        "detail": "Potential secret-like token detected",
                    }
                )
                high_count += 1

        if LOCAL_PATH_PATTERN.search(text):
            findings.append(
                {
                    "severity": "medium",
                    "finding_id": "hygiene.absolute_local_path",
                    "path": rel_path,
                    "detail": "Absolute local path detected",
                }
            )
            medium_count += 1

    tracked_pi_lens = [p for p in _tracked_files(repo_root) if p.startswith(".pi-lens/")]
    if tracked_pi_lens:
        findings.append(
            {
                "severity": "high",
                "finding_id": "hygiene.tracked_pi_lens",
                "path": ".pi-lens/",
                "detail": f"Tracked .pi-lens artifacts detected ({len(tracked_pi_lens)})",
            }
        )
        high_count += 1

    tracked_env = [
        p
        for p in _tracked_files(repo_root)
        if Path(p).name.startswith(".env") and not p.endswith(".env.example")
    ]
    if tracked_env:
        findings.append(
            {
                "severity": "high",
                "finding_id": "hygiene.tracked_env",
                "path": ", ".join(tracked_env[:3]),
                "detail": f"Tracked .env files detected ({len(tracked_env)})",
            }
        )
        high_count += 1

    tracked_generated = [
        p
        for p in _tracked_files(repo_root)
        if p.startswith(".build/") or p.startswith(".rig/")
    ]
    if tracked_generated:
        findings.append(
            {
                "severity": "high",
                "finding_id": "hygiene.tracked_generated_runtime",
                "path": tracked_generated[0],
                "detail": f"Tracked generated runtime artifacts detected ({len(tracked_generated)})",
            }
        )
        high_count += 1

    if high_count > 0:
        status = "failed"
    elif medium_count > 0:
        status = "hold"
    else:
        status = "passed"

    actions: list[str] = []
    if high_count > 0:
        actions.append("Remove or redact high-severity secret/runtime hygiene findings")
    if medium_count > 0:
        actions.append("Review medium-severity absolute local path findings")

    return status, actions, findings


def _status_from_workflow_findings(findings: list[dict[str, str]]) -> str:
    severities = {finding.get("severity", "") for finding in findings}
    if "high" in severities:
        return "failed"
    if "medium" in severities:
        return "hold"
    return "passed"


def _status_to_check_result(status: str) -> str:
    return "pass" if status == "passed" else "fail" if status == "failed" else "warn"


def files_checked(repo_root: Path) -> list[str]:
    checked: list[str] = []
    for rel_path in REQUIRED_FILES:
        path = repo_root / rel_path
        if path.exists():
            checked.append(rel_path)

    for workflow in sorted((repo_root / ".github/workflows").glob("*.yml")):
        checked.append(str(workflow.relative_to(repo_root)))

    for template in sorted((repo_root / ".github/ISSUE_TEMPLATE").glob("*")):
        if template.is_file():
            checked.append(str(template.relative_to(repo_root)))

    return checked


def run_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    branch = _git_output(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    head_sha = _git_output(repo_root, ["rev-parse", "HEAD"])

    checked_paths = files_checked(repo_root)

    workflow_findings: list[dict[str, str]] = []
    for workflow in sorted((repo_root / ".github/workflows").glob("*.yml")):
        workflow_findings.extend(scan_workflow_file(workflow))

    workflow_status = _status_from_workflow_findings(workflow_findings)

    security_policy_status, security_issues = evaluate_security_policy(repo_root)
    license_status, license_issues = evaluate_license_consistency(repo_root)
    metadata_status, metadata_issues = evaluate_metadata_consistency(repo_root)
    secret_status, secret_actions, secret_findings = scan_secret_and_path_hygiene(repo_root)

    forbidden_markdown = detect_forbidden_markdown_paths(checked_paths)
    markdown_status = "passed" if not forbidden_markdown else "failed"

    checks = [
        {
            "check_id": "security_policy_private_reporting",
            "status": _status_to_check_result(security_policy_status),
            "detail": "Security policy supports private vulnerability reporting and 0.1.0a1 scope",
            "issues": security_issues,
        },
        {
            "check_id": "workflow_least_privilege",
            "status": _status_to_check_result(workflow_status),
            "detail": f"Workflow findings: {len(workflow_findings)}",
        },
        {
            "check_id": "license_consistency",
            "status": _status_to_check_result(license_status),
            "detail": "Public license metadata is AGPL-3.0-or-later across policy and package metadata",
            "issues": license_issues,
        },
        {
            "check_id": "metadata_consistency",
            "status": _status_to_check_result(metadata_status),
            "detail": "README, pyproject, policies, changelog, and install script are aligned",
            "issues": metadata_issues,
        },
        {
            "check_id": "secret_and_path_hygiene",
            "status": _status_to_check_result(secret_status),
            "detail": (
                f"Secret/path scan findings: {len(secret_findings)}"
            ),
        },
        {
            "check_id": "markdown_exception_policy",
            "status": _status_to_check_result(markdown_status),
            "detail": "Allowed Markdown exceptions remain allowed and forbidden report paths are rejected",
            "issues": forbidden_markdown,
        },
    ]

    required_next_actions: list[str] = []
    required_next_actions.extend(security_issues)
    required_next_actions.extend(license_issues)
    required_next_actions.extend(metadata_issues)
    required_next_actions.extend(secret_actions)

    medium_or_higher_workflow_findings = [
        finding
        for finding in workflow_findings
        if finding.get("severity") in {"medium", "high"}
    ]
    for finding in medium_or_higher_workflow_findings:
        required_next_actions.append(
            f"{finding['workflow']}: {finding['finding_id']} — {finding['detail']}"
        )

    if forbidden_markdown:
        required_next_actions.append(
            f"Forbidden Markdown report paths detected: {', '.join(forbidden_markdown)}"
        )

    component_statuses = [
        security_policy_status,
        workflow_status,
        license_status,
        metadata_status,
        secret_status,
        markdown_status,
    ]

    if "failed" in component_statuses:
        overall_status = "failed"
    elif "hold" in component_statuses:
        overall_status = "hold"
    else:
        overall_status = "passed"

    return {
        "schema_version": "rig.release_candidate.security_repository_hygiene.v1",
        "generated_at": _now_iso(),
        "branch": branch,
        "head_sha": head_sha,
        "overall_status": overall_status,
        "checks": checks,
        "files_checked": checked_paths,
        "workflow_findings": workflow_findings,
        "security_policy_status": security_policy_status,
        "license_status": license_status,
        "metadata_consistency_status": metadata_status,
        "secret_scan_status": secret_status,
        "required_next_actions": sorted(set(required_next_actions)),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-rc-security-repository-hygiene",
        description="Run RC security/repository hygiene checks and emit JSON evidence.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root to audit (default: current rig-relay repo).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write JSON output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless overall_status is passed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    result = run_audit(repo_root)

    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    print(payload)

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = repo_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")

    if args.strict:
        return 0 if result["overall_status"] == "passed" else 1
    return 0 if result["overall_status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

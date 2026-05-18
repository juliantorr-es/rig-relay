from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import jsonschema
import pytest

from scripts.rig_rc_security_repository_hygiene import (
    check_install_script_source,
    detect_forbidden_markdown_paths,
    evaluate_metadata_consistency,
    scan_secret_and_path_hygiene,
    scan_workflow_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPO_ROOT / "docs/json/release_candidate/rc_security_repository_hygiene.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs/schemas/rig.release_candidate.security_repository_hygiene.v1.schema.json"
)


@pytest.mark.contract
@pytest.mark.real_artifact
def test_security_repository_hygiene_artifact_validates_schema() -> None:
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(artifact))
    assert not errors, "; ".join(
        f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )


@pytest.mark.adversarial
def test_workflow_scanner_flags_dangerous_permissions(tmp_path: Path) -> None:
    workflow = tmp_path / "danger.yml"
    workflow.write_text(
        """
name: Dangerous workflow
on:
  pull_request:
    branches: [main]
jobs:
  release:
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: pypa/gh-action-pypi-publish@v1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    findings = scan_workflow_file(workflow)
    finding_ids = {finding["finding_id"] for finding in findings}
    assert "workflow.permissions_dangerous" in finding_ids
    assert "workflow.pypi_publish_unrestricted" in finding_ids


@pytest.mark.contract
def test_metadata_consistency_detects_stale_project_identity(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/json").mkdir(parents=True, exist_ok=True)

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "stale-name"
version = "9.9.9"
license = { text = "MIT" }
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "legacy text without required architecture language\n", encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "docs/json/repository_policy.v1.json").write_text(
        json.dumps({"repository": "someone/else"}), encoding="utf-8"
    )
    (tmp_path / "scripts/install.sh").write_text(
        "uv tool install rig-relay\n", encoding="utf-8"
    )

    status, issues = evaluate_metadata_consistency(tmp_path)
    assert status == "failed"
    assert any("name mismatch" in issue for issue in issues)
    assert any("expected GitHub source URL" in issue for issue in issues)


@pytest.mark.adversarial
def test_secret_scanner_catches_fake_api_key(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "danger.py").write_text(
        'token = "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"\n', encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", "danger.py"], cwd=tmp_path, check=True, capture_output=True
    )

    status, _actions, findings = scan_secret_and_path_hygiene(tmp_path)
    finding_ids = {finding["finding_id"] for finding in findings}
    assert status == "failed"
    assert "secret.github_pat" in finding_ids


@pytest.mark.contract
def test_markdown_exception_policy_allows_exceptions_and_blocks_reports() -> None:
    forbidden = detect_forbidden_markdown_paths([
        "README.md",
        "SECURITY.md",
        "docs/audits/new-audit.md",
        "docs/reports/final-report.md",
    ])
    assert "README.md" not in forbidden
    assert "SECURITY.md" not in forbidden
    assert "docs/audits/new-audit.md" in forbidden
    assert "docs/reports/final-report.md" in forbidden


@pytest.mark.substrate
@pytest.mark.real_artifact
def test_evidence_artifact_contains_no_raw_secrets() -> None:
    text = ARTIFACT_PATH.read_text(encoding="utf-8")
    patterns = [
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
        re.compile(r"\bghs_[A-Za-z0-9]{36}\b"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    ]
    assert all(pattern.search(text) is None for pattern in patterns)


@pytest.mark.contract
def test_install_script_source_points_to_expected_github_repo() -> None:
    install_text = (REPO_ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    assert check_install_script_source(install_text) == []

    stale_source = "uv tool install rig-relay\n"
    issues = check_install_script_source(stale_source)
    assert any("expected GitHub source URL" in issue for issue in issues)
    assert any("plain package install target" in issue for issue in issues)

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.release_candidate.installability_check.v1.schema.json"
)
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "rig_rc_installability_check.py"

_REQUIRED_TOP_KEYS = {
    "schema_version",
    "generated_at",
    "branch",
    "head_sha",
    "package_name",
    "package_version",
    "python_requires",
    "overall_status",
    "cli_entry_points_checked",
    "public_docs_checked",
    "license_status",
    "checks",
    "errors",
    "warnings",
    "evidence_paths",
    "commands_run",
    "duration_ms",
    "required_next_actions",
}


def _run_installability_script(cwd: Path | None = None) -> dict:
    import subprocess

    result = subprocess.run(
        ["uv", "run", "python", str(_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=120,
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def real_output() -> dict:
    return _run_installability_script(cwd=_REPO_ROOT)


# ── Real-artifact tests ───────────────────────────────────────────────


def test_installability_check_emits_valid_json(real_output: dict) -> None:
    assert isinstance(real_output, dict)
    assert set(real_output.keys()) >= _REQUIRED_TOP_KEYS, (
        f"Missing keys: {_REQUIRED_TOP_KEYS - set(real_output.keys())}"
    )


def test_installability_check_overall_status_passed(real_output: dict) -> None:
    assert real_output["overall_status"] in {"passed", "failed", "blocked"}


# ── Contract tests ────────────────────────────────────────────────────


@pytest.mark.contract
def test_schema_validates_installability_output(real_output: dict) -> None:
    import jsonschema

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(real_output))
    assert not errors, "Schema validation errors: " + "; ".join(
        f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors
    )


@pytest.mark.contract
def test_version_is_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.rig_rc_installability_check import check_version_ascii

    def _fake_pyproject() -> dict:
        return {"project": {"version": "0.1.0\u200b"}}

    monkeypatch.setattr(
        "scripts.rig_rc_installability_check._load_pyproject", _fake_pyproject
    )
    result = check_version_ascii()
    assert result["status"] == "fail"
    assert "non-ASCII" in result["detail"]


# ── Adversarial tests ─────────────────────────────────────────────────


def test_missing_public_doc_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.rig_rc_installability_check import check_required_public_docs

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    # Intentionally skip LICENSE, CHANGELOG.md, SECURITY.md

    monkeypatch.setattr("scripts.rig_rc_installability_check.REPO_ROOT", tmp_path)

    result = check_required_public_docs()
    assert result["status"] == "fail"
    assert "Missing required docs" in result["detail"]
    assert "LICENSE" in result["detail"]


def test_license_mismatch_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.rig_rc_installability_check import check_license_consistency

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nlicense = { text = "MIT" }\n', encoding="utf-8"
    )
    (tmp_path / "LICENSE").write_text(
        "GNU AFFERO GENERAL PUBLIC LICENSE Version 3\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.PYPROJECT_PATH",
        tmp_path / "pyproject.toml",
    )
    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.LICENSE_PATH", tmp_path / "LICENSE"
    )

    result = check_license_consistency()
    assert result["status"] == "fail"
    assert "mismatch" in result["detail"].lower()


def test_failing_command_is_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.rig_rc_installability_check import run_checks

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "1.0"\n'
        'requires-python = ">=3.12"\nlicense = { text = "MIT" }\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "SECURITY.md").write_text("# Security\n", encoding="utf-8")

    monkeypatch.setattr("scripts.rig_rc_installability_check.REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.PYPROJECT_PATH",
        tmp_path / "pyproject.toml",
    )
    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.LICENSE_PATH", tmp_path / "LICENSE"
    )
    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.SCHEMA_VALIDATOR_PATH",
        tmp_path / "scripts" / "rig_relay_validate_schemas.py",
    )
    monkeypatch.setattr(
        "scripts.rig_rc_installability_check.RELEASE_GATE_VALIDATOR_PATH",
        tmp_path / "scripts" / "rig_release_gate_validate.py",
    )

    output = run_checks(strict=False)
    assert isinstance(output, dict)
    assert "overall_status" in output
    assert "errors" in output
    assert "checks" in output


# ── Substrate test ────────────────────────────────────────────────────


def test_no_markdown_evidence_created(real_output: dict) -> None:
    evidence = real_output.get("evidence_paths", [])
    assert isinstance(evidence, list)
    md_evidence = [p for p in evidence if p.endswith(".md")]
    assert not md_evidence, f"Found .md evidence paths: {md_evidence}"


# ── Integration tests ─────────────────────────────────────────────────


@pytest.mark.integration
def test_cli_help_capture(real_output: dict) -> None:
    cli_help_check = next(
        (c for c in real_output["checks"] if c["check_id"] == "cli_help_succeeds"), None
    )
    assert cli_help_check is not None, "cli_help_succeeds check missing"
    assert "exit code" in cli_help_check["detail"] or cli_help_check["status"] == "pass"
    assert "cli_help_succeeds" in real_output["commands_run"]


@pytest.mark.integration
def test_doctor_command_as_subcheck(real_output: dict) -> None:
    doctor_check = next(
        (c for c in real_output["checks"] if c["check_id"] == "doctor_command"), None
    )
    assert doctor_check is not None, "doctor_command check missing"
    assert "doctor_command" in real_output["commands_run"]

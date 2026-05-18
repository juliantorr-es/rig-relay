#!/usr/bin/env python3
"""Rig Relay RC Installability Smoke Test.

Runs targeted checks against a local release-candidate workspace
and emits JSON to stdout.  Call as::

    uv run python scripts/rig_rc_installability_check.py
    uv run python scripts/rig_rc_installability_check.py --strict
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
LICENSE_PATH = REPO_ROOT / "LICENSE"
SCHEMA_VALIDATOR_PATH = REPO_ROOT / "scripts" / "rig_relay_validate_schemas.py"
RELEASE_GATE_VALIDATOR_PATH = REPO_ROOT / "scripts" / "rig_release_gate_validate.py"

REQUIRED_DOCS = ["README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md"]

MARKDOWN_FORBIDDEN_DIRS = [
    "docs/audits",
    "docs/reports",
    "docs/roadmaps",
    "docs/proofs",
]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT
    )


def _resolve_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


_MAX_MARKDOWN_SAMPLE = 5


def _format_markdown_detail(found: list[str]) -> str:
    sample = found[:_MAX_MARKDOWN_SAMPLE]
    suffix = "..." if len(found) > _MAX_MARKDOWN_SAMPLE else ""
    return (
        f"Found {len(found)} .md file(s) in forbidden evidence dirs: {sample}{suffix}"
    )


def _resolve_head_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def _load_pyproject() -> dict[str, Any]:
    raw = PYPROJECT_PATH.read_bytes()
    return tomllib.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Individual checks  (each returns dict with check_id, status, detail, duration_ms)
# ---------------------------------------------------------------------------


def check_pyproject_parseable() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        _load_pyproject()
        return {
            "check_id": "pyproject_parseable",
            "status": "pass",
            "detail": "pyproject.toml parses as valid TOML",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "pyproject_parseable",
            "status": "fail",
            "detail": f"pyproject.toml TOML parse error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_package_metadata() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        proj = _load_pyproject()
        project = proj.get("project", {})
        name = project.get("name", "")
        version = project.get("version", "")
        requires_python = project.get("requires-python", "")
        license_val = project.get("license", None)

        missing: list[str] = []
        if not name:
            missing.append("name")
        if not version:
            missing.append("version")
        if not requires_python:
            missing.append("requires-python")
        if not license_val:
            missing.append("license")
        elif isinstance(license_val, dict):
            if not license_val.get("text", ""):
                missing.append("license.text")

        if missing:
            return {
                "check_id": "package_metadata",
                "status": "fail",
                "detail": f"Missing or empty fields: {', '.join(missing)}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "package_metadata",
            "status": "pass",
            "detail": f"name={name}, version={version}, python_requires={requires_python}, license OK",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "package_metadata",
            "status": "fail",
            "detail": f"Error reading metadata: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_entry_points_exist() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        found: dict[str, bool] = {}
        for ep in eps:
            if ep.group == "console_scripts" and ep.name in {
                "rig-relay",
                "rig-relay-acp",
            }:
                found[ep.name] = True
        missing = [name for name in ("rig-relay", "rig-relay-acp") if name not in found]
        if missing:
            return {
                "check_id": "entry_points_exist",
                "status": "fail",
                "detail": f"Missing entry points: {', '.join(missing)}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "entry_points_exist",
            "status": "pass",
            "detail": "rig-relay and rig-relay-acp entry points resolve",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "entry_points_exist",
            "status": "fail",
            "detail": f"Error checking entry points: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_cli_help_succeeds() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        result = _run(["uv", "run", "rig-relay", "--help"])
        if result.returncode == 0:
            return {
                "check_id": "cli_help_succeeds",
                "status": "pass",
                "detail": "`uv run rig-relay --help` returned exit code 0",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "cli_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay --help` returned exit code {result.returncode}: {result.stderr.strip()[:200]}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "check_id": "cli_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay --help` timed out after {e.timeout}s",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "cli_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay --help` error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_cli_acp_help_succeeds() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        result = _run(["uv", "run", "rig-relay-acp", "--help"])
        if result.returncode == 0:
            return {
                "check_id": "cli_acp_help_succeeds",
                "status": "pass",
                "detail": "`uv run rig-relay-acp --help` returned exit code 0",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "cli_acp_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay-acp --help` returned exit code {result.returncode}: {result.stderr.strip()[:200]}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "check_id": "cli_acp_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay-acp --help` timed out after {e.timeout}s",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "cli_acp_help_succeeds",
            "status": "fail",
            "detail": f"`uv run rig-relay-acp --help` error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_doctor_command() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        result = _run(["uv", "run", "rig-relay", "doctor"])
        if result.returncode == 0:
            return {
                "check_id": "doctor_command",
                "status": "pass",
                "detail": "`uv run rig-relay doctor` returned exit code 0",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "doctor_command",
            "status": "fail",
            "detail": f"`uv run rig-relay doctor` returned exit code {result.returncode}: {result.stderr.strip()[:200]}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "check_id": "doctor_command",
            "status": "fail",
            "detail": f"`uv run rig-relay doctor` timed out after {e.timeout}s",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "doctor_command",
            "status": "fail",
            "detail": f"`uv run rig-relay doctor` error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_required_public_docs() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    missing = [d for d in REQUIRED_DOCS if not (REPO_ROOT / d).is_file()]
    if missing:
        return {
            "check_id": "required_public_docs",
            "status": "fail",
            "detail": f"Missing required docs: {', '.join(missing)}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    return {
        "check_id": "required_public_docs",
        "status": "pass",
        "detail": f"All {len(REQUIRED_DOCS)} required public docs present",
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def check_license_consistency() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        proj = _load_pyproject()
        license_field = proj.get("project", {}).get("license", None)
        if not license_field:
            return {
                "check_id": "license_consistency",
                "status": "fail",
                "detail": "No license field in pyproject.toml",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }

        if isinstance(license_field, dict):
            pyproj_license = license_field.get("text", "")
        else:
            pyproj_license = str(license_field)

        agpl_indicators = [
            "AGPL-3.0",
            "GNU AFFERO",
            "GNU AFFERO GENERAL PUBLIC LICENSE",
        ]
        try:
            license_text = LICENSE_PATH.read_text(encoding="utf-8")
        except OSError as e:
            return {
                "check_id": "license_consistency",
                "status": "fail",
                "detail": f"Cannot read LICENSE file: {e}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }

        pyproj_is_agpl = any(ind in pyproj_license for ind in agpl_indicators)
        file_is_agpl = any(ind in license_text for ind in agpl_indicators)

        if pyproj_is_agpl and file_is_agpl:
            return {
                "check_id": "license_consistency",
                "status": "pass",
                "detail": f"pyproject.toml license ({pyproj_license}) matches LICENSE file (AGPL-3.0)",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "license_consistency",
            "status": "fail",
            "detail": f"License mismatch: pyproject={pyproj_license!r}, "
            f"LICENSE file indicates AGPL-3.0={file_is_agpl}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "license_consistency",
            "status": "fail",
            "detail": f"Error checking license consistency: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_schema_validation() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        result = _run(
            ["uv", "run", "python", str(SCHEMA_VALIDATOR_PATH.relative_to(REPO_ROOT))],
            timeout=30,
        )
        if result.returncode == 0:
            return {
                "check_id": "schema_validation",
                "status": "pass",
                "detail": "Schema validation script passed",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        detail = f"Schema validation script failed (exit code {result.returncode})"
        output = (result.stdout + result.stderr).strip()
        if output:
            # Extract the summary lines
            parts: list[str] = []
            for line in output.splitlines():
                stripped = line.strip()
                if stripped.startswith("Total:") or stripped.startswith("Failed:"):
                    parts.append(stripped)
            if parts:
                detail += " — " + ", ".join(parts)
        return {
            "check_id": "schema_validation",
            "status": "fail",
            "detail": detail,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "check_id": "schema_validation",
            "status": "fail",
            "detail": f"Schema validation timed out after {e.timeout}s",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "schema_validation",
            "status": "fail",
            "detail": f"Schema validation error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_release_gate_validator() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        if not RELEASE_GATE_VALIDATOR_PATH.is_file():
            return {
                "check_id": "release_gate_validator",
                "status": "fail",
                "detail": "scripts/rig_release_gate_validate.py does not exist",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        raw = RELEASE_GATE_VALIDATOR_PATH.read_text(encoding="utf-8")
        compile(raw, str(RELEASE_GATE_VALIDATOR_PATH), "exec")
        return {
            "check_id": "release_gate_validator",
            "status": "pass",
            "detail": "scripts/rig_release_gate_validate.py exists and is parseable Python",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except SyntaxError as e:
        return {
            "check_id": "release_gate_validator",
            "status": "fail",
            "detail": f"scripts/rig_release_gate_validate.py has syntax error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "release_gate_validator",
            "status": "fail",
            "detail": f"Error checking release gate validator: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_no_markdown_evidence() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    found: list[str] = []
    for d in MARKDOWN_FORBIDDEN_DIRS:
        dir_path = REPO_ROOT / d
        if not dir_path.is_dir():
            continue
        for md_file in dir_path.rglob("*.md"):
            found.append(str(md_file.relative_to(REPO_ROOT)))
    if found:
        return {
            "check_id": "no_markdown_evidence",
            "status": "warn",
            "detail": _format_markdown_detail(found),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    return {
        "check_id": "no_markdown_evidence",
        "status": "pass",
        "detail": "No .md files found in forbidden evidence directories",
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def check_dogfood_readiness_distinction() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    golden_path_path = (
        REPO_ROOT
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_reviewer_golden_path.v1.json"
    )
    if not golden_path_path.is_file():
        return {
            "check_id": "dogfood_readiness_distinction",
            "status": "fail",
            "detail": (
                "Dogfood golden path artifact missing: "
                "docs/json/release_candidate/rc_reviewer_golden_path.v1.json. "
                "Installability smoke test alone is insufficient for RC readiness."
            ),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    try:
        golden_path = json.loads(golden_path_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "check_id": "dogfood_readiness_distinction",
            "status": "fail",
            "detail": f"Golden path artifact is malformed JSON: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    overall = golden_path.get("overall_status", "not_verified")
    blocked_steps = [
        s["step_id"]
        for s in golden_path.get("steps", [])
        if s.get("status") == "blocked" and s.get("blocking_failure_conditions")
    ]
    not_verified_steps = [
        s["step_id"]
        for s in golden_path.get("steps", [])
        if s.get("status") == "not_verified" and s.get("blocking_failure_conditions")
    ]

    if overall == "passing":
        return {
            "check_id": "dogfood_readiness_distinction",
            "status": "pass",
            "detail": (
                "Dogfood golden path is passing. "
                "Installability smoke test is supplemented by dogfood operational readiness."
            ),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    if blocked_steps:
        return {
            "check_id": "dogfood_readiness_distinction",
            "status": "warn",
            "detail": (
                f"Installability smoke may pass but dogfood readiness is BLOCKED. "
                f"{len(blocked_steps)} blocked step(s): {', '.join(blocked_steps)}. "
                f"Do not treat installability-only checks as RC readiness."
            ),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    return {
        "check_id": "dogfood_readiness_distinction",
        "status": "warn",
        "detail": (
            f"Installability smoke may pass but dogfood golden path is '{overall}'. "
            f"{len(not_verified_steps)} steps not yet verified by a human reviewer. "
            f"Do not treat installability-only checks as RC readiness."
        ),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def check_version_ascii() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        proj = _load_pyproject()
        version = proj.get("project", {}).get("version", "")
        if not version:
            return {
                "check_id": "version_ascii",
                "status": "fail",
                "detail": "No version field in pyproject.toml",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        if version.isascii():
            return {
                "check_id": "version_ascii",
                "status": "pass",
                "detail": f"Version {version!r} is ASCII-only",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "version_ascii",
            "status": "fail",
            "detail": f"Version {version!r} contains non-ASCII characters",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "version_ascii",
            "status": "fail",
            "detail": f"Error checking version ASCII: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_python_version_constraint() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    try:
        proj = _load_pyproject()
        requires_python = proj.get("project", {}).get("requires-python", "")
        if not requires_python:
            return {
                "check_id": "python_version_constraint",
                "status": "fail",
                "detail": "No requires-python field in pyproject.toml",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }

        from packaging.specifiers import SpecifierSet

        spec = SpecifierSet(requires_python)
        if "3.12" in spec or any(
            f"3.{v}" in spec for v in range(12, 20) for _ in [None]
        ):
            return {
                "check_id": "python_version_constraint",
                "status": "pass",
                "detail": f"requires-python={requires_python!r} correctly includes >=3.12",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "python_version_constraint",
            "status": "fail",
            "detail": f"requires-python={requires_python!r} does not require >=3.12",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "python_version_constraint",
            "status": "fail",
            "detail": f"Error checking python version constraint: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def check_demo_commands_not_in_product_help() -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    forbidden = ["demo-seed", "demo-doctor", "demo-render-docs"]
    try:
        result = _run(["uv", "run", "rig-relay", "--help"])
        if result.returncode != 0:
            return {
                "check_id": "demo_commands_not_in_product_help",
                "status": "fail",
                "detail": f"`uv run rig-relay --help` returned exit code {result.returncode}: {result.stderr.strip()[:200]}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        found = [cmd for cmd in forbidden if cmd in result.stdout]
        if found:
            return {
                "check_id": "demo_commands_not_in_product_help",
                "status": "fail",
                "detail": f"Demo commands leaked into product --help: {', '.join(found)}",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        return {
            "check_id": "demo_commands_not_in_product_help",
            "status": "pass",
            "detail": "No demo commands found in product --help output",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "check_id": "demo_commands_not_in_product_help",
            "status": "fail",
            "detail": f"`uv run rig-relay --help` timed out after {e.timeout}s",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:
        return {
            "check_id": "demo_commands_not_in_product_help",
            "status": "fail",
            "detail": f"`uv run rig-relay --help` error: {e}",
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

CHECKS = [
    check_pyproject_parseable,
    check_package_metadata,
    check_entry_points_exist,
    check_cli_help_succeeds,
    check_cli_acp_help_succeeds,
    check_doctor_command,
    check_required_public_docs,
    check_license_consistency,
    check_schema_validation,
    check_release_gate_validator,
    check_no_markdown_evidence,
    check_version_ascii,
    check_python_version_constraint,
    check_dogfood_readiness_distinction,
    check_demo_commands_not_in_product_help,
]


def _compute_status(
    checks: list[dict[str, Any]], strict: bool
) -> tuple[str, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for c in checks:
        if c["status"] == "fail":
            errors.append(f"{c['check_id']}: {c['detail']}")
        elif c["status"] == "warn":
            warnings.append(f"{c['check_id']}: {c['detail']}")
    if errors:
        return "failed", errors, warnings
    if strict and warnings:
        return "failed", errors, warnings
    return "passed", errors, warnings


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-rc-installability-check",
        description="Run RC installability smoke tests and emit JSON to stdout.",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as failures"
    )
    return parser.parse_args(argv)


def _pyproject_metadata() -> tuple[str, str, str]:
    try:
        proj = _load_pyproject()
        project = proj.get("project", {})
        return (
            project.get("name", "unknown"),
            project.get("version", "unknown"),
            project.get("requires-python", "unknown"),
        )
    except Exception:
        return ("unknown", "unknown", "unknown")


def _build_next_actions(checks: list[dict[str, Any]], strict: bool) -> list[str]:
    actions: list[str] = []
    for c in checks:
        if c["status"] == "fail":
            actions.append(f"Fix: {c['check_id']} — {c['detail']}")
        elif c["status"] == "warn" and strict:
            actions.append(f"Fix: {c['check_id']} — {c['detail']}")
    return actions


_COMMAND_CHECK_IDS = {
    "cli_help_succeeds",
    "cli_acp_help_succeeds",
    "doctor_command",
    "schema_validation",
    "demo_commands_not_in_product_help",
}


def run_checks(strict: bool = False) -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    branch = _resolve_branch()
    head_sha = _resolve_head_sha()
    pkg_name, pkg_version, requires_python = _pyproject_metadata()

    checks: list[dict[str, Any]] = []
    commands_run: list[str] = []
    for check_fn in CHECKS:
        result = check_fn()
        checks.append(result)
        if result["check_id"] in _COMMAND_CHECK_IDS:
            commands_run.append(result["check_id"])

    overall_status, errors, warnings = _compute_status(checks, strict)
    total_ms = int((time.monotonic() - t0) * 1000)
    required_next_actions = (
        _build_next_actions(checks, strict) if overall_status != "passed" else []
    )

    return {
        "schema_version": "rig.release_candidate.installability_check.v1",
        "generated_at": _now_iso(),
        "branch": branch,
        "head_sha": head_sha,
        "package_name": pkg_name,
        "package_version": pkg_version,
        "python_requires": requires_python,
        "overall_status": overall_status,
        "cli_entry_points_checked": ["rig-relay", "rig-relay-acp"],
        "public_docs_checked": list(REQUIRED_DOCS),
        "license_status": next(
            (c["status"] for c in checks if c["check_id"] == "license_consistency"),
            "fail",
        ),
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "evidence_paths": [],
        "commands_run": commands_run,
        "duration_ms": total_ms,
        "required_next_actions": required_next_actions,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_checks(strict=args.strict)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

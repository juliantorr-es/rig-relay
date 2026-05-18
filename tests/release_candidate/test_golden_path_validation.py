from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN_PATH_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "release_candidate"
    / "rc_reviewer_golden_path.v1.json"
)
_SCHEMA_PATH = (
    _REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.release_candidate.reviewer_golden_path.v1.schema.json"
)
_VALIDATOR_PATH = _REPO_ROOT / "scripts" / "rig_release_gate_validate.py"
_READINESS_GATE_PATH = (
    _REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
)


def _load_golden_path() -> dict:
    return json.loads(_GOLDEN_PATH_PATH.read_text(encoding="utf-8"))


def _run_validator() -> dict:
    import subprocess

    result = subprocess.run(
        ["uv", "run", "python", str(_VALIDATOR_PATH)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=60,
    )
    return json.loads(result.stdout)


# ── Contract tests ────────────────────────────────────────────────────


@pytest.mark.contract
def test_golden_path_validates_against_schema() -> None:
    import jsonschema

    golden_path = _load_golden_path()
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(golden_path))
    assert len(errors) == 0, (
        f"Golden path failed schema validation: {'; '.join(e.message for e in errors)}"
    )


@pytest.mark.contract
def test_golden_path_has_all_required_steps() -> None:
    golden_path = _load_golden_path()
    step_ids = {s["step_id"] for s in golden_path["steps"]}

    required_steps = {
        "gp_install_sync",
        "gp_understand_product",
        "gp_launch_server",
        "gp_launch_frontend",
        "gp_frontend_primary_surface",
        "gp_run_real_work_lane",
        "gp_feral_subprocess_accountability",
        "gp_bash_rerouting_transparency",
        "gp_telemetry_degradation_visibility",
        "gp_context_assembler_availability",
        "gp_structured_evidence_inspection",
        "gp_no_markdown_evidence_leakage",
        "gp_debug_packet_quarantine",
        "gp_coordination_watchable",
        "gp_shutdown_cleanly",
        "gp_see_blocked_deferred_state",
        "gp_release_gate_validator_baseline",
    }
    missing = required_steps - step_ids
    assert not missing, f"Missing required golden path steps: {missing}"


@pytest.mark.contract
def test_golden_path_blocking_steps_have_failure_conditions() -> None:
    golden_path = _load_golden_path()
    for step in golden_path["steps"]:
        if step["status"] == "blocked":
            assert step.get("blocking_failure_conditions"), (
                f"Blocked step {step['step_id']} must have blocking_failure_conditions"
            )


@pytest.mark.contract
def test_golden_path_all_steps_have_status() -> None:
    golden_path = _load_golden_path()
    valid_statuses = {"passing", "failing", "blocked", "not_verified", "skipped"}
    for step in golden_path["steps"]:
        assert step.get("status") in valid_statuses, (
            f"Step {step['step_id']} has invalid status: {step.get('status')}"
        )


# ── Integration tests ─────────────────────────────────────────────────


@pytest.mark.integration
def test_release_gate_cannot_promote_when_golden_path_blocked() -> None:
    result = _run_validator()
    assert result["verdict"] != "PASS", (
        f"Validator returned {result['verdict']} but golden path is blocked. "
        f"PROMOTE must not be possible when golden path has blocking steps."
    )


@pytest.mark.integration
def test_release_gate_verdict_is_fail_when_golden_path_blocked() -> None:
    result = _run_validator()
    golden_path = _load_golden_path()
    if golden_path["overall_status"] != "passing":
        assert result["verdict"] in {"FAIL", "BLOCKED"}, (
            f"Validator returned {result['verdict']} but golden path "
            f"overall_status is '{golden_path['overall_status']}'. "
            f"Verdict must be FAIL or BLOCKED when golden path is not passing."
        )


@pytest.mark.integration
def test_validator_reports_golden_path_blocked_steps() -> None:
    result = _run_validator()
    errors_text = " ".join(result.get("errors", []))
    assert "golden path" in errors_text.lower(), (
        "Validator errors must mention golden path when it has blocking steps"
    )


# ── Real-artifact tests ───────────────────────────────────────────────


def test_golden_path_evidence_paths_exist() -> None:
    golden_path = _load_golden_path()
    missing: list[str] = []
    for ep in golden_path.get("evidence_paths", []):
        full_path = _REPO_ROOT / ep
        if not full_path.exists():
            missing.append(ep)
    assert not missing, f"Golden path evidence paths missing: {missing}"


def test_golden_path_debug_quarantine_is_blocked_not_skipped() -> None:
    golden_path = _load_golden_path()
    for step in golden_path["steps"]:
        if step["step_id"] == "gp_debug_packet_quarantine":
            assert step["status"] in {"passing", "blocked", "not_verified"}, (
                f"Debug packet quarantine step must be 'passing', 'blocked', or 'not_verified', "
                f"got '{step['status']}'"
            )
            if step["status"] == "blocked":
                assert step.get("blocking_failure_conditions"), (
                    "Blocked step must have blocking_failure_conditions"
                )


def test_golden_path_dogfood_phase_6_references_golden_path() -> None:
    gate = json.loads(_READINESS_GATE_PATH.read_text(encoding="utf-8"))
    phase_6 = next(
        (
            p
            for p in gate["phases"]
            if p["phase_id"] == "phase_6_dogfood_operational_readiness"
        ),
        None,
    )
    assert phase_6 is not None, "Phase 6 (dogfood operational readiness) must exist"
    evidence = phase_6.get("required_evidence", [])
    assert "docs/json/release_candidate/rc_reviewer_golden_path.v1.json" in evidence, (
        "Phase 6 required_evidence must include the golden path artifact"
    )


# ── Adversarial tests ─────────────────────────────────────────────────


@pytest.mark.adversarial
def test_no_markdown_evidence_in_golden_path() -> None:
    golden_path = _load_golden_path()
    markdown_paths: list[str] = []
    for ep in golden_path.get("evidence_paths", []):
        if ep.endswith(".md") or ep.endswith(".mdx") or ep.endswith(".markdown"):
            allowed = {
                "README.md",
                "AGENTS.md",
                "LICENSE",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "CHANGELOG.md",
                "CODE_OF_CONDUCT.md",
                "THIRD_PARTY_NOTICES.md",
                "ATTRIBUTION.md",
                "UPSTREAM.md",
            }
            if ep not in allowed:
                markdown_paths.append(ep)
    assert not markdown_paths, (
        f"Golden path evidence_paths contains forbidden Markdown: {markdown_paths}"
    )


@pytest.mark.adversarial
def test_installability_alone_cannot_satisfy_dogfood() -> None:
    import subprocess

    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(_REPO_ROOT / "scripts" / "rig_rc_installability_check.py"),
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    installability = json.loads(result.stdout)
    dogfood_check = next(
        (
            c
            for c in installability["checks"]
            if c["check_id"] == "dogfood_readiness_distinction"
        ),
        None,
    )
    assert dogfood_check is not None, (
        "Installability check must include dogfood_readiness_distinction"
    )
    if installability["overall_status"] == "passed":
        golden_path = _load_golden_path()
        if golden_path["overall_status"] == "passing":
            assert dogfood_check["status"] == "pass", (
                "If installability passes and the golden path is fully passing, "
                "dogfood_distinction must also pass"
            )
        else:
            assert dogfood_check["status"] == "warn", (
                "If installability passes but the golden path is not yet verified, "
                "dogfood_distinction must warn instead of implying readiness"
            )
    else:
        assert dogfood_check["status"] in {"warn", "fail"}, (
            f"Dogfood distinction check must warn or fail when golden path is not passing. "
            f"Got status={dogfood_check['status']}, "
            f"golden_path_overall_status=blocked"
        )


# ── Substrate tests ───────────────────────────────────────────────────


@pytest.mark.substrate
def test_golden_path_schema_json_is_valid_json() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(schema, dict)
    assert "$schema" in schema
    assert "$id" in schema

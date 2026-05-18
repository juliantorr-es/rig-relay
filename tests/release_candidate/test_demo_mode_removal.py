from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent.parent / "scripts"
VALIDATOR_PATH = SCRIPTS_DIR / "rig_release_gate_validate.py"
GOLDEN_PATH_CHECKER = SCRIPTS_DIR / "rig_rc_golden_path_check.py"
SCHEMAS_SRC = THIS_DIR.parent.parent / "docs" / "schemas"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _repr_root(tmp: Path) -> Path:
    (tmp / "docs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_candidate").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_gate").mkdir(parents=True, exist_ok=True)

    for name in [
        "rig.release_gate.readiness.v1.schema.json",
        "rig.release_gate.blocker.v1.schema.json",
        "rig.release_gate.validation_run.v1.schema.json",
        "rig.release_gate.phase.v1.schema.json",
        "rig.release_candidate.reviewer_golden_path.v1.schema.json",
        "rig.release_candidate.installability_check.v1.schema.json",
    ]:
        src = SCHEMAS_SRC / name
        if src.exists():
            (tmp / "docs" / "schemas" / name).write_text(src.read_text())

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True
    )
    (tmp / "dummy.txt").write_text("test")
    subprocess.run(
        ["git", "add", "dummy.txt"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )
    return tmp


def _get_head(tmp: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
    ).strip()


def _write_minimal_gate(tmp: Path) -> Path:
    head = _get_head(tmp)
    gate = {
        "schema_version": "rig.release_gate.readiness.v1",
        "gate_id": "test_gate",
        "repository": "",
        "head_sha": head,
        "branch": "test",
        "generated_at": "2026-05-17T00:00:00Z",
        "overall_status": "unknown",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "unknown",
                "owner_surface": "test",
                "source_commit": head,
            }
        ],
        "policy": {
            "allowed_markdown_exceptions": [
                "AGENTS.md",
                "README.md",
                "LICENSE",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "CODE_OF_CONDUCT.md",
                "CHANGELOG.md",
                "THIRD_PARTY_NOTICES.md",
                "ATTRIBUTION.md",
                "UPSTREAM.md",
            ]
        },
    }
    p = tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    p.write_text(json.dumps(gate, indent=2))
    return p


def _write_blockers(tmp: Path, entries: list[dict]) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _write_validation_runs(tmp: Path, entries: list[dict]) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _write_deferred_risks(tmp: Path) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_deferred_risks.v1.jsonl"
    p.write_text("")
    return p


def _write_installability(tmp: Path, overall: str = "passed") -> Path:
    p = (
        tmp
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_installability_verdict.v1.json"
    )
    p.write_text(
        json.dumps({
            "schema_version": "rig.release_candidate.installability_check.v1",
            "generated_at": "2026-05-17T00:00:00Z",
            "branch": "test",
            "head_sha": _get_head(tmp),
            "package_name": "test",
            "package_version": "1.0",
            "python_requires": ">=3.12",
            "overall_status": overall,
            "cli_entry_points_checked": ["rig-relay"],
            "public_docs_checked": ["README.md"],
            "license_status": "pass",
            "checks": [],
            "errors": [],
            "warnings": [],
            "evidence_paths": [],
            "commands_run": [],
            "duration_ms": 100,
            "required_next_actions": [],
        })
    )
    return p


def _write_golden_path(
    tmp: Path,
    steps: list[dict],
    evidence_paths: list[str] | None = None,
    overall: str = "blocked",
) -> Path:
    head = _get_head(tmp)
    gp = {
        "schema_version": "rig.release_candidate.reviewer_golden_path.v1",
        "golden_path_id": "rc_dogfood_v1",
        "generated_at": "2026-05-17T00:00:00Z",
        "head_sha": head,
        "branch": "test",
        "title": "Test Golden Path",
        "description": "Test",
        "overall_status": overall,
        "steps": steps,
        "evidence_paths": evidence_paths if evidence_paths is not None else [],
    }
    p = tmp / "docs" / "json" / "release_candidate" / "rc_reviewer_golden_path.v1.json"
    p.write_text(json.dumps(gp, indent=2))
    return p


def _make_step(
    step_id: str,
    status: str = "not_verified",
    validation_method: str = "manual_review",
    **overrides,
) -> dict:
    base = {
        "step_id": step_id,
        "user_goal": f"Goal for {step_id}",
        "command_or_ui_action": f"Action for {step_id}",
        "expected_result": f"Result for {step_id}",
        "evidence_path": f"evidence/{step_id}.json",
        "blocking_failure_conditions": ["failure condition"],
        "status": status,
        "validation_method": validation_method,
        "phase_id": "phase_6_dogfood_operational_readiness",
    }
    base.update(overrides)
    if isinstance(base["evidence_path"], Path):
        base["evidence_path"] = str(base["evidence_path"])
    return base


def _run_validator(tmp: Path) -> dict:
    gate_p = str(tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json")
    blockers_p = str(tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl")
    vruns_p = str(
        tmp / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR_PATH),
            "--repo-root",
            str(tmp),
            "--readiness-gate",
            gate_p,
            "--blockers",
            blockers_p,
            "--validation-runs",
            vruns_p,
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=30,
    )
    return json.loads(proc.stdout)


def _run_golden_path_checker(tmp: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(GOLDEN_PATH_CHECKER), "--repo-root", str(tmp)],
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=30,
    )
    return json.loads(proc.stdout)


# ── Contract tests ─────────────────────────────────────────────────────


@pytest.mark.contract
class TestDemoModeRemovalContract:
    def test_release_gate_validator_rejects_demo_artifact_as_rc_evidence(
        self, tmp_path: Path
    ) -> None:
        tmp = _repr_root(tmp_path)
        demo_file = tmp / ".build" / "rig-relay" / "demo" / "something.json"
        demo_file.parent.mkdir(parents=True)
        demo_file.write_text("{}")
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(
            tmp, [], evidence_paths=[".build/rig-relay/demo/something.json"]
        )
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        result = _run_validator(tmp)
        errors = result.get("errors", [])
        assert any("DEMO EVIDENCE REJECTED" in e for e in errors), (
            f"No DEMO EVIDENCE REJECTED error found in: {errors}"
        )

    def test_golden_path_checker_rejects_demo_evidence(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(
            tmp,
            [
                _make_step(
                    "gp_no_demo_evidence",
                    "not_verified",
                    validation_method="automated_script",
                    blocking_failure_conditions=[
                        ".build/rig-relay/demo/ in evidence_paths"
                    ],
                )
            ],
            evidence_paths=[".build/rig-relay/demo/report.json"],
        )
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        result = _run_golden_path_checker(tmp)
        demo_steps = [
            sr
            for sr in result.get("step_results", [])
            if sr.get("step_id") == "gp_no_demo_evidence"
        ]
        assert len(demo_steps) == 1
        assert demo_steps[0]["automated_check_passed"] is False

    def test_demo_commands_under_dev_namespace(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "rig-relay", "dev", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        help_text = proc.stdout
        assert "demo-seed" in help_text, (
            f"demo-seed not found in dev --help: {help_text}"
        )
        assert "demo-doctor" in help_text, (
            f"demo-doctor not found in dev --help: {help_text}"
        )
        assert "demo-render-docs" in help_text, (
            f"demo-render-docs not found in dev --help: {help_text}"
        )


# ── Real-artifact tests ────────────────────────────────────────────────


@pytest.mark.real_artifact
class TestDemoModeRemovalRealArtifact:
    def test_readme_quick_start_does_not_contain_demo_commands(self) -> None:
        readme_path = REPO_ROOT / "README.md"
        content = readme_path.read_text(encoding="utf-8")
        assert "demo-seed" not in content, "README.md contains demo-seed"
        assert "demo-doctor" not in content, "README.md contains demo-doctor"
        assert "demo-render-docs" not in content, "README.md contains demo-render-docs"

    @pytest.mark.timeout(60)
    def test_cli_help_does_not_present_demo_as_first_run_path(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "rig-relay", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        help_text = proc.stdout
        assert "demo-seed" not in help_text, (
            f"CLI --help contains demo-seed: {help_text}"
        )
        assert "demo-doctor" not in help_text, (
            f"CLI --help contains demo-doctor: {help_text}"
        )
        assert "demo-render-docs" not in help_text, (
            f"CLI --help contains demo-render-docs: {help_text}"
        )

    def test_release_candidate_tests_dont_use_demo_data(self) -> None:
        this_file = Path(__file__).resolve()
        test_files = [
            tf
            for tf in (REPO_ROOT / "tests" / "release_candidate").glob("*.py")
            if tf.resolve() != this_file
        ]
        playwright_path = (
            REPO_ROOT / "tests" / "desktop" / "test_playwright_frontend_product_path.py"
        )
        if playwright_path.exists():
            test_files.append(playwright_path)

        forbidden_patterns = [
            "from rig_relay.cli.demo_commands import",
            "demo-seed",
            "demo-doctor",
            "demo-render-docs",
            "build_demo_ralph_reports",
        ]

        for tf in test_files:
            content = tf.read_text(encoding="utf-8")
            for pat in forbidden_patterns:
                assert pat not in content, (
                    f"{tf.relative_to(REPO_ROOT)} contains forbidden pattern: {pat}"
                )


# ── Substrate test ─────────────────────────────────────────────────────


@pytest.mark.substrate
class TestDemoModeRemovalSubstrate:
    def test_remaining_demo_fixtures_marked_non_rc(self) -> None:
        demo_dir = REPO_ROOT / ".build" / "rig-relay" / "demo"
        if not demo_dir.is_dir():
            return

        fixture_files = list(demo_dir.glob("**/*"))
        assert fixture_files, "Demo directory exists but contains no files to validate"
        for f in fixture_files:
            if f.is_file():
                content = f.read_text(encoding="utf-8")
                lower = content.lower()
                has_demo_label = any(
                    marker in lower
                    for marker in [
                        "demo",
                        "demo-synthetic",
                        "non-rc",
                        "dev only",
                        "not for rc",
                        "non_rc_fixture",
                        "source-demo",
                    ]
                )
                is_json_demo = f.suffix == ".json" and "demo" in f.parent.name.lower()
                assert has_demo_label or is_json_demo, (
                    f"{f.relative_to(REPO_ROOT)} is a demo fixture not clearly labeled as non-RC"
                )

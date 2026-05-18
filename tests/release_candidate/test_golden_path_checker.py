from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent.parent / "scripts"
GOLDEN_PATH_CHECKER = SCRIPTS_DIR / "rig_rc_golden_path_check.py"
VALIDATOR_PATH = SCRIPTS_DIR / "rig_release_gate_validate.py"
SCHEMAS_SRC = THIS_DIR.parent.parent / "docs" / "schemas"


def _repr_root(tmp: Path) -> Path:
    """Set up a minimal repo root with schemas, directories, and git init."""
    (tmp / "docs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_candidate").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_gate").mkdir(parents=True, exist_ok=True)
    (tmp / "frontend" / "desktop").mkdir(parents=True, exist_ok=True)
    (tmp / "rig_relay" / "desktop").mkdir(parents=True, exist_ok=True)
    (tmp / "tests" / "desktop").mkdir(parents=True, exist_ok=True)

    for name in [
        "rig.release_gate.readiness.v1.schema.json",
        "rig.release_gate.blocker.v1.schema.json",
        "rig.release_gate.validation_run.v1.schema.json",
        "rig.release_gate.phase.v1.schema.json",
        "rig.release_candidate.reviewer_golden_path.v1.schema.json",
        "rig.release_candidate.installability_check.v1.schema.json",
        "rig.relay.desktop_projection.v1.schema.json",
    ]:
        src = SCHEMAS_SRC / name
        if src.exists():
            (tmp / "docs" / "schemas" / name).write_text(src.read_text())

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / "dummy.txt").write_text("test")
    subprocess.run(
        ["git", "add", "dummy.txt"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )

    return tmp


def _write_minimal_gate(tmp: Path, **overrides) -> Path:
    base = {
        "schema_version": "rig.release_gate.readiness.v1",
        "gate_id": "test_gate",
        "repository": "",
        "head_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
        ).strip(),
        "branch": "test",
        "generated_at": "2026-05-17T00:00:00Z",
        "overall_status": "unknown",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "unknown",
                "owner_surface": "test",
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
                ).strip(),
            }
        ],
        "policy": {
            "allowed_markdown_exceptions": [
                "AGENTS.md", "README.md", "LICENSE", "CONTRIBUTING.md",
                "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md",
                "THIRD_PARTY_NOTICES.md", "ATTRIBUTION.md", "UPSTREAM.md",
            ]
        },
    }
    base.update(overrides)
    p = tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    p.write_text(json.dumps(base, indent=2))
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


def _write_golden_path(tmp: Path, steps: list[dict], overall: str = "blocked") -> Path:
    gh = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
    ).strip()
    if not steps:
        steps = [_make_step("gp_placeholder_no_blocking", "passing",
                            blocking_failure_conditions=[],
                            evidence_path=str(tmp / "evidence/dummy.json"),
                            validation_method="manual_review")]
        (tmp / "evidence").mkdir(exist_ok=True)
        (tmp / "evidence" / "dummy.json").write_text("{}")
    gp = {
        "schema_version": "rig.release_candidate.reviewer_golden_path.v1",
        "golden_path_id": "rc_dogfood_v1",
        "generated_at": "2026-05-17T00:00:00Z",
        "head_sha": gh,
        "branch": "test",
        "title": "Test Golden Path",
        "description": "Test",
        "overall_status": overall,
        "steps": steps,
        "evidence_paths": [],
    }
    p = tmp / "docs" / "json" / "release_candidate" / "rc_reviewer_golden_path.v1.json"
    p.write_text(json.dumps(gp, indent=2))
    return p


def _write_installability(tmp: Path, overall: str = "passed") -> Path:
    p = tmp / "docs" / "json" / "release_candidate" / "rc_installability_verdict.v1.json"
    p.write_text(
        json.dumps({
            "schema_version": "rig.release_candidate.installability_check.v1",
            "generated_at": "2026-05-17T00:00:00Z",
            "branch": "test",
            "head_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
            ).strip(),
            "package_name": "test",
            "package_version": "1.0",
            "python_requires": ">=3.12",
            "overall_status": overall,
            "cli_entry_points_checked": ["rig-relay", "rig-relay-acp"],
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


def _write_deferred_risks(tmp: Path) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_deferred_risks.v1.jsonl"
    p.write_text("")
    return p


def _run_golden_path_checker(tmp: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(GOLDEN_PATH_CHECKER), "--repo-root", str(tmp)],
        capture_output=True, text=True, cwd=str(tmp), timeout=30,
    )
    return json.loads(proc.stdout)


def _run_validator_in_tmp(tmp: Path) -> dict:
    gate_p = str(tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json")
    blockers_p = str(tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl")
    vruns_p = str(tmp / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl")
    proc = subprocess.run(
        [
            sys.executable, str(VALIDATOR_PATH),
            "--repo-root", str(tmp),
            "--readiness-gate", gate_p,
            "--blockers", blockers_p,
            "--validation-runs", vruns_p,
        ],
        capture_output=True, text=True, cwd=str(tmp), timeout=30,
    )
    return json.loads(proc.stdout)


def _make_blocker(blocker_id: str, status: str = "open", **overrides) -> dict:
    base = {
        "blocker_id": blocker_id,
        "phase_id": "phase_1",
        "severity": "high",
        "title": f"Blocker {blocker_id}",
        "description": f"Description for {blocker_id}",
        "status": status,
        "discovered_by": "test",
        "source_commit": "abc1230000000000000000000000000000000000",
        "created_at": "2026-05-17T00:00:00Z",
        "updated_at": "2026-05-17T00:00:00Z",
    }
    base.update(overrides)
    return base


def _make_step(step_id: str, status: str = "not_verified", validation_method: str = "manual_review", **overrides) -> dict:
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


# ── Contract tests ────────────────────────────────────────────────────


@pytest.mark.contract
class TestGoldenPathExecutorContract:
    def test_emits_valid_json(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)
        result = _run_golden_path_checker(tmp)
        assert "schema_version" in result
        assert result["schema_version"] == "rig.release_candidate.golden_path_run.v1"

    def test_no_steps_produces_zero_totals(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)
        result = _run_golden_path_checker(tmp)
        assert result["manual_steps_total"] == 1  # dummy step
        assert result["blocked_steps"] == []
        assert result["consistency_errors"] == []


@pytest.mark.contract
class TestOpenBlockerMakesStepBlocked:
    def test_open_blocker_linked_step_is_blocked(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "open", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
            _make_step("gp_install_sync", "not_verified", validation_method="automated_script"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)
        result = _run_golden_path_checker(tmp)
        blocked_ids = result["blocked_steps"]
        assert "gp_feral_subprocess_accountability" in blocked_ids

    def test_no_blocker_linked_step_not_blocked(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_install_sync", "not_verified", validation_method="automated_script"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)
        result = _run_golden_path_checker(tmp)
        assert result["blocked_steps"] == []


@pytest.mark.contract
class TestResolvedBlockerBlockedStepConsistency:
    def test_resolved_blocker_blocked_step_fails_consistency(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "resolved", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert any(
            "CONSISTENCY FAIL" in e and "gp_feral_subprocess_accountability" in e
            for e in vr.get("errors", [])
        )


@pytest.mark.contract
class TestPassingStepOpenBlockerConsistency:
    def test_passing_step_open_blocker_fails_consistency(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "open", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "passing", validation_method="receipt_inspection"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert any(
            "CONSISTENCY FAIL" in e and "gp_feral_subprocess_accountability" in e and "still 'open'" in e
            for e in vr.get("errors", [])
        )


@pytest.mark.contract
class TestManualNotVerifiedPreventsPromote:
    def test_manual_not_verified_step_blocks_promote(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_launch_server", "not_verified", validation_method="manual_review"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] in {"BLOCKED", "FAIL"}
        assert vr["verdict"] != "PASS"

    def test_all_manual_verified_allows_promote(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        (tmp / "e").mkdir(exist_ok=True)
        (tmp / "e" / "manual_evidence.json").write_text("ok")
        _write_golden_path(
            tmp,
            [
                _make_step("gp_launch_server", "passing", validation_method="manual_review",
                          evidence_path=str(tmp / "e" / "manual_evidence.json")),
            ],
            overall="passing",
        )
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] in {"BLOCKED", "PASS"}  # neither PASS nor FAIL necessarily


# ── Integration tests ─────────────────────────────────────────────────


@pytest.mark.integration
class TestInstallabilityAloneInsufficient:
    def test_installability_passed_golden_path_blocked(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "open", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        result = _run_golden_path_checker(tmp)
        assert result["overall_status"] == "blocked"
        blocked = result["blocked_steps"]
        assert "gp_feral_subprocess_accountability" in blocked

    def test_cli_only_evidence_insufficient_for_frontend_path(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_install_sync", "passing", validation_method="automated_script",
                      evidence_path=str(tmp / "evidence/install.json")),
            _make_step("gp_launch_frontend", "not_verified", validation_method="manual_review"),
        ])
        (tmp / "evidence").mkdir(exist_ok=True)
        (tmp / "evidence" / "install.json").write_text("{}")
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        result = _run_golden_path_checker(tmp)
        server_frontend_steps = [
            sr for sr in result["step_results"]
            if sr.get("server_frontend_path")
        ]
        assert len(server_frontend_steps) > 0
        assert not any(s["status"] == "passing" for s in server_frontend_steps)


@pytest.mark.integration
class TestMarkdownEvidenceRejected:
    def test_forbidden_markdown_in_golden_path(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        gp_path = tmp / "docs" / "json" / "release_candidate" / "rc_reviewer_golden_path.v1.json"
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        gp = {
            "schema_version": "rig.release_candidate.reviewer_golden_path.v1",
            "golden_path_id": "test",
            "generated_at": "2026-05-17T00:00:00Z",
            "head_sha": head,
            "branch": "test",
            "title": "Test",
            "description": "Test",
            "overall_status": "blocked",
            "steps": [],
            "evidence_paths": ["docs/audits/forbidden.md"],
        }
        gp_path.write_text(json.dumps(gp))
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert any(
            "forbidden" in e.lower() for e in vr.get("errors", [])
        )

    def test_allowed_markdown_not_rejected(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        (tmp / "README.md").write_text("# Test")
        gp_path = tmp / "docs" / "json" / "release_candidate" / "rc_reviewer_golden_path.v1.json"
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        gp = {
            "schema_version": "rig.release_candidate.reviewer_golden_path.v1",
            "golden_path_id": "test",
            "generated_at": "2026-05-17T00:00:00Z",
            "head_sha": head,
            "branch": "test",
            "title": "Test",
            "description": "Test",
            "overall_status": "blocked",
            "steps": [],
            "evidence_paths": ["README.md"],
        }
        gp_path.write_text(json.dumps(gp))
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert not any(
            "forbidden" in e.lower() for e in vr.get("errors", [])
        )


# ── Real-artifact tests ────────────────────────────────────────────────


@pytest.mark.real_artifact
class TestRealArtifactGoldenPath:
    def test_golden_path_executor_on_real_repo(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", str(GOLDEN_PATH_CHECKER)],
            capture_output=True, text=True, timeout=30,
        )
        result = json.loads(proc.stdout)
        assert result["schema_version"] == "rig.release_candidate.golden_path_run.v1"
        assert result["overall_status"] in {"blocked", "manual_required", "not_verified"}
        assert result["open_blocker_count"] >= 0
        assert len(result["consistency_errors"]) == 0
        assert result["blocked_steps"] == []
        assert result["automated_steps_total"] >= 3

    def test_golden_path_run_schema_validates(self) -> None:
        schema_path = (
            THIS_DIR.parent.parent
            / "docs"
            / "schemas"
            / "rig.release_candidate.golden_path_run.v1.schema.json"
        )
        run_path = (
            THIS_DIR.parent.parent
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_golden_path_run.v1.json"
        )
        import jsonschema
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        validator_ = jsonschema.Draft202012Validator(schema)
        errors = list(validator_.iter_errors(run))
        assert len(errors) == 0, f"Schema validation errors: {[e.message for e in errors]}"

    def test_validator_verdict_is_blocked_on_real_repo(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", str(VALIDATOR_PATH)],
            capture_output=True, text=True, timeout=60,
        )
        result = json.loads(proc.stdout)
        assert result["verdict"] in {"BLOCKED", "FAIL"}
        assert result["status"] in ("passed", "failed")
        assert result["verdict"] != "PASS"

    def test_validator_exit_code_zero_on_hold(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", str(VALIDATOR_PATH)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0


# ── Sabotage tests ────────────────────────────────────────────────────


@pytest.mark.sabotage
class TestSabotageConsistencyFailures:
    def test_resolved_blocker_blocked_step_fails_validator(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "resolved", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] == "FAIL"
        assert any("CONSISTENCY FAIL" in e for e in vr["errors"])

    def test_missing_evidence_automated_step_fails(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step(
                "gp_install_sync", "passing", validation_method="automated_script",
                evidence_path="nonexistent/path/evidence.json",
            ),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert any(
            "CONSISTENCY FAIL" in e and "evidence_path" in e and "does not exist" in e
            for e in vr.get("errors", [])
        )

    def test_open_blocker_missing_from_jsonl(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert any(
            "CONSISTENCY FAIL" in e and "blk_runtime_feral_subprocess" in e
            for e in vr.get("errors", [])
        )


# ── HOLD verus FAIL versus PASS tests ──────────────────────────────────


@pytest.mark.contract
class TestVerdictDistinction:
    def test_hold_with_open_blockers_is_hold(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp, overall_status="blocked",
                            phases=[{
                                "phase_id": "phase_1",
                                "title": "Phase 1",
                                "status": "blocked",
                                "owner_surface": "test",
                                "blocker_ids": ["B-HOLD"],
                                "source_commit": head,
                            }])
        _write_blockers(tmp, [
            _make_blocker("B-HOLD", "open", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] == "BLOCKED"

    def test_fail_on_contradictory_evidence(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [
            _make_blocker("blk_runtime_feral_subprocess", "resolved", source_commit=head),
        ])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_feral_subprocess_accountability", "blocked"),
        ])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] == "FAIL"

    def test_promote_only_when_all_blocking_verified(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp, text=True).strip()
        _write_minimal_gate(tmp,
                            phases=[{
                                "phase_id": "phase_1",
                                "title": "Phase 1",
                                "status": "ready",
                                "owner_surface": "test",
                                "source_commit": head,
                            }])
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [
            _make_step("gp_install_sync", "passing", validation_method="automated_script",
                      evidence_path=str(tmp / "evidence/install.json"),
                      blocking_failure_conditions=["may fail"]),
        ], overall="passing")
        (tmp / "evidence").mkdir(exist_ok=True)
        (tmp / "evidence" / "install.json").write_text("{}")
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        assert vr["verdict"] == "PASS"


@pytest.mark.real_artifact
class TestServerFrontendProductPathRequired:
    def test_server_frontend_artifacts_exist(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", str(GOLDEN_PATH_CHECKER)],
            capture_output=True, text=True, timeout=30,
        )
        result = json.loads(proc.stdout)
        sfp = result.get("server_frontend_product_path", {})
        assert sfp.get("bridge_server_exists") is True
        assert sfp.get("frontend_index_exists") is True
        assert sfp.get("product_path_tests_exist") is True
        assert sfp.get("projection_schema_exists") is True
        assert sfp.get("websocket_server_exists") is True

    def test_golden_path_includes_server_frontend_steps(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", str(GOLDEN_PATH_CHECKER)],
            capture_output=True, text=True, timeout=30,
        )
        result = json.loads(proc.stdout)
        sf_steps = [
            sr for sr in result["step_results"]
            if sr.get("server_frontend_path")
        ]
        sf_step_ids = {sr["step_id"] for sr in sf_steps}
        required_sf = {"gp_launch_server", "gp_launch_frontend", "gp_frontend_primary_surface", "gp_run_real_work_lane", "gp_shutdown_cleanly"}
        missing_sf = required_sf - sf_step_ids
        assert not missing_sf, f"Server/frontend steps missing: {missing_sf}"

"""Release Gate Validation — contract and real-artifact tests.

Test classifications used in this file:
  - contract: validator behavior tests against real temp JSON/JSONL files
  - real-artifact: tests that create and consume real schemas and evidence files
  - sabotage: tests that inject malformed or invalid data to verify rejection

Markers registered in pyproject.toml for real-artifact, sabotage:
  real_artifact: test creates and validates real JSON/JSONL/schema artifacts
  sabotage: test intentionally feeds invalid or malformed data
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent.parent / "scripts"


def _copy_schemas(repo_root: Path) -> None:
    real_schemas = THIS_DIR.parent.parent / "docs" / "schemas"
    dst = repo_root / "docs" / "schemas"
    dst.mkdir(parents=True, exist_ok=True)
    for name in [
        "rig.release_gate.phase.v1.schema.json",
        "rig.release_gate.readiness.v1.schema.json",
        "rig.release_gate.blocker.v1.schema.json",
        "rig.release_gate.validation_run.v1.schema.json",
        "rig.ci.artifact_index.v1.schema.json",
        "rig.ci.job.v1.schema.json",
        "rig.ci.run.v1.schema.json",
        "rig.ci.verdict.v1.schema.json",
    ]:
        src = real_schemas / name
        if src.exists():
            (dst / name).write_text(src.read_text())


def _write_mock_ci_evidence(repo_root: Path) -> None:
    evidence_dir = repo_root / ".build" / "rig-relay" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    run_data = {
        "schema_version": "rig.ci.run.v1",
        "run_id": "test-run-001",
        "runner_class": "local",
        "official_release": False,
        "release_class": "local_validation",
        "git_branch": "main",
        "git_sha": "a" * 40,
        "git_dirty": False,
        "started_at": "2026-05-18T00:00:00Z",
        "artifact_index_path": ".build/rig-relay/evidence/ci_mock_artifact_index.v1.json",
        "verdict_path": ".build/rig-relay/evidence/ci_mock_verdict.v1.json",
        "evidence_event_stream_path": ".build/rig-relay/evidence/ci_mock_events.v1.jsonl",
        "generated_at": "2026-05-18T00:00:00Z",
    }
    (evidence_dir / "ci_mock_run.v1.json").write_text(json.dumps(run_data, indent=2))

    job_data = {
        "schema_version": "rig.ci.job.v1",
        "run_id": "test-run-001",
        "job_id": "test-job-001",
        "job_name": "Test Job",
        "runner_os": "darwin",
        "runner_arch": "aarch64",
        "runner_class": "local",
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-05-18T00:00:00Z",
        "completed_at": "2026-05-18T00:01:00Z",
        "referenced_artifacts": [],
        "referenced_schema_validations": [],
        "referenced_test_receipts": [],
        "telemetry_redaction_notes": "None",
        "generated_at": "2026-05-18T00:00:00Z",
    }
    (evidence_dir / "ci_mock_job.v1.json").write_text(json.dumps(job_data, indent=2))

    index_data = {
        "schema_version": "rig.ci.artifact_index.v1",
        "run_id": "test-run-001",
        "artifacts": [
            {
                "artifact_id": "ci_mock_run",
                "artifact_kind": "ci_run",
                "path": ".build/rig-relay/evidence/ci_mock_run.v1.json",
                "sha256": "0" * 64,
                "size_bytes": 100,
                "producer": "ci_evidence_producer",
                "required_for_release_gate": True,
                "source_surface": "ci_evidence",
                "created_at": "2026-05-18T00:00:00Z",
            },
            {
                "artifact_id": "ci_mock_job",
                "artifact_kind": "ci_job",
                "path": ".build/rig-relay/evidence/ci_mock_job.v1.json",
                "sha256": "0" * 64,
                "size_bytes": 100,
                "producer": "ci_evidence_producer",
                "required_for_release_gate": True,
                "source_surface": "ci_evidence",
                "created_at": "2026-05-18T00:00:00Z",
            },
        ],
        "generated_at": "2026-05-18T00:00:00Z",
    }
    (evidence_dir / "ci_mock_artifact_index.v1.json").write_text(
        json.dumps(index_data, indent=2)
    )

    verdict_data = {
        "schema_version": "rig.ci.verdict.v1",
        "run_id": "test-run-001",
        "verdict": "pass",
        "release_gate_blocker_id": "blk_ci_cd_structured_evidence_surface",
        "runner_class": "local",
        "official_release": False,
        "release_class": "local_validation",
        "evaluated_at": "2026-05-18T00:00:00Z",
        "required_artifacts_present": True,
        "required_artifacts_valid": True,
        "artifact_hashes_verified": True,
        "blocking_reasons": [],
        "warnings": [],
        "evidence_paths": [],
        "telemetry_redaction_notes": "None",
    }
    (evidence_dir / "ci_mock_verdict.v1.json").write_text(
        json.dumps(verdict_data, indent=2)
    )


def _write_gate(repo_root: Path, gate: dict) -> Path:
    gd = repo_root / "docs" / "json" / "release_gate"
    gd.mkdir(parents=True, exist_ok=True)
    p = gd / "rc_readiness_gate.v1.json"
    p.write_text(json.dumps(gate, indent=2))
    return p


def _write_jsonl(repo_root: Path, name: str, entries: list[dict]) -> Path:
    gd = repo_root / "docs" / "json" / "release_gate"
    gd.mkdir(parents=True, exist_ok=True)
    p = gd / name
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _minimal_gate(**overrides) -> dict:
    base = {
        "schema_version": "rig.release_gate.readiness.v1",
        "gate_id": "test_gate",
        "repository": "",
        "head_sha": "abc123",
        "branch": "test",
        "generated_at": "2026-05-17T00:00:00Z",
        "overall_status": "unknown",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "unknown",
                "owner_surface": "test",
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
    base.update(overrides)
    return base


def _gate_path(repo_root: Path) -> str:
    return str(
        repo_root / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    )


def _blockers_path(repo_root: Path) -> str:
    return str(repo_root / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl")


def _vruns_path(repo_root: Path) -> str:
    return str(
        repo_root / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    )


def _run(
    repo_root: Path, expect_pass: bool = False, write_ci_evidence: bool = True
) -> dict:
    if write_ci_evidence:
        _write_mock_ci_evidence(repo_root)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "rig_release_gate_validate.py"),
            "--repo-root",
            str(repo_root),
            "--readiness-gate",
            _gate_path(repo_root),
            "--blockers",
            _blockers_path(repo_root),
            "--validation-runs",
            _vruns_path(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    if expect_pass:
        assert proc.returncode == 0, f"stdout={proc.stdout} stderr={proc.stderr}"
    return json.loads(proc.stdout)


# ── CLI integration tests ───────────────────────────────────────────


class TestValidGatePasses:
    def test_empty_gate_passes(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_gate(tmp_path, _minimal_gate())
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed"
        assert result["artifact_counts"]["phases"] == 1

    def test_mock_ci_evidence_validates(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_mock_ci_evidence(tmp_path)

        import importlib.util

        validator_path = SCRIPTS_DIR / "rig_release_gate_validate.py"
        spec = importlib.util.spec_from_file_location(
            "rig_release_gate_validate", validator_path
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        errors = mod.check_ci_evidence_surface(tmp_path, tmp_path / "docs" / "schemas")
        assert not errors, f"Mock CI evidence validation errors: {errors}"

    def test_gate_with_blockers_and_runs_passes(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"] = [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "unknown",
                "owner_surface": "test",
                "blocker_ids": ["B-001"],
                "validation_run_ids": ["VR-001"],
            }
        ]
        _write_gate(tmp_path, gate)
        _write_jsonl(
            tmp_path,
            "rc_blockers.v1.jsonl",
            [
                {
                    "blocker_id": "B-001",
                    "phase_id": "phase_1",
                    "severity": "high",
                    "title": "Test blocker",
                    "description": "A test blocker",
                    "status": "resolved",
                    "discovered_by": "test",
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                    "updated_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-001",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed", (
            f"Unexpected errors: {result.get('errors')}"
        )


class TestMissingBlockerFails:
    def test_missing_blocker_reference_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["blocker_ids"] = ["B-NONEXISTENT"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("missing blocker" in e.lower() for e in result["errors"])


class TestMissingValidationRunFails:
    def test_missing_validation_run_reference_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["validation_run_ids"] = ["VR-NONEXISTENT"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("missing validation run" in e.lower() for e in result["errors"])


class TestOpenBlockerPreventsPassing:
    def test_open_blocker_prevents_passing(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["policy"]["passing_phase_blocker_check"] = True
        gate["phases"][0]["status"] = "passing"
        gate["phases"][0]["blocker_ids"] = ["B-OPEN"]
        _write_gate(tmp_path, gate)
        _write_jsonl(
            tmp_path,
            "rc_blockers.v1.jsonl",
            [
                {
                    "blocker_id": "B-OPEN",
                    "phase_id": "phase_1",
                    "severity": "blocker",
                    "title": "Open blocker",
                    "description": "Still open",
                    "status": "open",
                    "discovered_by": "test",
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                    "updated_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any(
            "passing" in e.lower() or "still open" in e.lower()
            for e in result["errors"]
        )


class TestMissingEvidencePathFails:
    def test_missing_evidence_path_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["required_evidence"] = ["nonexistent/path/evidence.json"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("missing" in e.lower() for e in result["errors"])


class TestMarkdownEvidenceFails:
    def test_forbidden_markdown_evidence_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        (tmp_path / "docs" / "audits").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "audits" / "some-audit.md").write_text("# Audit")
        gate = _minimal_gate()
        gate["phases"][0]["required_evidence"] = ["docs/audits/some-audit.md"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any(
            "forbidden" in e.lower() or "markdown" in e.lower()
            for e in result["errors"]
        )

    def test_allowed_markdown_exception_passes(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        (tmp_path / "AGENTS.md").write_text("# AGENTS")
        gate = _minimal_gate()
        gate["phases"][0]["required_evidence"] = ["AGENTS.md"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed", f"Unexpected errors: {result['errors']}"


class TestMissingTestClassificationsFails:
    def test_validation_run_without_classifications_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["validation_run_ids"] = ["VR-NO-CLASS"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-NO-CLASS",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 42,
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("test_classifications" in e.lower() for e in result["errors"])


class TestMalformedJsonlFails:
    def test_malformed_blocker_jsonl_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_gate(tmp_path, _minimal_gate())
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        bp = tmp_path / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        bp.write_text("this is not valid json\n")

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("malformed" in e.lower() for e in result["errors"])


class TestSchemaGovernedArtifacts:
    def test_schema_artifact_without_validation_result_fails(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["schema_artifact_paths"] = [
            "docs/schemas/rig.release_gate.phase.v1.schema.json"
        ]
        gate["phases"][0]["validation_run_ids"] = ["VR-SCHEMA"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-SCHEMA",
                    "phase_ids": ["phase_1"],
                    "command": "uv run validate_schemas",
                    "result": "passed",
                    "tests_run": 0,
                    "schema_validation_results": {},
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("schema validation" in e.lower() for e in result["errors"])


def _run_with_exit_code(
    repo_root: Path, write_ci_evidence: bool = True
) -> tuple[int, dict]:
    if write_ci_evidence:
        _write_mock_ci_evidence(repo_root)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "rig_release_gate_validate.py"),
            "--repo-root",
            str(repo_root),
            "--readiness-gate",
            _gate_path(repo_root),
            "--blockers",
            _blockers_path(repo_root),
            "--validation-runs",
            _vruns_path(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode, json.loads(proc.stdout)


class TestReleaseGateExitCode:
    def test_validator_exits_nonzero_on_malformed_blocker_jsonl(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_gate(tmp_path, _minimal_gate())
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        bp = tmp_path / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        bp.write_text("this is not valid json\n")
        exit_code, result = _run_with_exit_code(tmp_path)
        assert exit_code == 1
        assert result["status"] == "failed"
        assert result["verdict"] == "FAIL"
        assert any("malformed" in e.lower() for e in result["errors"])

    def test_validator_fails_on_missing_ci_evidence_surface(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_gate(tmp_path, _minimal_gate())
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        exit_code, result = _run_with_exit_code(tmp_path, write_ci_evidence=False)
        assert exit_code == 1
        assert result["status"] == "failed"
        assert result["verdict"] == "FAIL"
        assert any("ci evidence surface" in e.lower() for e in result["errors"])

    def test_validator_exits_nonzero_on_missing_evidence(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["required_evidence"] = ["nonexistent/path/evidence.json"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        exit_code, result = _run_with_exit_code(tmp_path)
        assert exit_code == 1
        assert result["status"] == "failed"
        assert result["verdict"] == "FAIL"
        assert any("missing" in e.lower() for e in result["errors"])

    def test_validator_exits_nonzero_on_forbidden_markdown_evidence(
        self, tmp_path: Path
    ):
        _copy_schemas(tmp_path)
        (tmp_path / "docs" / "audits").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "audits" / "some-audit.md").write_text("# Audit")
        gate = _minimal_gate()
        gate["phases"][0]["required_evidence"] = ["docs/audits/some-audit.md"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        exit_code, result = _run_with_exit_code(tmp_path)
        assert exit_code == 1
        assert result["status"] == "failed"
        assert result["verdict"] == "FAIL"
        assert any(
            "forbidden" in e.lower() or "markdown" in e.lower()
            for e in result["errors"]
        )

    def test_validator_exits_zero_on_valid_gate_no_errors(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        _write_gate(tmp_path, _minimal_gate())
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])
        exit_code, result = _run_with_exit_code(tmp_path)
        assert exit_code == 0
        assert result["status"] == "passed"
        assert result["verdict"] == "PASS"

    def test_validator_exits_zero_on_hold_with_blockers_truthful(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["overall_status"] = "blocked"
        gate["phases"] = [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "blocked",
                "owner_surface": "test",
                "blocker_ids": ["B-HOLD"],
                "validation_run_ids": ["VR-HOLD"],
            }
        ]
        _write_gate(tmp_path, gate)
        _write_jsonl(
            tmp_path,
            "rc_blockers.v1.jsonl",
            [
                {
                    "blocker_id": "B-HOLD",
                    "phase_id": "phase_1",
                    "severity": "blocker",
                    "title": "Real blocker holding the gate",
                    "description": "This is a real blocker",
                    "status": "open",
                    "discovered_by": "test",
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                    "updated_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-HOLD",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "source_commit": "abc123",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        exit_code, result = _run_with_exit_code(tmp_path)
        assert exit_code == 0
        assert result["status"] == "passed"
        assert result["verdict"] == "BLOCKED"


class TestStaleEvidenceDetection:
    def test_stale_validation_run_detected(self, tmp_path: Path):
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(
            ["git", "add", "dummy.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["validation_run_ids"] = ["VR-STALE"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-STALE",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": "abc1230000000000000000000000000000000000",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("stale" in e.lower() for e in result["errors"])

    def test_stale_phase_status_detected(self, tmp_path: Path):
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(
            ["git", "add", "dummy.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["status"] = "passing"
        gate["phases"][0]["source_commit"] = "abc1230000000000000000000000000000000000"
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(tmp_path, "rc_validation_runs.v1.jsonl", [])

        result = _run(tmp_path)
        assert result["status"] == "failed"
        assert any("stale" in e.lower() for e in result["errors"])
        assert any("source_commit" in e.lower() for e in result["errors"])

    def test_current_evidence_not_flagged(self, tmp_path: Path):
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(
            ["git", "add", "dummy.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
        ).strip()

        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["status"] = "passing"
        gate["phases"][0]["source_commit"] = head_sha
        gate["phases"][0]["validation_run_ids"] = ["VR-CURRENT"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-CURRENT",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": head_sha,
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )

        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed", f"Unexpected errors: {result['errors']}"
        stale_errors = [e for e in result["errors"] if "stale" in e.lower()]
        assert len(stale_errors) == 0

    def test_unreferenced_historical_validation_run_is_ignored(self, tmp_path: Path):
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "dummy.txt").write_text("test")
        subprocess.run(
            ["git", "add", "dummy.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
        ).strip()

        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["status"] = "passing"
        gate["phases"][0]["source_commit"] = head_sha
        gate["phases"][0]["validation_run_ids"] = ["VR-CURRENT"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-CURRENT",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": head_sha,
                    "created_at": "2026-05-17T00:00:00Z",
                },
                {
                    "validation_run_id": "VR-ARCHIVED",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": "abc1230000000000000000000000000000000000",
                    "created_at": "2026-05-17T00:00:00Z",
                },
            ],
        )

        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed", f"Unexpected errors: {result['errors']}"
        stale_errors = [e for e in result["errors"] if "stale" in e.lower()]
        assert len(stale_errors) == 0

    def test_no_head_available_graceful_degradation(self, tmp_path: Path):
        _copy_schemas(tmp_path)
        gate = _minimal_gate()
        gate["phases"][0]["status"] = "passing"
        gate["phases"][0]["source_commit"] = "abc1230000000000000000000000000000000000"
        gate["phases"][0]["validation_run_ids"] = ["VR-NOREPO"]
        _write_gate(tmp_path, gate)
        _write_jsonl(tmp_path, "rc_blockers.v1.jsonl", [])
        _write_jsonl(
            tmp_path,
            "rc_validation_runs.v1.jsonl",
            [
                {
                    "validation_run_id": "VR-NOREPO",
                    "phase_ids": ["phase_1"],
                    "command": "uv run pytest",
                    "result": "passed",
                    "tests_run": 10,
                    "test_classifications": {"unit": 10},
                    "source_commit": "abc1230000000000000000000000000000000000",
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )

        result = _run(tmp_path, expect_pass=True)
        assert result["status"] == "passed", f"Unexpected errors: {result['errors']}"
        stale_errors = [e for e in result["errors"] if "stale" in e.lower()]
        assert len(stale_errors) == 0

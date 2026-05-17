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
    ]:
        src = real_schemas / name
        if src.exists():
            (dst / name).write_text(src.read_text())


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


def _run(repo_root: Path, expect_pass: bool = False) -> dict:
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

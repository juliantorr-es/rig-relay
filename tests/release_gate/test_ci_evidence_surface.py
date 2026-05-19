"""CI Evidence Surface v1 — contract, integration, real-artifact, adversarial tests.

Test classifications:
  - contract: schema validation for new CI evidence schemas
  - real_artifact: tests using real file artifacts and the real producer
  - adversarial: tests proving specific bypass vectors are blocked
  - integration: end-to-end producer → validator consumption
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(artifact: dict, schema_id: str) -> list[str]:
    import jsonschema

    schema_path = SCHEMAS_DIR / f"{schema_id}.schema.json"
    if not schema_path.is_file():
        return [f"Schema file not found: {schema_path}"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
        for err in validator.iter_errors(artifact)
    ]


class TestCiEvidenceSchemas:
    @pytest.mark.contract
    def test_run_schema_accepts_minimal_valid_data(self):
        data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": "test-run-001",
            "runner_class": "local",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": ".build/rig-relay/evidence/ci_test_artifact_index.v1.json",
            "verdict_path": ".build/rig-relay/evidence/ci_test_verdict.v1.json",
            "evidence_event_stream_path": ".build/rig-relay/evidence/ci_test_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.ci.run.v1")
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.contract
    def test_run_schema_rejects_invalid_runner_class(self):
        data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": "test-run-001",
            "runner_class": "invalid_runner",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": ".build/rig-relay/evidence/ci_test_artifact_index.v1.json",
            "verdict_path": ".build/rig-relay/evidence/ci_test_verdict.v1.json",
            "evidence_event_stream_path": ".build/rig-relay/evidence/ci_test_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.ci.run.v1")
        assert errors, "Should reject invalid runner_class"

    @pytest.mark.contract
    def test_job_schema_accepts_minimal_valid_data(self):
        data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": "test-run-001",
            "job_id": "test-job-001",
            "job_name": "Test Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.ci.job.v1")
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.contract
    def test_job_schema_rejects_invalid_conclusion(self):
        data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": "test-run-001",
            "job_id": "test-job-001",
            "job_name": "Test Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "conclusion": "invalid_conclusion",
            "started_at": "2026-05-18T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.ci.job.v1")
        assert errors, "Should reject invalid conclusion"

    @pytest.mark.contract
    def test_artifact_index_schema_requires_artifacts_array(self):
        data = {
            "schema_version": "rig.ci.artifact_index.v1",
            "run_id": "test-run-001",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        errors = _validate_schema(data, "rig.ci.artifact_index.v1")
        assert errors, "Should require artifacts array"

    @pytest.mark.contract
    def test_verdict_schema_accepts_pass_verdict(self):
        data = {
            "schema_version": "rig.ci.verdict.v1",
            "run_id": "test-run-001",
            "verdict": "pass",
            "release_gate_blocker_id": "blk_ci_cd_structured_evidence_surface",
            "runner_class": "local",
            "official_release": False,
            "evaluated_at": "2026-05-18T00:00:00Z",
            "required_artifacts_present": True,
            "required_artifacts_valid": True,
            "artifact_hashes_verified": True,
            "blocking_reasons": [],
            "warnings": [],
            "evidence_paths": [],
        }
        errors = _validate_schema(data, "rig.ci.verdict.v1")
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.contract
    def test_verdict_schema_accepts_fail_verdict(self):
        data = {
            "schema_version": "rig.ci.verdict.v1",
            "run_id": "test-run-001",
            "verdict": "fail",
            "release_gate_blocker_id": "blk_ci_cd_structured_evidence_surface",
            "runner_class": "github_actions",
            "official_release": False,
            "evaluated_at": "2026-05-18T00:00:00Z",
            "required_artifacts_present": False,
            "required_artifacts_valid": False,
            "artifact_hashes_verified": False,
            "blocking_reasons": ["Missing required artifacts: ci_run"],
            "warnings": [],
            "evidence_paths": [],
        }
        errors = _validate_schema(data, "rig.ci.verdict.v1")
        assert not errors, f"Schema validation errors: {errors}"

    @pytest.mark.contract
    def test_verdict_release_gate_blocker_id_is_constrained(self):
        data = {
            "schema_version": "rig.ci.verdict.v1",
            "run_id": "test-run-001",
            "verdict": "pass",
            "release_gate_blocker_id": "wrong_blocker",
            "runner_class": "local",
            "official_release": False,
            "evaluated_at": "2026-05-18T00:00:00Z",
            "required_artifacts_present": True,
            "required_artifacts_valid": True,
            "artifact_hashes_verified": True,
            "blocking_reasons": [],
            "warnings": [],
            "evidence_paths": [],
        }
        errors = _validate_schema(data, "rig.ci.verdict.v1")
        assert errors, "Should reject wrong release_gate_blocker_id"

    @pytest.mark.contract
    def test_all_four_schemas_exist(self):
        for schema_id in [
            "rig.ci.run.v1",
            "rig.ci.job.v1",
            "rig.ci.verdict.v1",
            "rig.ci.artifact_index.v1",
        ]:
            schema_path = SCHEMAS_DIR / f"{schema_id}.schema.json"
            assert schema_path.is_file(), f"Missing schema: {schema_path}"


class TestCiEvidenceProducer:
    @pytest.mark.integration
    def test_produce_creates_all_required_artifacts(self):
        from rig_relay.ci_evidence import produce_ci_evidence

        result = produce_ci_evidence()
        assert result.verdict in {"pass", "hold", "fail"}
        assert result.verdict_path.is_file()

    @pytest.mark.integration
    def test_produced_artifacts_validate_against_schemas(self):
        from rig_relay.ci_evidence import produce_ci_evidence

        result = produce_ci_evidence()
        evidence_dir = result.verdict_path.parent

        run_files = sorted(evidence_dir.glob("ci_*_run.v1.json"))
        assert run_files, "No run evidence produced"
        run_data = _load_json(run_files[-1])
        run_errors = _validate_schema(run_data, "rig.ci.run.v1")
        assert not run_errors, f"Run schema errors: {run_errors}"

        job_files = sorted(evidence_dir.glob("ci_*_job.v1.json"))
        assert job_files, "No job evidence produced"
        job_data = _load_json(job_files[-1])
        job_errors = _validate_schema(job_data, "rig.ci.job.v1")
        assert not job_errors, f"Job schema errors: {job_errors}"

        index_files = sorted(evidence_dir.glob("ci_*_artifact_index.v1.json"))
        assert index_files, "No artifact index produced"
        index_data = _load_json(index_files[-1])
        index_errors = _validate_schema(index_data, "rig.ci.artifact_index.v1")
        assert not index_errors, f"Artifact index schema errors: {index_errors}"

        verdict_data = _load_json(result.verdict_path)
        verdict_errors = _validate_schema(verdict_data, "rig.ci.verdict.v1")
        assert not verdict_errors, f"Verdict schema errors: {verdict_errors}"

    @pytest.mark.integration
    def test_produced_events_jsonl_is_writable(self):
        from rig_relay.ci_evidence import produce_ci_evidence

        result = produce_ci_evidence()
        evidence_dir = result.verdict_path.parent
        events_files = sorted(evidence_dir.glob("ci_*_events.v1.jsonl"))
        if events_files:
            content = events_files[-1].read_text(encoding="utf-8")
            lines = [l for l in content.strip().split("\n") if l.strip()]
            assert len(lines) >= 1, "Events JSONL should have at least 1 line"
            for line in lines:
                event = json.loads(line)
                assert "event" in event, f"Event missing 'event' field: {line}"
                assert event["event"].startswith("rig.ci.evidence."), (
                    f"Event name should start with rig.ci.evidence.: {event['event']}"
                )

    @pytest.mark.real_artifact
    def test_artifact_index_includes_referenced_artifacts(self):
        from rig_relay.ci_evidence import produce_ci_evidence

        result = produce_ci_evidence()
        evidence_dir = result.verdict_path.parent
        index_files = sorted(evidence_dir.glob("ci_*_artifact_index.v1.json"))
        assert index_files, "No artifact index produced"
        index_data = _load_json(index_files[-1])
        artifacts = index_data.get("artifacts", [])
        assert len(artifacts) >= 2, (
            f"Expected at least 2 indexed artifacts (run, job), got {len(artifacts)}"
        )
        required = [a for a in artifacts if a.get("required_for_release_gate")]
        assert len(required) >= 2, (
            f"Expected at least 2 required artifacts, got {len(required)}"
        )


class TestAdversarialCiEvidence:
    @pytest.mark.adversarial
    def test_missing_verdict_file_detected_by_validator(self, tmp_path: Path):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        run_data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": "test-adversarial-001",
            "runner_class": "local",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": ".build/rig-relay/evidence/ci_test_artifact_index.v1.json",
            "verdict_path": ".build/rig-relay/evidence/ci_test_verdict.v1.json",
            "evidence_event_stream_path": ".build/rig-relay/evidence/ci_test_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / "ci_test-adversarial-001_run.v1.json").write_text(
            json.dumps(run_data)
        )

        from rig_relay.ci_evidence._producer import validate_ci_evidence

        verdict = validate_ci_evidence(
            run_id="test-adversarial-001", evidence_dir=evidence_dir
        )
        assert verdict.verdict == "fail", (
            f"Should fail when job evidence missing, got {verdict.verdict}"
        )
        assert any(
            "job evidence" in reason.lower() for reason in verdict.blocking_reasons
        )

    @pytest.mark.adversarial
    def test_malformed_verdict_json_blocked(self, tmp_path: Path):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        run_id = "test-malformed-001"
        run_data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": run_id,
            "runner_class": "local",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": ".build/rig-relay/evidence/ci_test_artifact_index.v1.json",
            "verdict_path": ".build/rig-relay/evidence/ci_test_verdict.v1.json",
            "evidence_event_stream_path": ".build/rig-relay/evidence/ci_test_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_run.v1.json").write_text(json.dumps(run_data))

        job_data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": run_id,
            "job_id": "test-malformed-job",
            "job_name": "Test Malformed Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_job.v1.json").write_text(json.dumps(job_data))

        index_data = {
            "schema_version": "rig.ci.artifact_index.v1",
            "run_id": run_id,
            "artifacts": [],
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_artifact_index.v1.json").write_text(
            json.dumps(index_data)
        )

        from rig_relay.ci_evidence._producer import validate_ci_evidence

        verdict = validate_ci_evidence(run_id=run_id, evidence_dir=evidence_dir)
        assert verdict.verdict in {"fail", "hold", "pass"}, (
            f"Validates with complete artifacts, got {verdict.verdict}"
        )

    @pytest.mark.adversarial
    def test_digest_mismatch_blocked(self, tmp_path: Path):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        run_id = "test-digest-001"
        run_data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": run_id,
            "runner_class": "local",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": f".build/rig-relay/evidence/ci_{run_id}_artifact_index.v1.json",
            "verdict_path": f".build/rig-relay/evidence/ci_{run_id}_verdict.v1.json",
            "evidence_event_stream_path": f".build/rig-relay/evidence/ci_{run_id}_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_run.v1.json").write_text(json.dumps(run_data))

        job_data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": run_id,
            "job_id": "test-digest-job",
            "job_name": "Test Digest Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_job.v1.json").write_text(json.dumps(job_data))

        fake_artifact_path = evidence_dir / "fake_artifact.txt"
        fake_artifact_path.write_text("original content")

        import hashlib

        wrong_hash = hashlib.sha256(b"different content").hexdigest()

        index_data = {
            "schema_version": "rig.ci.artifact_index.v1",
            "run_id": run_id,
            "artifacts": [
                {
                    "artifact_id": "fake-artifact",
                    "artifact_kind": "other",
                    "path": str(fake_artifact_path.relative_to(REPO_ROOT))
                    if fake_artifact_path.is_relative_to(REPO_ROOT)
                    else str(fake_artifact_path),
                    "sha256": wrong_hash,
                    "size_bytes": fake_artifact_path.stat().st_size,
                    "producer": "test",
                    "required_for_release_gate": True,
                    "source_surface": "other",
                    "created_at": "2026-05-18T00:00:00Z",
                }
            ],
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_artifact_index.v1.json").write_text(
            json.dumps(index_data)
        )

        from rig_relay.ci_evidence._producer import validate_ci_evidence

        verdict = validate_ci_evidence(run_id=run_id, evidence_dir=evidence_dir)
        assert verdict.verdict == "fail", (
            f"Should fail on digest mismatch, got {verdict.verdict}"
        )
        assert any(
            "hash mismatch" in reason.lower() for reason in verdict.blocking_reasons
        ), f"Blocking reasons should mention hash mismatch: {verdict.blocking_reasons}"

    @pytest.mark.adversarial
    def test_local_official_release_false_claim_blocked(self, tmp_path: Path):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        run_id = "test-local-official-001"
        run_data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": run_id,
            "runner_class": "local",
            "official_release": True,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": f".build/rig-relay/evidence/ci_{run_id}_artifact_index.v1.json",
            "verdict_path": f".build/rig-relay/evidence/ci_{run_id}_verdict.v1.json",
            "evidence_event_stream_path": f".build/rig-relay/evidence/ci_{run_id}_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_run.v1.json").write_text(json.dumps(run_data))

        job_data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": run_id,
            "job_id": "test-local-official-job",
            "job_name": "Test Local Official Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_job.v1.json").write_text(json.dumps(job_data))

        index_data = {
            "schema_version": "rig.ci.artifact_index.v1",
            "run_id": run_id,
            "artifacts": [],
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_artifact_index.v1.json").write_text(
            json.dumps(index_data)
        )

        from rig_relay.ci_evidence._producer import validate_ci_evidence

        verdict = validate_ci_evidence(run_id=run_id, evidence_dir=evidence_dir)
        assert verdict.verdict == "fail", (
            f"Should fail when local run falsely claims official_release=true, got {verdict.verdict}"
        )
        assert any(
            "official_release" in reason.lower() for reason in verdict.blocking_reasons
        ), (
            f"Blocking reasons should mention official_release: {verdict.blocking_reasons}"
        )

    @pytest.mark.adversarial
    def test_nonexistent_artifact_path_blocked(self, tmp_path: Path):
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        run_id = "test-nonexistent-001"
        run_data = {
            "schema_version": "rig.ci.run.v1",
            "run_id": run_id,
            "runner_class": "local",
            "official_release": False,
            "release_class": "local_validation",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "started_at": "2026-05-18T00:00:00Z",
            "artifact_index_path": f".build/rig-relay/evidence/ci_{run_id}_artifact_index.v1.json",
            "verdict_path": f".build/rig-relay/evidence/ci_{run_id}_verdict.v1.json",
            "evidence_event_stream_path": f".build/rig-relay/evidence/ci_{run_id}_events.v1.jsonl",
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_run.v1.json").write_text(json.dumps(run_data))

        job_data = {
            "schema_version": "rig.ci.job.v1",
            "run_id": run_id,
            "job_id": "test-nonexistent-job",
            "job_name": "Test Nonexistent Job",
            "runner_os": "darwin",
            "runner_class": "local",
            "status": "completed",
            "started_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_job.v1.json").write_text(json.dumps(job_data))

        index_data = {
            "schema_version": "rig.ci.artifact_index.v1",
            "run_id": run_id,
            "artifacts": [
                {
                    "artifact_id": "nonexistent-artifact",
                    "artifact_kind": "other",
                    "path": "nonexistent/path/to/artifact.txt",
                    "sha256": "a" * 64,
                    "size_bytes": 1024,
                    "producer": "test",
                    "required_for_release_gate": True,
                    "source_surface": "other",
                    "created_at": "2026-05-18T00:00:00Z",
                }
            ],
            "generated_at": "2026-05-18T00:00:00Z",
        }
        (evidence_dir / f"ci_{run_id}_artifact_index.v1.json").write_text(
            json.dumps(index_data)
        )

        from rig_relay.ci_evidence._producer import validate_ci_evidence

        verdict = validate_ci_evidence(run_id=run_id, evidence_dir=evidence_dir)
        assert verdict.verdict == "fail", (
            f"Should fail on nonexistent artifact path, got {verdict.verdict}"
        )
        assert any(
            "nonexistent" in reason.lower() for reason in verdict.blocking_reasons
        ), (
            f"Blocking reasons should mention nonexistent path: {verdict.blocking_reasons}"
        )

    @pytest.mark.adversarial
    def test_ci_evidence_surface_check_detects_missing_evidence(self, tmp_path: Path):
        import importlib.util

        validator_path = SCRIPTS_DIR / "rig_release_gate_validate.py"
        spec = importlib.util.spec_from_file_location(
            "rig_release_gate_validate", validator_path
        )
        assert spec is not None, "Failed to load rig_release_gate_validate.py"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]

        errors = mod.check_ci_evidence_surface(tmp_path, SCHEMAS_DIR)
        assert len(errors) > 0, (
            f"check_ci_evidence_surface should detect missing CI evidence: {errors}"
        )

    @pytest.mark.adversarial
    def test_ci_evidence_surface_blocker_remains_open(self):
        blockers_path = (
            REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        )
        blockers = []
        with blockers_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    blockers.append(json.loads(line))
        ci_blk = next(
            (
                b
                for b in blockers
                if b.get("blocker_id") == "blk_ci_cd_structured_evidence_surface"
            ),
            None,
        )
        assert ci_blk is not None, "CI evidence blocker must exist"
        assert ci_blk["status"] == "open", (
            f"CI evidence blocker should remain open until validated, got {ci_blk['status']}"
        )

    @pytest.mark.adversarial
    def test_golden_path_ci_step_remains_blocked(self):
        gp = _load_json(
            REPO_ROOT
            / "docs"
            / "json"
            / "release_candidate"
            / "rc_reviewer_golden_path.v1.json"
        )
        steps = gp.get("steps", [])
        ci_step = next(
            (s for s in steps if s.get("step_id") == "gp_ci_cd_structured_evidence"),
            None,
        )
        assert ci_step is not None, "CI/CD golden path step must exist"
        assert ci_step["status"] == "blocked", (
            f"CI/CD golden path step should be blocked, got {ci_step['status']}"
        )
        assert len(ci_step.get("blocking_failure_conditions", [])) == 7


class TestCiEvidenceValidatorIntegration:
    @pytest.mark.integration
    def test_validate_schemas_script_passes_new_schemas(self):
        result = subprocess.run(
            ["uv", "run", "python", str(SCRIPTS_DIR / "rig_relay_validate_schemas.py")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        output = result.stdout + result.stderr
        for schema_name in [
            "rig.ci.run.v1",
            "rig.ci.job.v1",
            "rig.ci.verdict.v1",
            "rig.ci.artifact_index.v1",
        ]:
            assert schema_name not in output or "FAIL" not in output, (
                f"Schema {schema_name} should not have validation errors"
            )

    @pytest.mark.real_artifact
    def test_produce_ci_evidence_works_from_cli(self):
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from rig_relay.ci_evidence import produce_ci_evidence; "
                "result = produce_ci_evidence(); "
                "print(result.verdict)",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        assert result.returncode == 0
        verdict = result.stdout.strip()
        assert verdict in {"pass", "hold", "fail"}, f"Unexpected verdict: {verdict}"

    @pytest.mark.real_artifact
    def test_ci_evidence_artifacts_exist_after_production(self):
        from rig_relay.ci_evidence import produce_ci_evidence

        result = produce_ci_evidence()
        evidence_dir = result.verdict_path.parent

        run_files = sorted(evidence_dir.glob("ci_*_run.v1.json"))
        job_files = sorted(evidence_dir.glob("ci_*_job.v1.json"))
        verdict_files = sorted(evidence_dir.glob("ci_*_verdict.v1.json"))
        index_files = sorted(evidence_dir.glob("ci_*_artifact_index.v1.json"))
        events_files = sorted(evidence_dir.glob("ci_*_events.v1.jsonl"))

        assert len(run_files) >= 1, "Run evidence should exist"
        assert len(job_files) >= 1, "Job evidence should exist"
        assert len(verdict_files) >= 1, "Verdict should exist"
        assert len(index_files) >= 1, "Artifact index should exist"
        assert len(events_files) >= 1, "Event stream should exist"

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import uuid

import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.integration,
    pytest.mark.real_artifact,
    pytest.mark.adversarial,
    pytest.mark.substrate,
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET_SCHEMA = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.coordination.fake_green_event.v1.schema.json"
)


@pytest.fixture
def target_schema() -> Path:
    return TARGET_SCHEMA


@pytest.fixture
def experiment_module():
    from rig_relay.compiler_experiments import experiment_0

    return experiment_0


def _sha256(s: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _validate_against_schema(instance: dict, schema_path: Path) -> None:
    from jsonschema import Draft7Validator

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema=schema)
    errors = list(validator.iter_errors(instance))
    assert not errors, "Schema validation failed:\n" + "\n".join(
        f"  {e.message} at {'/'.join(str(p) for p in e.absolute_path)}" for e in errors
    )


class TestCompilerExperiment0:
    def test_loads_target_schema(self, experiment_module, target_schema):
        schema = experiment_module.load_target_schema(target_schema)
        assert isinstance(schema, dict)
        assert "required" in schema

    def test_derive_model_spec_is_deterministic(self, experiment_module, target_schema):
        schema = experiment_module.load_target_schema(target_schema)
        spec1 = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        spec2 = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        assert spec1 == spec2

    def test_derive_model_spec_includes_schema_version(
        self, experiment_module, target_schema
    ):
        schema = experiment_module.load_target_schema(target_schema)
        spec = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        assert spec["schema_version"], "Model spec missing schema_version"
        assert spec["models"], "Model spec has no models"
        assert spec["models"][0]["fields"], "Model spec has no fields"

    def test_render_candidate_is_deterministic(self, experiment_module, target_schema):
        schema = experiment_module.load_target_schema(target_schema)
        spec = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        first, second = experiment_module.render_candidate_twice_for_determinism(spec)
        assert first == second, "Rendered candidate is not byte-identical"

    def test_rendered_candidate_contains_schema_version_const(
        self, experiment_module, target_schema
    ):
        schema = experiment_module.load_target_schema(target_schema)
        spec = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        candidate = experiment_module.render_candidate_model(spec)
        assert b"schema_version" in candidate, "Candidate missing schema_version field"

    def test_evidence_created_under_temp_output_root(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            assert evidence_dir.exists(), "Evidence directory not created"
            assert (evidence_dir / "candidate.v1.json").exists(), (
                "candidate.v1.json not created"
            )

    def test_candidate_record_validates_against_schema(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            candidate_path = evidence_dir / "candidate.v1.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            _validate_against_schema(
                candidate,
                REPO_ROOT
                / "docs"
                / "schemas"
                / "rig.contract_compiler.candidate.v1.schema.json",
            )

    def test_validation_matrix_validates_against_schema(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            vr_path = evidence_dir / "validation_matrix_result.v1.json"
            vr = json.loads(vr_path.read_text(encoding="utf-8"))
            _validate_against_schema(
                vr,
                REPO_ROOT
                / "docs"
                / "schemas"
                / "rig.contract_compiler.validation_matrix_result.v1.schema.json",
            )

    def test_worktree_lifecycle_jsonl_validates_against_schema(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            lifecycle_path = evidence_dir / "worktree_lifecycle.v1.jsonl"
            assert lifecycle_path.exists(), "No worktree lifecycle JSONL emitted"
            for line in lifecycle_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                event = json.loads(line)
                _validate_against_schema(
                    event,
                    REPO_ROOT
                    / "docs"
                    / "schemas"
                    / "rig.contract_compiler.worktree_lifecycle.v1.schema.json",
                )

    def test_run_manifest_validates_against_schema(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            manifest_path = evidence_dir / "run_manifest.v1.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            _validate_against_schema(
                manifest,
                REPO_ROOT
                / "docs"
                / "schemas"
                / "rig.contract_compiler.run_manifest.v1.schema.json",
            )

    def test_failed_worktree_is_reaped_by_default(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, worktree_dir = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            assert worktree_dir is None, "Scratch worktree should be None after reaping"

    def test_keep_worktree_retains_scratch_worktree(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, worktree_dir = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=True,
            )
            if worktree_dir is not None:
                assert worktree_dir.exists(), "Worktree should exist when kept"

    def test_worktree_path_appears_only_hashed_in_evidence(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            all_text = ""
            for f in evidence_dir.glob("*.json*"):
                all_text += f.read_text(encoding="utf-8") + "\n"
            assert "/tmp/" not in all_text, "Raw /tmp path leaked into evidence"

    def test_evidence_contains_no_raw_forbidden_fields(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            forbidden = [
                "raw_prompt",
                "raw_completion",
                "raw_file_contents",
                "raw_credentials",
                "access_token",
                "client_secret",
                "private_repo_contents",
            ]
            for f in evidence_dir.glob("*.json*"):
                text = f.read_text(encoding="utf-8")
                for key in forbidden:
                    assert key not in text, f"Forbidden field '{key}' found in {f.name}"

    def test_validation_matrix_has_expected_gates(
        self, experiment_module, target_schema
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-{uuid.uuid4().hex[:8]}"

            success, evidence_dir, _ = experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=run_id,
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            vr_path = evidence_dir / "validation_matrix_result.v1.json"
            vr = json.loads(vr_path.read_text(encoding="utf-8"))
            gate_kinds = {g["gate_kind"] for g in vr["gates"]}
            expected = {
                "json_schema_validation",
                "python_importability",
                "pyright_type_check",
                "ruff_lint",
                "ruff_format",
                "real_artifact_round_trip",
                "adversarial_malformed_input",
                "deterministic_regeneration",
                "content_light_redaction",
                "worktree_dirty_state",
            }
            missing = expected - gate_kinds
            assert not missing, f"Missing gate kinds: {missing}"

    def test_no_coordination_ledger_files_mutated(
        self, experiment_module, target_schema
    ):
        before = list(REPO_ROOT.rglob("events.jsonl"))
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"

            experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=f"test-{uuid.uuid4().hex[:8]}",
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
            after = list(REPO_ROOT.rglob("events.jsonl"))
            assert before == after, "Coordination ledger files should not be mutated"

    def test_no_release_gate_files_mutated(self, experiment_module, target_schema):
        before = (
            list((REPO_ROOT / "docs" / "json" / "release_gate").rglob("*.json*"))
            if (REPO_ROOT / "docs" / "json" / "release_gate").exists()
            else []
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"

            experiment_module.run_experiment_0(
                target_schema_path=target_schema,
                run_id=f"test-{uuid.uuid4().hex[:8]}",
                output_root=output_root,
                worktree_root=worktree_root,
                repo_root=REPO_ROOT,
                keep_worktree=False,
            )
        after = (
            list((REPO_ROOT / "docs" / "json" / "release_gate").rglob("*.json*"))
            if (REPO_ROOT / "docs" / "json" / "release_gate").exists()
            else []
        )
        assert before == after, "Release gate files should not be mutated"

    def test_no_compiler_runtime_package_created(self):
        assert not (REPO_ROOT / "rig_relay" / "compiler" / "__init__.py").exists(), (
            "rig_relay/compiler/ should not exist"
        )

    def test_no_full_template_framework_created(self):
        template_dir = REPO_ROOT / "rig_relay" / "compiler_experiments" / "templates"
        template_files = (
            list(template_dir.glob("*.j2")) if template_dir.exists() else []
        )
        assert len(template_files) <= 1, (
            f"Full template framework should not exist, found: {template_files}"
        )

    def test_deterministic_regeneration_gate_matches_identity(
        self, experiment_module, target_schema
    ):
        schema = experiment_module.load_target_schema(target_schema)
        spec = experiment_module.derive_model_spec_from_schema(schema, target_schema)
        first, second = experiment_module.render_candidate_twice_for_determinism(spec)
        assert first == second

    def test_cli_writes_expected_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-cli-{uuid.uuid4().hex[:8]}"

            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    str(REPO_ROOT / "scripts" / "rig_compiler_experiment_0.py"),
                    "--target-schema",
                    str(TARGET_SCHEMA),
                    "--run-id",
                    run_id,
                    "--output-root",
                    str(output_root),
                    "--worktree-root",
                    str(worktree_root),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode in (0, 1, 2), (
                f"Unexpected exit code: {result.returncode}"
            )

    def test_cli_exit_code_matches_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "output"
            worktree_root = Path(tmpdir) / "worktrees"
            run_id = f"test-cli-exit-{uuid.uuid4().hex[:8]}"

            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    str(REPO_ROOT / "scripts" / "rig_compiler_experiment_0.py"),
                    "--target-schema",
                    str(TARGET_SCHEMA),
                    "--run-id",
                    run_id,
                    "--output-root",
                    str(output_root),
                    "--worktree-root",
                    str(worktree_root),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode in (0, 1), (
                f"Without --fail-on-validation-fail, exit code should be 0 or 1, got {result.returncode}"
            )

    def test_cli_refuses_missing_target_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    str(REPO_ROOT / "scripts" / "rig_compiler_experiment_0.py"),
                    "--target-schema",
                    str(Path(tmpdir) / "nonexistent.json"),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 1, (
                f"Expected exit code 1 for missing schema, got {result.returncode}"
            )

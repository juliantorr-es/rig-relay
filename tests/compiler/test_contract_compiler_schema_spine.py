from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.adversarial]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
ARTIFACTS_DIR = REPO_ROOT / "docs" / "json" / "compiler"
COMPILER_DIR = REPO_ROOT / "rig_relay" / "compiler"

SCHEMA_NAMES = [
    "rig.contract_compiler.run_manifest.v1.schema.json",
    "rig.contract_compiler.candidate.v1.schema.json",
    "rig.contract_compiler.worktree_lifecycle.v1.schema.json",
    "rig.contract_compiler.counterexample.v1.schema.json",
    "rig.contract_compiler.validation_matrix_result.v1.schema.json",
    "rig.contract_compiler.permutation_corpus_row.v1.schema.json",
    "rig.contract_compiler.pattern_report.v1.schema.json",
]

SHA256_RE = r"^sha256:[a-f0-9]{64}$"
FULL_SHA_RE = r"^[a-f0-9]{40}$"


def _sha256(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _validate_against_schema(instance: dict, schema: dict) -> None:
    from jsonschema import Draft7Validator

    validator = Draft7Validator(schema=schema)
    errors = list(validator.iter_errors(instance))
    assert not errors, "Schema validation failed:\n" + "\n".join(
        f"  {e.message} at {'/'.join(str(p) for p in e.absolute_path)}" for e in errors
    )


def _valid_run_manifest() -> dict:
    return {
        "schema_version": "rig.contract_compiler.run_manifest.v1",
        "run_id": "run-2026-05-19-001",
        "generated_at": "2026-05-19T12:00:00Z",
        "repo_head_sha": "a" * 40,
        "repo_branch_hash": _sha256("main"),
        "semantic_contract_id": "coordination_event_payloads",
        "semantic_contract_sha256": _sha256("contract-body"),
        "compiler_version": "0.0.1-dev",
        "generator_id": "jinja2_template_v0",
        "generator_version": "0.0.1-dev",
        "base_worktree_path_hash": _sha256("/path/to/base"),
        "evidence_root": "contract-compiler/runs/run-2026-05-19-001/",
        "worktree_root_hash": _sha256("/path/to/worktrees"),
        "worktree_budget": {
            "max_scratch_worktrees": 20,
            "max_retained_failed_worktrees": 3,
            "max_stage_depth": 10,
            "max_candidates_per_slice": 50,
            "max_runtime_seconds_per_candidate": 300,
        },
        "contract_slices": [
            {
                "contract_slice_id": "slice-1",
                "slice_order": 0,
                "acceptance_threshold": 1.0,
                "assertion_count": 5,
                "required_gate_ids": ["json_schema_validation", "python_importability"],
            }
        ],
        "candidate_count": 10,
        "accepted_candidate_count": 1,
        "rejected_candidate_count": 7,
        "quarantined_candidate_count": 2,
        "counterexample_count": 15,
        "validation_matrix_summary": {
            "total_gates": 12,
            "passing_gates": 120,
            "failing_gates": 15,
            "held_gates": 5,
            "skipped_gates": 0,
            "total_validations_run": 10,
            "average_duration_ms": 4500,
        },
        "artifact_paths": {
            "candidates_jsonl": "candidates.jsonl",
            "validation_results_jsonl": "validation_results.jsonl",
            "counterexamples_jsonl": "counterexamples.jsonl",
            "permutation_corpus_jsonl": "permutation_corpus.jsonl",
            "pattern_report_path": "pattern_report.v1.json",
            "worktree_lifecycle_jsonl": "worktree_lifecycle.jsonl",
        },
        "artifact_hashes": {
            "candidates_jsonl_sha256": _sha256("candidates"),
            "validation_results_jsonl_sha256": _sha256("results"),
            "counterexamples_jsonl_sha256": _sha256("counterexamples"),
            "permutation_corpus_jsonl_sha256": _sha256("corpus"),
            "pattern_report_sha256": _sha256("report"),
            "worktree_lifecycle_jsonl_sha256": _sha256("lifecycle"),
            "run_manifest_sha256": _sha256("manifest"),
        },
        "content_light": True,
        "redaction_status": "content_light",
    }


def _valid_candidate() -> dict:
    return {
        "schema_version": "rig.contract_compiler.candidate.v1",
        "candidate_id": "cand-001",
        "run_id": "run-2026-05-19-001",
        "contract_family_id": "coordination_event_payloads",
        "contract_slice_id": "slice-1",
        "parent_stage_id": "stage-0",
        "candidate_kind": "combined_candidate",
        "candidate_status": "generated",
        "semantic_contract_sha256": _sha256("contract-body"),
        "schema_candidate_sha256": _sha256("schema"),
        "python_candidate_sha256": _sha256("python"),
        "candidate_patch_sha256": _sha256("patch"),
        "generator_id": "jinja2_template_v0",
        "generator_version": "0.0.1-dev",
        "worktree_id": "wt-001",
        "worktree_path_hash": _sha256("/path/to/worktree"),
        "base_head_sha": "b" * 40,
        "created_at": "2026-05-19T12:00:00Z",
        "updated_at": "2026-05-19T12:01:00Z",
        "content_light": True,
        "redaction_status": "content_light",
    }


def _valid_worktree_lifecycle() -> dict:
    return {
        "schema_version": "rig.contract_compiler.worktree_lifecycle.v1",
        "event_id": "evt-001",
        "run_id": "run-2026-05-19-001",
        "candidate_id": "cand-001",
        "worktree_id": "wt-001",
        "worktree_kind": "scratch_candidate",
        "lifecycle_state": "created",
        "previous_state": "",
        "next_state": "patch_applied",
        "worktree_path_hash": _sha256("/path/to/worktree"),
        "base_head_sha": "c" * 40,
        "current_head_sha": "c" * 40,
        "dirty_state": "clean",
        "emitted_at": "2026-05-19T12:00:00Z",
        "event_reason": "Candidate worktree created from stage base",
        "cleanup_action": "none",
        "content_light": True,
        "redaction_status": "content_light",
    }


def _valid_counterexample() -> dict:
    return {
        "schema_version": "rig.contract_compiler.counterexample.v1",
        "counterexample_id": "ce-001",
        "run_id": "run-2026-05-19-001",
        "candidate_id": "cand-007",
        "worktree_id": "wt-007",
        "contract_family_id": "coordination_event_payloads",
        "contract_slice_id": "slice-2",
        "source_gate": "adversarial_malformed_input",
        "input_artifact_hash": _sha256("malformed-input"),
        "expected_behavior": "Model must raise ValidationError for missing required field",
        "actual_behavior_hash": _sha256("model-accepted-invalid-data"),
        "failure_class": "constraint_violation",
        "spurious_or_genuine": "genuine",
        "replay_command_hash": _sha256("replay-command"),
        "minimal_reproduction_artifact_path": "counterexamples/ce-001/repro.json",
        "redaction_status": "content_light",
        "deduplication_key": _sha256("dedup-combined-key"),
        "pruning_effect": "schema_constraint_pattern",
        "discovered_at": "2026-05-19T12:02:00Z",
    }


def _valid_validation_matrix_result() -> dict:
    return {
        "schema_version": "rig.contract_compiler.validation_matrix_result.v1",
        "validation_result_id": "vr-001",
        "run_id": "run-2026-05-19-001",
        "candidate_id": "cand-001",
        "worktree_id": "wt-001",
        "started_at": "2026-05-19T12:00:30Z",
        "completed_at": "2026-05-19T12:01:00Z",
        "overall_status": "pass",
        "gates": [
            {
                "gate_id": "gate-json-schema",
                "gate_kind": "json_schema_validation",
                "status": "pass",
                "started_at": "2026-05-19T12:00:30Z",
                "completed_at": "2026-05-19T12:00:31Z",
                "duration_ms": 200,
                "evidence_hash": _sha256("schema-evidence"),
            },
            {
                "gate_id": "gate-pyright",
                "gate_kind": "pyright_type_check",
                "status": "pass",
                "started_at": "2026-05-19T12:00:31Z",
                "completed_at": "2026-05-19T12:00:35Z",
                "duration_ms": 3500,
                "evidence_hash": _sha256("pyright-evidence"),
            },
        ],
        "passed_gate_count": 2,
        "failed_gate_count": 0,
        "warning_gate_count": 0,
        "counterexample_ids": [],
        "output_artifact_hashes": {},
        "content_light": True,
        "redaction_status": "content_light",
    }


def _valid_permutation_corpus_row() -> dict:
    return {
        "schema_version": "rig.contract_compiler.permutation_corpus_row.v1",
        "row_id": "row-001",
        "run_id": "run-2026-05-19-001",
        "candidate_id": "cand-001",
        "contract_family_id": "coordination_event_payloads",
        "contract_slice_id": "slice-1",
        "generator_id": "jinja2_template_v0",
        "generator_version": "0.0.1-dev",
        "schema_pattern_id": "sp-001",
        "template_branch_id": "tb-001",
        "candidate_status": "accepted",
        "fit_score": 1.0,
        "gate_summary": {"passed": 12, "failed": 0, "held": 0, "skipped": 0},
        "counterexample_count": 0,
        "counterexample_cluster_ids": [],
        "promoted_to_stage": True,
        "accepted": True,
        "emitted_at": "2026-05-19T12:01:30Z",
        "content_light": True,
    }


def _valid_pattern_report() -> dict:
    return {
        "schema_version": "rig.contract_compiler.pattern_report.v1",
        "run_id": "run-2026-05-19-001",
        "generated_at": "2026-05-19T12:05:00Z",
        "successful_schema_patterns": [
            {
                "pattern_id": "sp-ok-001",
                "pattern_kind": "schema_constraint",
                "frequency": 5,
                "success_rate": 1.0,
                "affected_contract_family_ids": ["coordination_event_payloads"],
                "affected_slice_ids": ["slice-1"],
                "evidence_candidate_ids": ["cand-001", "cand-002"],
                "evidence_hashes": [_sha256("ev1"), _sha256("ev2")],
                "recommendation": "This constraint pattern is reliable; promote to template default.",
            }
        ],
        "failed_schema_patterns": [],
        "successful_template_patterns": [],
        "failed_template_patterns": [],
        "counterexample_clusters": [
            {
                "cluster_id": "cl-001",
                "failure_class": "constraint_violation",
                "counterexample_count": 3,
                "affected_candidate_count": 3,
                "representative_counterexample_hash": _sha256("repr"),
            }
        ],
        "contract_ambiguity_findings": [
            {
                "assertion_id": "assert-003",
                "attempt_count": 8,
                "failure_rate": 0.625,
                "affected_contract_families": ["coordination_event_payloads"],
            }
        ],
        "recommended_schema_refinements": [
            "Add minLength constraint to session_id field"
        ],
        "recommended_template_refinements": [
            "Generate Pydantic Field validators for pattern constraints"
        ],
        "recommended_validator_refinements": [
            "Add worktree_dirty_state check after round-trip test"
        ],
        "content_light": True,
        "redaction_status": "content_light",
    }


class TestContractCompilerSchemaSpine:
    def test_all_seven_schemas_parse_as_json(self):
        for name in SCHEMA_NAMES:
            schema = _load_schema(name)
            assert isinstance(schema, dict), f"{name} did not parse as JSON dict"

    def test_all_seven_schemas_pass_project_validation(self):
        from jsonschema import Draft7Validator

        for name in SCHEMA_NAMES:
            schema = _load_schema(name)
            Draft7Validator.check_schema(schema)

    def test_run_manifest_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[0])
        _validate_against_schema(_valid_run_manifest(), schema)

    def test_candidate_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[1])
        _validate_against_schema(_valid_candidate(), schema)

    def test_worktree_lifecycle_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[2])
        _validate_against_schema(_valid_worktree_lifecycle(), schema)

    def test_counterexample_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[3])
        _validate_against_schema(_valid_counterexample(), schema)

    def test_validation_matrix_result_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[4])
        _validate_against_schema(_valid_validation_matrix_result(), schema)

    def test_permutation_corpus_row_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[5])
        _validate_against_schema(_valid_permutation_corpus_row(), schema)

    def test_pattern_report_valid_fixture_validates(self):
        schema = _load_schema(SCHEMA_NAMES[6])
        _validate_against_schema(_valid_pattern_report(), schema)

    def test_counterexample_rejects_raw_prompt_field(self):
        schema = _load_schema(SCHEMA_NAMES[3])
        bad = _valid_counterexample()
        bad["raw_prompt"] = "leaked-prompt"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_counterexample_rejects_raw_file_contents_field(self):
        schema = _load_schema(SCHEMA_NAMES[3])
        bad = _valid_counterexample()
        bad["raw_file_contents"] = "leaked-file"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_counterexample_rejects_access_token_field(self):
        schema = _load_schema(SCHEMA_NAMES[3])
        bad = _valid_counterexample()
        bad["access_token"] = "ghp_leaked"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_lifecycle_rejects_unknown_lifecycle_state(self):
        schema = _load_schema(SCHEMA_NAMES[2])
        bad = _valid_worktree_lifecycle()
        bad["lifecycle_state"] = "nonexistent_state"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_validation_matrix_rejects_unknown_gate_kind(self):
        schema = _load_schema(SCHEMA_NAMES[4])
        bad = _valid_validation_matrix_result()
        bad["gates"][0]["gate_kind"] = "made_up_gate"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_hash_fields_require_sha256_prefix_and_64_hex_chars(self):
        schema = _load_schema(SCHEMA_NAMES[3])
        bad = _valid_counterexample()
        bad["deduplication_key"] = "not-a-hash"
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_pattern_report_requires_content_light_true(self):
        schema = _load_schema(SCHEMA_NAMES[6])
        bad = _valid_pattern_report()
        bad["content_light"] = False
        with pytest.raises(AssertionError):
            _validate_against_schema(bad, schema)

    def test_schema_spine_artifact_exists_and_names_all_seven(self):
        spine_path = ARTIFACTS_DIR / "contract_compiler_schema_spine_v0.v1.json"
        assert spine_path.exists(), f"Missing spine artifact at {spine_path}"
        spine = json.loads(spine_path.read_text(encoding="utf-8"))
        introduced = spine.get("schemas_introduced", [])
        assert len(introduced) == 7, (
            f"Expected 7 schemas in spine artifact, got {len(introduced)}"
        )
        expected_paths = {s["schema_path"] for s in introduced}
        assert all("rig.contract_compiler." in p for p in expected_paths), (
            "All paths should contain 'rig.contract_compiler.'"
        )

    def test_compiler_implementation_files_do_not_exist(self):
        nonexistent = [
            COMPILER_DIR / "__init__.py",
            REPO_ROOT / "scripts" / "rig_contract_compiler.py",
        ]
        for path in nonexistent:
            assert not path.exists(), (
                f"Compiler implementation file should not exist: {path}"
            )

    def test_no_jinja2_templates_created(self):
        template_dir = COMPILER_DIR / "templates"
        assert not template_dir.exists(), (
            f"Jinja2 template directory should not exist: {template_dir}"
        )

    def test_no_worktrees_created(self):
        wt_root = REPO_ROOT / ".rig" / "relay" / "worktrees" / "compiler"
        assert not wt_root.exists(), (
            f"Compiler worktree directory should not exist: {wt_root}"
        )

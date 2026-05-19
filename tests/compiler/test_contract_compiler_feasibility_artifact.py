from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.contract_compiler_feasibility.v1.schema.json"
)
ARTIFACT_PATH = (
    REPO_ROOT / "docs" / "json" / "compiler" / "contract_compiler_feasibility.v1.json"
)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def _validate_artifact_against_schema(artifact: dict, schema: dict) -> None:
    from jsonschema import Draft7Validator

    validator = Draft7Validator(schema=schema)
    errors = list(validator.iter_errors(artifact))
    assert not errors, "Artifact failed schema validation:\n" + "\n".join(
        f"  {e.message} at {'/'.join(str(p) for p in e.absolute_path)}" for e in errors
    )


class TestContractCompilerFeasibilityArtifact:
    def test_schema_file_is_valid_json(self):
        schema = _load_schema()
        assert isinstance(schema, dict)

    def test_artifact_file_is_valid_json(self):
        artifact = _load_artifact()
        assert isinstance(artifact, dict)

    def test_artifact_validates_against_schema(self):
        schema = _load_schema()
        artifact = _load_artifact()
        _validate_artifact_against_schema(artifact, schema)

    def test_schema_version_is_correct(self):
        artifact = _load_artifact()
        assert (
            artifact.get("schema_version") == "rig.contract_compiler_feasibility.v1"
        ), (
            f"Expected schema_version 'rig.contract_compiler_feasibility.v1', got '{artifact.get('schema_version')}'"
        )

    def test_final_recommendation_is_promote(self):
        artifact = _load_artifact()
        final = artifact.get("final_recommendation", {})
        assert final.get("recommendation") == "promote", (
            f"Expected recommendation 'promote', got '{final.get('recommendation')}'"
        )

    def test_compiler_kind_is_contract_satisfaction_compiler(self):
        artifact = _load_artifact()
        arch = artifact.get("proposed_compiler_architecture", {})
        assert arch.get("compiler_kind") == "contract_satisfaction_compiler", (
            f"Expected compiler_kind 'contract_satisfaction_compiler', got '{arch.get('compiler_kind')}'"
        )

    def test_implementation_should_start_now_is_false(self):
        artifact = _load_artifact()
        verdict = artifact.get("feasibility_verdict", {})
        assert verdict.get("implementation_should_start_now") is False, (
            "Expected implementation_should_start_now to be false"
        )

    def test_no_new_dependency_path_is_recommended(self):
        artifact = _load_artifact()
        dep_rec = artifact.get("dependency_recommendation", {})
        no_dep = dep_rec.get("no_new_dependency_path", {})
        assert no_dep.get("recommended") is True, (
            "Expected no_new_dependency_path to be recommended for first proof"
        )

    def test_coordination_event_payload_models_is_rank_1(self):
        artifact = _load_artifact()
        ranking = artifact.get("first_compiler_target_ranking", {})
        coord = ranking.get("coordination_event_payload_models", {})
        assert coord.get("rank") == 1, (
            f"Expected coordination_event_payload_models at rank 1, got rank {coord.get('rank')}"
        )
        assert coord.get("selected_as_first") is True, (
            "Expected coordination_event_payload_models to be selected as first target"
        )

    def test_validation_matrix_includes_deterministic_regeneration(self):
        artifact = _load_artifact()
        matrix = artifact.get("proposed_compiler_architecture", {}).get(
            "validation_matrix", {}
        )
        dr = matrix.get("deterministic_regeneration", {})
        assert dr.get("enabled") is True, (
            "Expected deterministic_regeneration to be enabled in validation matrix"
        )

    def test_validation_matrix_includes_adversarial_malformed_input(self):
        artifact = _load_artifact()
        matrix = artifact.get("proposed_compiler_architecture", {}).get(
            "validation_matrix", {}
        )
        adv = matrix.get("adversarial_malformed_input", {})
        assert adv.get("enabled") is True, (
            "Expected adversarial_malformed_input to be enabled in validation matrix"
        )

    def test_fake_green_risks_includes_generated_tests_mirror_generated_code(self):
        artifact = _load_artifact()
        risks = artifact.get("fake_green_risks", {})
        assert "generated_tests_mirror_generated_code" in risks, (
            "Expected fake_green_risks to include generated_tests_mirror_generated_code"
        )
        risk = risks["generated_tests_mirror_generated_code"]
        assert risk.get("severity") == "critical", (
            f"Expected severity 'critical', got '{risk.get('severity')}'"
        )

    def test_all_coordination_events_are_proposed_only(self):
        artifact = _load_artifact()
        events = artifact.get("coordination_event_ledger_event_design", {})
        assert len(events) > 0, "Expected at least one coordination event definition"
        for event_name, event_def in events.items():
            status = event_def.get("implementation_status")
            assert status == "proposed_only", (
                f"Event '{event_name}' has implementation_status '{status}', expected 'proposed_only'"
            )

    def test_artifact_id_is_populated(self):
        artifact = _load_artifact()
        assert artifact.get("artifact_id"), "Expected artifact_id to be populated"

    def test_generated_at_is_populated(self):
        artifact = _load_artifact()
        assert artifact.get("generated_at"), "Expected generated_at to be populated"

    def test_repo_observation_has_head_and_branch(self):
        artifact = _load_artifact()
        repo = artifact.get("repo_observation", {})
        assert repo.get("branch"), "Expected branch to be populated"
        assert repo.get("head"), "Expected head to be populated"
        assert repo.get("dirty_state") == "clean"

    def test_all_four_strategies_present(self):
        artifact = _load_artifact()
        strategies = artifact.get("strategy_comparison_matrix", {})
        required = [
            "existing_generator_wrapper",
            "first_party_template_compiler",
            "cst_ast_compiler",
            "hybrid_long_term",
        ]
        for sid in required:
            assert sid in strategies, f"Missing strategy: {sid}"
            s = strategies[sid]
            assert s.get("recommendation") in {"promote", "park", "reject"}, (
                f"Strategy {sid} has invalid recommendation: {s.get('recommendation')}"
            )

    def test_all_capability_map_entries_present(self):
        artifact = _load_artifact()
        caps = artifact.get("current_repo_capability_map", {})
        required = [
            "schema_validation",
            "model_schema_drift_detection",
            "python_codegen",
            "formatting_static_checks",
            "evidence_receipt_recording",
            "coordination_ledger_readiness",
            "property_based_testing",
            "mutation_testing",
            "template_rendering",
            "git_worktree_available",
        ]
        for cap_id in required:
            assert cap_id in caps, f"Missing capability: {cap_id}"
            c = caps[cap_id]
            assert "available" in c, f"Capability {cap_id} missing 'available'"
            assert "maturity" in c, f"Capability {cap_id} missing 'maturity'"
            assert "notes" in c, f"Capability {cap_id} missing 'notes'"

    def test_online_research_includes_required_entries(self):
        artifact = _load_artifact()
        research = artifact.get("online_research_summary", [])
        tools_found = {r["tool_or_source"] for r in research}
        required_entries = {
            "pydantic_v2_json_schema",
            "jinja2_templates",
            "ruff_formatter",
            "datamodel_code_generator",
            "hypothesis",
            "cosmic_ray",
            "libcst",
            "python_ast",
        }
        for required in required_entries:
            assert required in tools_found, f"Missing online research entry: {required}"

    def test_git_worktree_requirement_is_enforced(self):
        artifact = _load_artifact()
        arch = artifact.get("proposed_compiler_architecture", {})
        gwr = arch.get("git_worktree_requirement", {})
        assert gwr.get("enforced") is True, (
            "Expected git_worktree_requirement.enforced to be true"
        )
        pp = gwr.get("promotion_policy", {})
        assert pp.get("candidate_never_mutates_canonical_directly") is True, (
            "Expected candidate_never_mutates_canonical_directly to be true"
        )
        assert pp.get("promotion_is_governed") is True, (
            "Expected promotion_is_governed to be true"
        )
        assert "isolated Git worktree" in gwr.get("description", ""), (
            "Expected git worktree requirement description to mention isolated Git worktree"
        )

    def test_worktree_path_patterns_are_present(self):
        artifact = _load_artifact()
        arch = artifact.get("proposed_compiler_architecture", {})
        worktree_pattern = arch.get("candidate_worktree_path_pattern", "")
        assert ".rig/relay/worktrees/compiler/" in worktree_pattern, (
            f"Expected worktree path pattern to contain '.rig/relay/worktrees/compiler/', got '{worktree_pattern}'"
        )
        isolation_pattern = arch.get("candidate_isolation_path_pattern", "")
        assert ".build/rig-relay/contract-compiler/runs/" in isolation_pattern, (
            f"Expected isolation path pattern to contain '.build/rig-relay/contract-compiler/runs/', got '{isolation_pattern}'"
        )

    def test_fake_green_risks_includes_inert_file_only_validation(self):
        artifact = _load_artifact()
        risks = artifact.get("fake_green_risks", {})
        assert "inert_file_only_validation" in risks, (
            "Expected fake_green_risks to include inert_file_only_validation"
        )
        risk = risks["inert_file_only_validation"]
        assert risk.get("severity") == "critical", (
            f"Expected severity 'critical', got '{risk.get('severity')}'"
        )
        assert "worktree" in risk.get(
            "prevention", ""
        ).lower() or "Git worktree" in risk.get("prevention", ""), (
            "Expected prevention text to mention worktree validation"
        )

    def test_coordination_events_include_worktree_events(self):
        artifact = _load_artifact()
        events = artifact.get("coordination_event_ledger_event_design", {})
        required_worktree_events = [
            "contract_candidate_worktree_created",
            "contract_candidate_patch_applied",
            "contract_candidate_worktree_cleaned",
        ]
        for event_name in required_worktree_events:
            assert event_name in events, f"Missing worktree event: {event_name}"
            evt = events[event_name]
            assert evt.get("implementation_status") == "proposed_only", (
                f"Worktree event '{event_name}' should be proposed_only"
            )
            assert evt.get("event_name", "").startswith("contract.candidate"), (
                f"Worktree event '{event_name}' name should start with 'contract.candidate'"
            )

    def test_worktree_budget_fields_are_present(self):
        artifact = _load_artifact()
        gwr = artifact.get("proposed_compiler_architecture", {}).get(
            "git_worktree_requirement", {}
        )
        budget = gwr.get("worktree_budget", {})
        required_fields = [
            "max_scratch_worktrees",
            "max_retained_failed_worktrees",
            "max_stage_depth",
            "max_candidates_per_slice",
            "max_runtime_seconds_per_candidate",
        ]
        for field in required_fields:
            assert field in budget, f"Missing worktree budget field: {field}"
            assert isinstance(budget[field], int) and budget[field] > 0, (
                f"Worktree budget {field} should be positive integer, got {budget[field]}"
            )

    def test_worktree_lifecycle_states_are_defined(self):
        artifact = _load_artifact()
        gwr = artifact.get("proposed_compiler_architecture", {}).get(
            "git_worktree_requirement", {}
        )
        states = gwr.get("worktree_lifecycle_states", [])
        required_states = [
            "created",
            "patch_applied",
            "validation_running",
            "failed_reset",
            "failed_reaped",
            "partially_satisfied",
            "promoted_to_stage",
            "fully_satisfied",
            "accepted",
            "promotion_proposal_emitted",
            "worktree_cleaned",
        ]
        state_names = {s["state"] for s in states}
        for required in required_states:
            assert required in state_names, f"Missing lifecycle state: {required}"

    def test_contract_slicing_is_enabled(self):
        artifact = _load_artifact()
        slicing = artifact.get("proposed_compiler_architecture", {}).get(
            "contract_slicing", {}
        )
        assert slicing.get("enabled") is True, "Expected contract_slicing to be enabled"
        slices = slicing.get("slice_ordering", [])
        assert len(slices) >= 3, (
            f"Expected at least 3 contract slices, got {len(slices)}"
        )
        assert slicing.get("partial_success_promotion", {}).get("enabled") is True, (
            "Expected partial_success_promotion to be enabled"
        )

    def test_pattern_aggregation_is_enabled(self):
        artifact = _load_artifact()
        aggregation = artifact.get("proposed_compiler_architecture", {}).get(
            "pattern_aggregation", {}
        )
        assert aggregation.get("enabled") is True, (
            "Expected pattern_aggregation to be enabled"
        )
        products = aggregation.get("data_products", [])
        assert len(products) >= 4, (
            f"Expected at least 4 data products, got {len(products)}"
        )

    def test_fake_green_risks_includes_contract_ambiguity_risk(self):
        artifact = _load_artifact()
        risks = artifact.get("fake_green_risks", {})
        assert "contract_ambiguity_risk" in risks, (
            "Expected fake_green_risks to include contract_ambiguity_risk"
        )
        risk = risks["contract_ambiguity_risk"]
        assert risk.get("severity") == "high", (
            f"Expected severity 'high', got '{risk.get('severity')}'"
        )

    def test_stage_slice_aggregation_events_are_proposed_only(self):
        artifact = _load_artifact()
        events = artifact.get("coordination_event_ledger_event_design", {})
        required_events = [
            "contract_candidate_validation_failed",
            "contract_candidate_worktree_reset",
            "contract_candidate_worktree_reaped",
            "contract_slice_partially_satisfied",
            "contract_stage_worktree_promoted",
            "contract_stage_validation_passed",
            "contract_full_contract_satisfied",
            "contract_promotion_proposal_emitted",
            "contract_permutation_patterns_aggregated",
            "contract_schema_pattern_discovered",
            "contract_template_refinement_proposed",
        ]
        for event_name in required_events:
            assert event_name in events, f"Missing event: {event_name}"
            evt = events[event_name]
            assert evt.get("implementation_status") == "proposed_only", (
                f"Event '{event_name}' should be proposed_only"
            )

    def test_staged_accumulation_rule_is_correct(self):
        artifact = _load_artifact()
        gwr = artifact.get("proposed_compiler_architecture", {}).get(
            "git_worktree_requirement", {}
        )
        rule = gwr.get("staged_accumulation_rule", {})
        assert (
            rule.get(
                "reset_after_failure_resets_to_current_stage_base_not_original_contract_base"
            )
            is True
        ), (
            "Expected reset after failure to use current stage base, not original contract base"
        )
        assert rule.get("slice_n_base_is_stage_n_minus_1_promoted_worktree") is True, (
            "Expected slice N base to be stage N-1 promoted worktree"
        )

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.contract_compiler_research_rationale.v1.schema.json"
)
ARTIFACT_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "compiler"
    / "contract_compiler_research_rationale.v1.json"
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


class TestContractCompilerResearchRationale:
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
            artifact.get("schema_version")
            == "rig.contract_compiler_research_rationale.v1"
        ), (
            f"Expected schema_version 'rig.contract_compiler_research_rationale.v1', got '{artifact.get('schema_version')}'"
        )

    def test_research_sources_are_populated(self):
        artifact = _load_artifact()
        sources = artifact.get("research_sources", [])
        assert len(sources) >= 8, (
            f"Expected at least 8 research sources, got {len(sources)}"
        )
        for src in sources:
            assert src.get("source_id"), f"Missing source_id in {src.get('title', '?')}"
            assert src.get("title"), f"Missing title in {src.get('source_id', '?')}"
            assert src.get("url", "").startswith("http"), (
                f"Missing or invalid URL in {src.get('source_id', '?')}"
            )

    def test_concept_summaries_include_cegis_and_cegar(self):
        artifact = _load_artifact()
        concepts = artifact.get("concept_summaries", {})
        assert "cegis" in concepts, "Missing CEGIS concept summary"
        assert "cegar" in concepts, "Missing CEGAR concept summary"
        cegis = concepts["cegis"]
        assert cegis.get("summary"), "CEGIS summary is empty"
        assert cegis.get("loop_structure"), "CEGIS loop_structure is empty"
        assert cegis.get("key_insight"), "CEGIS key_insight is empty"
        cegar = concepts["cegar"]
        assert cegar.get("spurious_vs_genuine"), "CEGAR spurious_vs_genuine is empty"

    def test_rig_mapping_matrix_has_required_concepts(self):
        artifact = _load_artifact()
        matrix = artifact.get("rig_mapping_matrix", [])
        concepts = {r["concept"] for r in matrix}
        required = [
            "generator",
            "verifier",
            "candidate",
            "specification",
            "counterexample",
            "refinement",
            "abstraction",
            "partial_success",
            "promotion",
        ]
        for req in required:
            assert req in concepts, f"Missing mapping matrix concept: {req}"

    def test_mapping_matrix_entries_include_cegis_cegar_rig_meanings(self):
        artifact = _load_artifact()
        for row in artifact.get("rig_mapping_matrix", []):
            assert row.get("cegis_meaning"), (
                f"Missing cegis_meaning for concept {row.get('concept', '?')}"
            )
            assert row.get("rig_meaning"), (
                f"Missing rig_meaning for concept {row.get('concept', '?')}"
            )

    def test_literature_challenges_are_ranked(self):
        artifact = _load_artifact()
        challenges = artifact.get("literature_challenges", [])
        assert len(challenges) >= 8, (
            f"Expected at least 8 challenges, got {len(challenges)}"
        )
        ranks = [c["rank"] for c in challenges]
        assert len(ranks) == len(set(ranks)), "Challenge ranks are not unique"
        assert min(ranks) == 1, "Lowest rank should be 1"
        assert max(ranks) <= len(challenges) + 2, "Max rank should be near list length"

    def test_worktree_lifecycle_state_machine_is_defined(self):
        artifact = _load_artifact()
        fsm = artifact.get("worktree_lifecycle_recommendations", {}).get(
            "state_machine", []
        )
        required_states = [
            "created",
            "patch_applied",
            "validation_running",
            "failed_reset",
            "partially_satisfied",
            "promoted_to_stage",
            "fully_satisfied",
            "accepted",
        ]
        state_names = {s["state"] for s in fsm}
        for required in required_states:
            assert required in state_names, f"Missing state machine state: {required}"

    def test_worktree_lifecycle_has_budget_fields(self):
        artifact = _load_artifact()
        budget = artifact.get("worktree_lifecycle_recommendations", {}).get(
            "budget_fields", {}
        )
        required = [
            "max_scratch_worktrees",
            "max_stage_depth",
            "max_candidates_per_slice",
        ]
        for field in required:
            assert field in budget, f"Missing budget field: {field}"
            assert budget[field] > 0, f"Budget field {field} must be positive"

    def test_counterexample_design_has_required_shape(self):
        artifact = _load_artifact()
        shape = artifact.get("counterexample_design", {}).get(
            "counterexample_shape", {}
        )
        fields = shape.get("fields", [])
        field_names = {f["field"] for f in fields}
        required_fields = [
            "counterexample_id",
            "source_gate",
            "failure_class",
            "spurious_or_genuine",
            "deduplication_key",
            "pruning_effect",
        ]
        for req in required_fields:
            assert req in field_names, f"Missing counterexample field: {req}"

    def test_validation_matrix_has_required_for_first_proof_validators(self):
        artifact = _load_artifact()
        matrix = artifact.get("validation_matrix_recommendations", [])
        required_validators = {
            v["validator"]
            for v in matrix
            if v.get("implementation_status") == "required_for_first_proof"
        }
        expected = {
            "json_schema_validation",
            "generated_python_importability",
            "pyright_type_check",
            "deterministic_regeneration",
            "adversarial_malformed_input",
            "content_light_redaction",
        }
        missing = expected - required_validators
        assert not missing, f"Missing required-for-first-proof validators: {missing}"

    def test_pattern_aggregation_products_are_defined(self):
        artifact = _load_artifact()
        products = artifact.get("pattern_aggregation_recommendations", [])
        assert len(products) >= 5, f"Expected at least 5 products, got {len(products)}"
        product_ids = {p["product_id"] for p in products}
        required = {
            "permutation_corpus.v1.jsonl",
            "schema_pattern_report.v1.json",
            "counterexample_cluster_report.v1.json",
            "contract_ambiguity_report.v1.json",
        }
        assert required <= product_ids, f"Missing products: {required - product_ids}"

    def test_claim_boundaries_define_both_may_and_must_not(self):
        artifact = _load_artifact()
        boundaries = artifact.get("claim_boundaries", {})
        may = boundaries.get("rig_may_claim", [])
        must_not = boundaries.get("rig_must_not_claim", [])
        assert len(may) >= 5, f"Expected at least 5 may-claim entries, got {len(may)}"
        assert len(must_not) >= 4, (
            f"Expected at least 4 must-not-claim entries, got {len(must_not)}"
        )

    def test_humility_boundaries_include_rices_theorem(self):
        artifact = _load_artifact()
        humility = artifact.get("humility_boundaries", {})
        assert humility.get("rices_theorem"), "Missing Rice's theorem humility boundary"
        assert "undecidable" in humility["rices_theorem"].lower(), (
            "Rice's theorem boundary should mention undecidability"
        )
        assert humility.get("symbolic_not_neural_learning"), (
            "Missing symbolic-not-neural-learning humility boundary"
        )

    def test_final_recommendation_adopts_cegis_inspired_model(self):
        artifact = _load_artifact()
        final = artifact.get("final_recommendation", {})
        assert final.get("should_adopt_cegis_cegar_inspired_model") is True, (
            "Expected recommendation to adopt CEGIS/CEGAR-inspired model"
        )
        assert final.get("smallest_useful_compiler_experiment"), (
            "Missing smallest useful compiler experiment description"
        )

    def test_proposed_schemas_and_events_are_defined(self):
        artifact = _load_artifact()
        proposed = artifact.get("proposed_rig_schemas_and_events", {})
        schemas = proposed.get("candidate_schemas", [])
        events = proposed.get("candidate_events", [])
        assert len(schemas) >= 5, (
            f"Expected at least 5 candidate schemas, got {len(schemas)}"
        )
        assert len(events) >= 10, (
            f"Expected at least 10 candidate events, got {len(events)}"
        )

    def test_rig_compiler_differentiation_is_defined(self):
        artifact = _load_artifact()
        diff = artifact.get("concept_summaries", {}).get(
            "rig_compiler_differentiation", {}
        )
        assert diff.get("staged_decomposition"), "Missing staged_decomposition"
        assert diff.get("real_world_worktree_validation"), (
            "Missing real_world_worktree_validation"
        )
        assert diff.get("evidence_first"), "Missing evidence_first"
        assert diff.get("symbolic_not_neural"), "Missing symbolic_not_neural"

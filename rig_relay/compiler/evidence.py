from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from rig_relay.compiler.hashes import compute_sha256, hash_path


@dataclass
class CompilerEvidence:
    evidence_dir: Path

    def __post_init__(self) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, filename: str, data: dict) -> Path:
        path = self.evidence_dir / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def write_jsonl(self, filename: str, record: dict) -> Path:
        path = self.evidence_dir / filename
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return path

    def write_candidate_record(
        self,
        candidate_id: str,
        run_id: str,
        contract_family_id: str,
        schema_version: str,
        candidate_sha256: str,
        schema_sha256: str,
        base_head_sha: str,
        status: str,
    ) -> Path:
        record = {
            "schema_version": "rig.contract_compiler.candidate.v1",
            "candidate_id": candidate_id,
            "run_id": run_id,
            "contract_family_id": contract_family_id,
            "contract_slice_id": "slice-0",
            "parent_stage_id": "",
            "candidate_kind": "combined_candidate",
            "candidate_status": status,
            "semantic_contract_sha256": compute_sha256(schema_version),
            "schema_candidate_sha256": schema_sha256,
            "python_candidate_sha256": candidate_sha256,
            "candidate_patch_sha256": candidate_sha256,
            "generator_id": "jinja2_template_v0",
            "generator_version": "0.0.1-dev",
            "worktree_id": candidate_id,
            "worktree_path_hash": hash_path(self.evidence_dir),
            "base_head_sha": base_head_sha,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "content_light": True,
            "redaction_status": "content_light",
        }
        return self.write_json("candidate.v1.json", record)

    def write_validation_matrix(
        self, matrix: dict, run_id: str, candidate_id: str
    ) -> Path:
        result = {
            "schema_version": "rig.contract_compiler.validation_matrix_result.v1",
            **matrix,
            "content_light": True,
            "redaction_status": "content_light",
        }
        return self.write_json("validation_matrix_result.v1.json", result)

    def write_worktree_lifecycle(
        self,
        run_id: str,
        candidate_id: str,
        lifecycle_state: str,
        previous_state: str,
        next_state: str,
        worktree_dir: Path,
        base_head_sha: str,
        event_reason: str,
        cleanup_action: str = "none",
    ) -> Path:
        event = {
            "schema_version": "rig.contract_compiler.worktree_lifecycle.v1",
            "event_id": f"evt-{candidate_id}-{lifecycle_state}",
            "run_id": run_id,
            "candidate_id": candidate_id,
            "worktree_id": candidate_id,
            "worktree_kind": "scratch_candidate",
            "lifecycle_state": lifecycle_state,
            "previous_state": previous_state,
            "next_state": next_state,
            "worktree_path_hash": hash_path(worktree_dir),
            "base_head_sha": base_head_sha,
            "current_head_sha": base_head_sha,
            "dirty_state": "clean",
            "emitted_at": _now_iso(),
            "event_reason": event_reason,
            "cleanup_action": cleanup_action,
            "content_light": True,
            "redaction_status": "content_light",
        }
        return self.write_jsonl("worktree_lifecycle.v1.jsonl", event)

    def write_run_manifest(
        self,
        run_id: str,
        base_head_sha: str,
        contract_family_id: str,
        schema_version: str,
        gate_summary: dict,
        candidate_count: int,
        accepted: int,
        rejected: int,
        quarantined: int,
        counterexamples: int,
    ) -> Path:
        manifest = {
            "schema_version": "rig.contract_compiler.run_manifest.v1",
            "run_id": run_id,
            "generated_at": _now_iso(),
            "repo_head_sha": base_head_sha,
            "repo_branch_hash": compute_sha256("main"),
            "semantic_contract_id": contract_family_id,
            "semantic_contract_sha256": compute_sha256(schema_version),
            "compiler_version": "0.0.1-dev",
            "generator_id": "jinja2_template_v0",
            "generator_version": "0.0.1-dev",
            "base_worktree_path_hash": hash_path(self.evidence_dir.parent),
            "evidence_root": str(
                self.evidence_dir.relative_to(self.evidence_dir.parent.parent)
            ),
            "candidate_count": candidate_count,
            "accepted_candidate_count": accepted,
            "rejected_candidate_count": rejected,
            "quarantined_candidate_count": quarantined,
            "counterexample_count": counterexamples,
            "validation_matrix_summary": gate_summary,
            "content_light": True,
            "redaction_status": "content_light",
        }
        return self.write_json("run_manifest.v1.json", manifest)


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat()

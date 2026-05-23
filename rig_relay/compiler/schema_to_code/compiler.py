from __future__ import annotations

import datetime
import json
from pathlib import Path
import uuid

from rig_relay.compiler.evidence import CompilerEvidence
from rig_relay.compiler.gates import GateMatrix
from rig_relay.compiler.hashes import compute_sha256
from rig_relay.compiler.schema_to_code.generator import (
    render_template,
    write_generated_code,
)
from rig_relay.compiler.schema_to_code.reader import (
    derive_model_spec_from_schema,
    load_target_schema,
)
from rig_relay.compiler.schema_to_code.validator import (
    validate_generated_code,
    validate_minimum_safety,
)
from rig_relay.compiler.worktree import CompilerWorktree


def compile_schema_to_code(
    schema_path: Path, output_dir: Path | None = None, run_validation: bool = True
) -> dict:
    if output_dir is None:
        output_dir = Path(".build/rig-relay/compiler/generated")

    repo_root = _find_repo_root(Path.cwd())
    run_id = _generate_run_id()
    candidate_id = f"cand-{run_id[:8]}-{uuid.uuid4().hex[:8]}"

    evidence_dir = output_dir / run_id / "candidates" / candidate_id
    evidence = CompilerEvidence(evidence_dir)

    schema = load_target_schema(schema_path)
    spec = derive_model_spec_from_schema(schema, schema_path)
    code = render_template(spec)
    schema_sha256 = compute_sha256(json.dumps(schema))
    candidate_sha256 = compute_sha256(code)

    worktree_root = Path(".rig/relay/worktrees/compiler")
    wt = CompilerWorktree(worktree_root=worktree_root, repo_root=repo_root)
    worktree_dir = None

    try:
        worktree_dir, base_sha = wt.create(run_id, candidate_id)
        evidence.write_worktree_lifecycle(
            run_id,
            candidate_id,
            "created",
            "",
            "patch_applied",
            worktree_dir,
            base_sha,
            "Scratch worktree created",
        )

        generated_file = (
            worktree_dir
            / "rig_relay"
            / "generated_candidates"
            / f"experiment_0_{candidate_id}.py"
        )
        generated_file = write_generated_code(code, generated_file)
        init_file = generated_file.parent / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")

        evidence.write_worktree_lifecycle(
            run_id,
            candidate_id,
            "patch_applied",
            "created",
            "validation_running",
            worktree_dir,
            base_sha,
            "Candidate patch applied",
        )

        gate_matrix: GateMatrix | None = None
        if run_validation:
            gate_matrix = validate_generated_code(
                worktree_dir, generated_file, schema_path, repo_root=repo_root
            )
        else:
            gate_matrix = validate_minimum_safety(schema_path, generated_file)

        overall = gate_matrix.overall_status.value
        status = "accepted" if overall == "pass" else "rejected"

        evidence.write_candidate_record(
            candidate_id=candidate_id,
            run_id=run_id,
            contract_family_id=spec.contract_family_id,
            schema_version=spec.schema_version,
            candidate_sha256=candidate_sha256,
            schema_sha256=schema_sha256,
            base_head_sha=base_sha,
            status=status,
        )

        matrix_dict = _gate_matrix_to_dict(gate_matrix, run_id, candidate_id)
        evidence.write_validation_matrix(matrix_dict, run_id, candidate_id)

        counterexamples = sum(
            1 for g in gate_matrix.gates if g.status.value in {"fail", "skipped"}
        )

        evidence.write_worktree_lifecycle(
            run_id,
            candidate_id,
            "completed",
            "validation_running",
            "patched"
            if not wt.worktree_dir or not wt.worktree_dir.exists()
            else "reaped",
            worktree_dir,
            base_sha,
            f"Validation {overall}",
            "none",
        )

        gate_summary = {
            "total_gates": gate_matrix.total,
            "passing_gates": gate_matrix.passed,
            "failing_gates": gate_matrix.failed,
            "skipped_gates": gate_matrix.skipped,
            "total_validations_run": 1,
        }
        evidence.write_run_manifest(
            run_id=run_id,
            base_head_sha=base_sha,
            contract_family_id=spec.contract_family_id,
            schema_version=spec.schema_version,
            gate_summary=gate_summary,
            candidate_count=1,
            accepted=1 if overall == "pass" else 0,
            rejected=0 if overall == "pass" else 1,
            quarantined=0,
            counterexamples=counterexamples,
        )

    finally:
        try:
            wt.reap()
        except Exception:
            pass

    return {
        "schema_path": str(schema_path),
        "output_dir": str(output_dir),
        "evidence_dir": str(evidence_dir),
        "generated_file": str(generated_file) if "generated_file" in dir() else "",
        "overall_status": overall if "overall" in dir() else "infra_fail",
        "gate_matrix": gate_matrix.model_dump() if gate_matrix else {},
    }


def _generate_run_id() -> str:
    return f"exp0-{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d-%H%M%S')}"


def _find_repo_root(start: Path) -> Path:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(start),
    )
    return Path(result.stdout.strip())


def _gate_matrix_to_dict(matrix: GateMatrix, run_id: str, candidate_id: str) -> dict:
    return {
        "validation_result_id": f"vr-{candidate_id}",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "worktree_id": candidate_id,
        "overall_status": matrix.overall_status.value,
        "gates": [g.model_dump() for g in matrix.gates],
        "passed_gate_count": matrix.passed,
        "failed_gate_count": matrix.failed,
        "warning_gate_count": 0,
        "counterexample_ids": [],
        "output_artifact_hashes": {},
    }

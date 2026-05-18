#!/usr/bin/env python3
"""Rig Relay Release Gate Validator CLI v1.

Validates the release-candidate readiness gate against structured evidence:
blocker JSONL, validation-run JSONL, schemas, and evidence paths.

Produces a deterministic JSON verdict to stdout. Fails on missing blockers,
missing validation runs, open blockers on passing phases, missing evidence,
Markdown-as-canonical-evidence, missing test classifications, and missing
schema validation results.

Usage:
    uv run python scripts/rig_release_gate_validate.py
    uv run python scripts/rig_release_gate_validate.py --readiness-gate docs/json/release_gate/rc_readiness_gate.v1.json
    uv run python scripts/rig_release_gate_validate.py --blockers docs/json/release_gate/rc_blockers.v1.jsonl
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_READINESS_GATE = (
    REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
)
DEFAULT_BLOCKERS = REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
DEFAULT_VALIDATION_RUNS = (
    REPO_ROOT / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
)
DEFAULT_GOLDEN_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "release_candidate"
    / "rc_reviewer_golden_path.v1.json"
)

MARKDOWN_EVIDENCE_FORBIDDEN_PATTERNS: list[str] = [
    "docs/audits/",
    "docs/reports/",
    "docs/roadmaps/",
    "docs/proofs/",
    "mission-report.md",
    "final-report.md",
    "handoff.md",
]

DEMO_ARTIFACT_PATTERNS: list[str] = [
    ".build/rig-relay/demo/",
    "demo-synthetic",
    "_demo_synthetic",
    "source-demo",
    "demo-seed",
    "demo-doctor",
    "demo-render-docs",
    "demo_commands.py",
    "demo_mode",
    "non_rc_fixture",
]

STEP_TO_BLOCKER: dict[str, str] = {
    "gp_feral_subprocess_accountability": "blk_runtime_feral_subprocess",
    "gp_bash_rerouting_transparency": "blk_bash_rerouting_transparency",
    "gp_telemetry_degradation_visibility": "blk_telemetry_disabled_degradation",
    "gp_debug_packet_quarantine": "blk_debug_packet_quarantine",
}


def check_golden_path(
    golden_path: dict[str, Any] | None, schemas_dir: Path
) -> list[str]:
    """Validate golden path artifact and check blocking step status.

    Returns errors if:
    - Golden path fails schema validation
    - Any step with blocking_failure_conditions has status != 'passing'
    - overall_status is 'blocked' or 'not_verified'
    """
    errors: list[str] = []
    if golden_path is None:
        errors.append(
            "Golden path artifact is missing: "
            "docs/json/release_candidate/rc_reviewer_golden_path.v1.json"
        )
        return errors

    schema_errors = validate_schema_artifact(
        golden_path, "rig.release_candidate.reviewer_golden_path.v1", schemas_dir
    )
    errors.extend(schema_errors)
    if schema_errors:
        return errors

    overall = golden_path.get("overall_status", "not_verified")
    if overall == "blocked":
        errors.append("Golden path overall_status is 'blocked' — cannot PROMOTE")
    elif overall == "not_verified":
        errors.append(
            "Golden path overall_status is 'not_verified' — "
            "a human reviewer must exercise and verify the golden path before PROMOTE"
        )

    steps = golden_path.get("steps", [])
    blocked_steps: list[str] = []
    not_verified_blocking: list[str] = []
    for step in steps:
        step_id = step.get("step_id", "unknown")
        status = step.get("status", "not_verified")
        blocking_conditions = step.get("blocking_failure_conditions", [])
        if not blocking_conditions:
            continue
        if status == "blocked":
            blocked_steps.append(step_id)
        elif status in {"not_verified", "failing"}:
            not_verified_blocking.append(step_id)

    if blocked_steps:
        errors.append(
            f"Golden path has {len(blocked_steps)} blocked step(s) "
            f"with blocking failure conditions: {', '.join(blocked_steps)}"
        )
    if not_verified_blocking:
        errors.append(
            f"Golden path has {len(not_verified_blocking)} not-verified step(s) "
            f"with blocking failure conditions: {', '.join(not_verified_blocking)}"
        )

    return errors


def check_golden_path_blocker_consistency(
    golden_path: dict[str, Any], blockers: list[dict[str, Any]], repo_root: Path
) -> list[str]:
    errors: list[str] = []
    blocker_map = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}

    for step in golden_path.get("steps", []):
        step_id = step.get("step_id", "unknown")
        step_status = step.get("status", "not_verified")
        blocker_id = STEP_TO_BLOCKER.get(step_id)
        validation_method = step.get("validation_method", "manual_review")
        evidence_path = step.get("evidence_path", "")

        if blocker_id:
            blocker = blocker_map.get(blocker_id)

            if step_status == "passing":
                if blocker and blocker.get("status") == "open":
                    errors.append(
                        f"CONSISTENCY FAIL: golden path step {step_id} is 'passing' "
                        f"but linked blocker {blocker_id} is still 'open'. "
                        f"Golden path step must remain blocked until blocker is resolved."
                    )

            elif step_status == "blocked":
                if blocker is None:
                    errors.append(
                        f"CONSISTENCY FAIL: golden path step {step_id} is 'blocked' "
                        f"but linked blocker {blocker_id} is not found in blockers JSONL."
                    )
                elif blocker.get("status") == "resolved":
                    errors.append(
                        f"CONSISTENCY FAIL: golden path step {step_id} is 'blocked' "
                        f"but linked blocker {blocker_id} is 'resolved'. "
                        f"Either blocker was re-opened or golden path step was not unblocked."
                    )

            elif step_status == "failing":
                if blocker and blocker.get("status") == "resolved":
                    errors.append(
                        f"CONSISTENCY FAIL: golden path step {step_id} is 'failing' "
                        f"but linked blocker {blocker_id} is 'resolved'. "
                        f"Step should not be failing if its blocker is resolved."
                    )

        if step_status == "passing" and validation_method == "automated_script":
            evidence_ok = False
            if evidence_path:
                ep = Path(evidence_path)
                if ep.is_absolute():
                    evidence_ok = ep.exists()
                else:
                    evidence_ok = (repo_root / ep).exists()
            if not evidence_ok and not evidence_path.startswith("N/A"):
                errors.append(
                    f"CONSISTENCY FAIL: golden path step {step_id} is 'passing' "
                    f"(automated) but evidence_path '{evidence_path}' does not exist."
                )

    return errors


def load_artifact(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                entries.append({"_parse_error": str(e), "_raw": line})
    return entries


def validate_schema_artifact(
    artifact: dict[str, Any], schema_id: str, schemas_dir: Path
) -> list[str]:
    errors: list[str] = []
    try:
        import jsonschema

        schema_path = schemas_dir / f"{schema_id}.schema.json"
        if not schema_path.is_file():
            errors.append(f"Schema file not found for schema_id={schema_id}")
            return errors

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(artifact):
            errors.append(
                f"Schema validation error at {'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
            )
    except Exception as e:
        errors.append(f"Schema validation exception: {e}")
    return errors


def is_demo_artifact_path(p: str) -> bool:
    for pat in DEMO_ARTIFACT_PATTERNS:
        if pat in p:
            return True
    return False


def is_markdown_path(p: str) -> bool:
    return p.endswith(".md") or p.endswith(".mdx") or p.endswith(".markdown")


def is_forbidden_markdown_evidence(p: str) -> bool:
    if not is_markdown_path(p):
        return False
    return any(
        p.startswith(pat) or pat in p for pat in MARKDOWN_EVIDENCE_FORBIDDEN_PATTERNS
    )


def is_markdown_allowed(p: str, allowed_exceptions: list[str]) -> bool:
    if not is_markdown_path(p):
        return False
    p_stripped = p.lstrip("./")
    for exc in allowed_exceptions:
        exc_stripped = exc.lstrip("./")
        if (
            p_stripped == exc_stripped
            or p_stripped.endswith("/" + exc_stripped)
            or p_stripped.endswith(exc_stripped)
        ):
            return True
    return False


def check_evidence_paths(
    evidence_paths: list[str], repo_root: Path, allowed_exceptions: list[str]
) -> list[str]:
    errors: list[str] = []
    for p in evidence_paths:
        full_path = repo_root / p
        if not full_path.exists():
            errors.append(f"Evidence path missing: {p}")
            continue
        if is_forbidden_markdown_evidence(p) and not is_markdown_allowed(
            p, allowed_exceptions
        ):
            errors.append(
                f"Forbidden Markdown evidence path: {p} "
                f"(not in allowed_markdown_exceptions; use JSON/JSONL/CSV artifacts)"
            )
        if is_demo_artifact_path(p):
            errors.append(
                f"DEMO EVIDENCE REJECTED: {p} references demo artifacts "
                f"(demo-synthetic, demo_commands, .build/rig-relay/demo/). "
                f"RC evidence must not include demo-generated data."
            )
    return errors


def check_phase_blockers(
    phases: list[dict[str, Any]], blockers: list[dict[str, Any]], policy: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    blocker_ids = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}

    for phase in phases:
        phase_id = phase.get("phase_id", "unknown")
        for bid in phase.get("blocker_ids", []):
            if bid not in blocker_ids:
                errors.append(f"Phase {phase_id} references missing blocker: {bid}")

    if policy.get("passing_phase_blocker_check", True):
        for phase in phases:
            if phase.get("status") != "passing":
                continue
            phase_id = phase.get("phase_id", "unknown")
            for bid in phase.get("blocker_ids", []):
                blocker = blocker_ids.get(bid)
                if blocker and blocker.get("status") == "open":
                    errors.append(
                        f"Phase {phase_id} has status 'passing' but blocker "
                        f"{bid} is still open"
                    )

    return errors


def check_validation_runs(
    phases: list[dict[str, Any]],
    validation_runs: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    run_ids = {
        r["validation_run_id"]: r for r in validation_runs if "_parse_error" not in r
    }

    for phase in phases:
        phase_id = phase.get("phase_id", "unknown")
        for rid in phase.get("validation_run_ids", []):
            if rid not in run_ids:
                errors.append(
                    f"Phase {phase_id} references missing validation run: {rid}"
                )

    if policy.get("test_classification_enforcement", True):
        for run in validation_runs:
            if "_parse_error" in run:
                continue
            rid = run.get("validation_run_id", "unknown")
            tests_run = run.get("tests_run", 0)
            classifications = run.get("test_classifications")
            if (
                tests_run
                and tests_run > 0
                and (
                    not classifications
                    or not isinstance(classifications, dict)
                    or len(classifications) == 0
                )
            ):
                errors.append(
                    f"Validation run {rid} reports {tests_run} tests_run "
                    f"but omits test_classifications"
                )

    return errors


def check_schema_governed_artifacts(
    phases: list[dict[str, Any]], validation_runs: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    schema_artifacts: set[str] = set()
    for phase in phases:
        for p in phase.get("schema_artifact_paths", []):
            schema_artifacts.add(p)

    if not schema_artifacts:
        return errors

    run_results: dict[str, dict[str, Any]] = {}
    for run in validation_runs:
        if "_parse_error" in run:
            continue
        schema_results = run.get("schema_validation_results", {})
        if isinstance(schema_results, dict):
            for s_path, s_result in schema_results.items():
                run_results[s_path] = s_result

    for s_path in schema_artifacts:
        if s_path not in run_results:
            errors.append(
                f"Schema-governed artifact {s_path} has no schema validation "
                f"result in any validation run"
            )

    return errors


def check_jsonl_parse_errors(
    blockers: list[dict[str, Any]], validation_runs: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    for i, b in enumerate(blockers):
        if "_parse_error" in b:
            errors.append(
                f"Malformed JSONL blocker at entry {i + 1}: {b['_parse_error']}"
            )
    for i, r in enumerate(validation_runs):
        if "_parse_error" in r:
            errors.append(
                f"Malformed JSONL validation run at entry {i + 1}: {r['_parse_error']}"
            )
    return errors


def check_stale_evidence(
    phases: list[dict[str, Any]],
    validation_runs: list[dict[str, Any]],
    repo_root: Path,
    current_head: str,
) -> list[str]:
    """Detect phase statuses referencing commits older than current HEAD.

    Validation runs are append-only historical evidence. Only the runs
    referenced by the current readiness gate phases are checked for staleness;
    unreferenced archived rows are intentionally ignored.
    """
    errors: list[str] = []
    if not current_head:
        return errors

    referenced_run_ids = {
        rid
        for phase in phases
        for rid in phase.get("validation_run_ids", [])
        if isinstance(rid, str)
    }

    for run in validation_runs:
        if "_parse_error" in run:
            continue
        run_id = run.get("validation_run_id", "")
        if run_id not in referenced_run_ids:
            continue
        run_commit = run.get("source_commit", "")
        if run_commit and run_commit != current_head:
            errors.append(
                f"Validation run {run_id} is stale: "
                f"source_commit={run_commit[:8]} != HEAD={current_head[:8]}"
            )

    for phase in phases:
        phase_commit = phase.get("source_commit", "")
        if (
            phase.get("status") in {"passing", "ready"}
            and phase_commit
            and phase_commit != current_head
        ):
            errors.append(
                f"Phase {phase.get('phase_id')} is stale: "
                f"source_commit={phase_commit[:8]} != HEAD={current_head[:8]}"
            )

    return errors


def resolve_head_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def resolve_branch(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        return ""


def _validate_entries(
    entries: list[dict[str, Any]], schema_id: str, schemas_dir: Path, label: str
) -> list[str]:
    errors: list[str] = []
    for i, entry in enumerate(entries):
        if "_parse_error" in entry:
            continue
        for err in validate_schema_artifact(entry, schema_id, schemas_dir):
            errors.append(f"{label} entry {i + 1}: {err}")
    return errors


def _build_phase_summaries(
    phases: list[dict[str, Any]], errors: list[str]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for phase in phases:
        phase_id = phase.get("phase_id", "unknown")
        phase_errors = [e for e in errors if phase_id in e]
        summaries.append({
            "phase_id": phase_id,
            "title": phase.get("title", ""),
            "status": phase.get("status", "unknown"),
            "error_count": len(phase_errors),
            "blocker_count": len(phase.get("blocker_ids", [])),
            "evidence_count": len(phase.get("required_evidence", [])),
            "validation_run_count": len(phase.get("validation_run_ids", [])),
        })
    return summaries


def run_validation(
    readiness_gate_path: Path,
    blockers_path: Path,
    validation_runs_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    artifact_counts: dict[str, int] = {
        "schemas_validated": 0,
        "blockers_loaded": 0,
        "validation_runs_loaded": 0,
        "phases": 0,
    }
    schemas_dir = repo_root / "docs" / "schemas"

    try:
        gate = load_artifact(readiness_gate_path)
    except Exception as e:
        return _error_result(
            str(repo_root), [f"Failed to load readiness gate: {e}"], artifact_counts
        )

    errors.extend(
        validate_schema_artifact(gate, "rig.release_gate.readiness.v1", schemas_dir)
    )

    blockers = load_jsonl(blockers_path)
    artifact_counts["blockers_loaded"] = len(blockers)

    validation_runs = load_jsonl(validation_runs_path)
    artifact_counts["validation_runs_loaded"] = len(validation_runs)

    errors.extend(
        _validate_entries(
            blockers, "rig.release_gate.blocker.v1", schemas_dir, "Blocker"
        )
    )
    errors.extend(
        _validate_entries(
            validation_runs,
            "rig.release_gate.validation_run.v1",
            schemas_dir,
            "Validation run",
        )
    )
    artifact_counts["schemas_validated"] = len(blockers) + len(validation_runs)

    errors.extend(check_jsonl_parse_errors(blockers, validation_runs))

    phases = gate.get("phases", [])
    artifact_counts["phases"] = len(phases)
    policy = gate.get("policy", {})

    allowed_exceptions = policy.get("allowed_markdown_exceptions", [])
    for phase in phases:
        errors.extend(
            check_evidence_paths(
                phase.get("required_evidence", []), repo_root, allowed_exceptions
            )
        )

    errors.extend(check_phase_blockers(phases, blockers, policy))
    errors.extend(check_validation_runs(phases, validation_runs, policy))
    errors.extend(check_schema_governed_artifacts(phases, validation_runs))

    current_head = resolve_head_sha(repo_root)
    errors.extend(
        check_stale_evidence(phases, validation_runs, repo_root, current_head)
    )

    golden_path: dict[str, Any] | None = None
    golden_path_path = (
        repo_root
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_reviewer_golden_path.v1.json"
    )
    if golden_path_path.is_file():
        try:
            golden_path = load_artifact(golden_path_path)
            artifact_counts["golden_path_loaded"] = 1
        except Exception as e:
            errors.append(f"Failed to load golden path artifact: {e}")

    if golden_path is not None:
        errors.extend(check_golden_path(golden_path, schemas_dir))
        errors.extend(
            check_evidence_paths(
                golden_path.get("evidence_paths", []), repo_root, allowed_exceptions
            )
        )
        errors.extend(
            check_golden_path_blocker_consistency(golden_path, blockers, repo_root)
        )

    phase_summaries = _build_phase_summaries(phases, errors)
    status = "passed" if len(errors) == 0 else "failed"
    verdict = _compute_verdict(errors, phases, blockers, golden_path)

    return {
        "status": status,
        "verdict": verdict,
        "errors": errors,
        "warnings": [],
        "artifact_counts": artifact_counts,
        "phase_summaries": phase_summaries,
        "validated_at": _now_iso(),
        "repository": str(repo_root),
        "head_sha": resolve_head_sha(repo_root),
        "branch": resolve_branch(repo_root),
    }


def _error_result(
    repo_root: str, errors: list[str], artifact_counts: dict[str, int]
) -> dict[str, Any]:
    return {
        "status": "failed",
        "verdict": "FAIL",
        "errors": errors,
        "warnings": [],
        "artifact_counts": artifact_counts,
        "phase_summaries": [],
        "validated_at": _now_iso(),
        "repository": str(repo_root),
        "head_sha": "",
        "branch": "",
    }


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_verdict(
    errors: list[str],
    phases: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    golden_path: dict[str, Any] | None = None,
) -> str:
    if errors:
        consistency_errors = [e for e in errors if "CONSISTENCY FAIL" in e]
        if consistency_errors:
            return "FAIL"
        blocked_notice_errors = [
            e
            for e in errors
            if "blocked step" in e.lower()
            or "not-verified" in e.lower()
            or "cannot promote" in e.lower()
            or "overall_status" in e.lower()
        ]
        other_errors = [e for e in errors if e not in blocked_notice_errors]
        if not other_errors:
            return "BLOCKED"
        return "FAIL"
    blocker_ids_map = {b["blocker_id"]: b for b in blockers if "_parse_error" not in b}
    for phase in phases:
        if phase.get("status") == "blocked":
            return "BLOCKED"
        for bid in phase.get("blocker_ids", []):
            blocker = blocker_ids_map.get(bid)
            if blocker and blocker.get("status") == "open":
                return "BLOCKED"
    if golden_path is not None:
        for step in golden_path.get("steps", []):
            step_status = step.get("status", "not_verified")
            blocking_conditions = step.get("blocking_failure_conditions", [])
            if step_status == "not_verified" and blocking_conditions:
                return "BLOCKED"
    return "PASS"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-release-gate-validate",
        description="Validate the release-candidate readiness gate against structured evidence.",
    )
    parser.add_argument(
        "--readiness-gate",
        type=Path,
        default=DEFAULT_READINESS_GATE,
        help=f"Path to readiness gate JSON (default: {DEFAULT_READINESS_GATE})",
    )
    parser.add_argument(
        "--blockers",
        type=Path,
        default=DEFAULT_BLOCKERS,
        help=f"Path to blockers JSONL (default: {DEFAULT_BLOCKERS})",
    )
    parser.add_argument(
        "--validation-runs",
        type=Path,
        default=DEFAULT_VALIDATION_RUNS,
        help=f"Path to validation runs JSONL (default: {DEFAULT_VALIDATION_RUNS})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help=f"Repository root (default: {REPO_ROOT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    repo_root = args.repo_root.resolve()

    readiness_gate = args.readiness_gate
    if readiness_gate == DEFAULT_READINESS_GATE and repo_root != REPO_ROOT:
        readiness_gate = (
            repo_root / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
        )

    blockers = args.blockers
    if blockers == DEFAULT_BLOCKERS and repo_root != REPO_ROOT:
        blockers = repo_root / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"

    validation_runs = args.validation_runs
    if validation_runs == DEFAULT_VALIDATION_RUNS and repo_root != REPO_ROOT:
        validation_runs = (
            repo_root / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
        )

    result = run_validation(
        readiness_gate_path=readiness_gate,
        blockers_path=blockers,
        validation_runs_path=validation_runs,
        repo_root=repo_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())

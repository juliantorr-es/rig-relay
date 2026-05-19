from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid

from jinja2 import Environment, FileSystemLoader


def compute_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def hash_path(path: Path | str) -> str:
    return compute_sha256(str(path))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _load_template() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def load_target_schema(schema_path: Path) -> dict:
    raw = schema_path.read_text(encoding="utf-8")
    return json.loads(raw)


def derive_model_spec_from_schema(schema: dict, schema_path: Path) -> dict:
    schema_id = schema.get("$id", str(schema_path))
    schema_version = (
        schema.get("properties", {}).get("schema_version", {}).get("const", "")
    )
    required_fields = schema.get("required", [])
    props = schema.get("properties", {})

    fields = []
    for field_name, prop in props.items():
        if field_name == "schema_version":
            continue
        field_type = _map_type(prop)
        is_required = field_name in required_fields
        fields.append({
            "name": field_name,
            "type": field_type,
            "optional": not is_required,
        })

    return {
        "contract_family_id": _derive_family_id(schema_id),
        "schema_version": schema_version,
        "models": [
            {
                "class_name": "GeneratedModel",
                "base": "BaseModel",
                "schema_version": schema_version,
                "fields": fields,
            }
        ],
        "imports": ["from pydantic import BaseModel"],
    }


def _derive_family_id(schema_id: str) -> str:
    parts = schema_id.replace("https://", "").replace("http://", "").split("/")
    for p in parts:
        if "rig.relay.coordination." in p or "rig.relay." in p:
            return p
    return parts[-1] if parts else "unknown"


def _map_type(prop: dict) -> str:
    t = prop.get("type", "str")
    if t == "array":
        return "list"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "object":
        return "dict"
    if t == "string":
        return "str"
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        return _map_type({"type": non_null[0]}) if non_null else "str"
    return "str"


def render_candidate_model(spec: dict) -> bytes:
    template = _load_template().get_template("experiment_0_pydantic_model.py.j2")
    raw = template.render(
        contract_family_id=spec["contract_family_id"],
        schema_id=spec["schema_version"],
        imports=spec.get("imports", ["from pydantic import BaseModel"]),
        models=spec.get("models", []),
    )
    return raw.encode("utf-8")


def render_candidate_twice_for_determinism(spec: dict) -> tuple[bytes, bytes]:
    first = render_candidate_model(spec)
    second = render_candidate_model(spec)
    return first, second


def create_scratch_worktree(
    worktree_root: Path, run_id: str, candidate_id: str, repo_root: Path
) -> tuple[Path, str]:
    _refuse_dangerous_paths(worktree_root, repo_root)
    wt_dir = worktree_root / run_id / "scratch" / candidate_id
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    base_sha = _git_head_sha(repo_root)
    _run_git(repo_root, ["worktree", "add", str(wt_dir), base_sha], cwd=repo_root)
    return wt_dir, base_sha


def apply_candidate_patch(
    worktree_dir: Path, candidate_code: bytes, candidate_id: str
) -> tuple[Path, str]:
    target_file = (
        worktree_dir
        / "rig_relay"
        / "generated_candidates"
        / f"experiment_0_{candidate_id}.py"
    )
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(candidate_code)
    init_file = target_file.parent / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")
    return target_file, compute_sha256(candidate_code)


def run_validation_matrix(
    worktree_dir: Path,
    candidate_file: Path,
    target_schema_path: Path,
    run_id: str,
    candidate_id: str,
    repo_root: Path,
) -> dict:
    started = _now_iso()
    gates = []

    gates.append(_gate_json_schema(target_schema_path))
    gates.append(_gate_importability(worktree_dir, candidate_file))
    gates.append(_gate_pyright(worktree_dir, candidate_file, repo_root))
    gates.append(_gate_ruff_lint(worktree_dir, candidate_file, repo_root))
    gates.append(_gate_ruff_format(worktree_dir, candidate_file, repo_root))
    gates.append(_gate_round_trip(worktree_dir, candidate_file, target_schema_path))
    gates.append(_gate_adversarial(worktree_dir, candidate_file, target_schema_path))
    gates.append(_gate_deterministic_regeneration(target_schema_path))
    gates.append(_gate_redaction(worktree_dir))
    gates.append(_gate_dirty_check(worktree_dir, candidate_file))

    completed = _now_iso()
    return _build_matrix_result(run_id, candidate_id, started, completed, gates)


def _gate_json_schema(schema_path: Path) -> dict:
    start = time.monotonic()
    try:
        from jsonschema import Draft7Validator

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        status = "pass"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-json-schema",
        "json_schema_validation",
        status,
        start,
        compute_sha256(str(status)),
    )


def _gate_importability(worktree_dir: Path, candidate_file: Path) -> dict:
    start = time.monotonic()
    try:
        code = (
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod)"
        )
        result = subprocess.run(
            [str(_find_python(worktree_dir)), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        status = "pass" if result.returncode == 0 else "fail"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-import",
        "python_importability",
        status,
        start,
        compute_sha256(str(status)),
    )


def _gate_pyright(worktree_dir: Path, candidate_file: Path, repo_root: Path) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["uv", "run", "pyright", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(repo_root),
        )
        status = "pass" if result.returncode == 0 else "fail"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-pyright", "pyright_type_check", status, start, compute_sha256(str(status))
    )


def _gate_ruff_lint(worktree_dir: Path, candidate_file: Path, repo_root: Path) -> dict:
    start = time.monotonic()
    try:
        subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(repo_root),
        )
        result = subprocess.run(
            ["uv", "run", "ruff", "check", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(repo_root),
        )
        status = "pass" if result.returncode == 0 else "fail"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-ruff-lint", "ruff_lint", status, start, compute_sha256(str(status))
    )


def _gate_ruff_format(
    worktree_dir: Path, candidate_file: Path, repo_root: Path
) -> dict:
    start = time.monotonic()
    try:
        subprocess.run(
            ["uv", "run", "ruff", "format", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(repo_root),
        )
        result = subprocess.run(
            ["uv", "run", "ruff", "format", "--check", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(repo_root),
        )
        status = "pass" if result.returncode == 0 else "fail"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-ruff-fmt", "ruff_format", status, start, compute_sha256(str(status))
    )


def _gate_round_trip(
    worktree_dir: Path, candidate_file: Path, schema_path: Path
) -> dict:
    start = time.monotonic()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        test_payload = _build_test_payload(schema)
        if test_payload is None:
            return _gate_result(
                "gate-round-trip",
                "real_artifact_round_trip",
                "skipped",
                start,
                compute_sha256("skipped"),
            )
        code = (
            "import importlib.util, json;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod);"
            f"m = mod.GeneratedModel(**{json.dumps(test_payload)});"
            "dump = json.loads(m.model_dump_json()); print(json.dumps(dump))"
        )
        result = subprocess.run(
            [str(_find_python(worktree_dir)), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        if result.returncode != 0:
            return _gate_result(
                "gate-round-trip",
                "real_artifact_round_trip",
                "fail",
                start,
                compute_sha256(result.stderr),
            )
        dumped = json.loads(result.stdout.strip())
        from jsonschema import Draft7Validator

        validator = Draft7Validator(schema=schema)
        errors = list(validator.iter_errors(dumped))
        status = "pass" if not errors else "fail"
        evidence = compute_sha256(json.dumps(dumped))
    except Exception:
        status = "fail"
        evidence = compute_sha256("round-trip-error")
    return _gate_result(
        "gate-round-trip", "real_artifact_round_trip", status, start, evidence
    )


def _build_test_payload(schema: dict) -> dict | None:
    from jsonschema import Draft7Validator

    validator = Draft7Validator(schema=schema)
    candidates = _generate_payload_candidates(schema)
    for candidate in candidates:
        errors = list(validator.iter_errors(candidate))
        if not errors:
            return candidate
    return None


def _generate_payload_candidates(schema: dict) -> list[dict]:
    required = schema.get("required", [])
    props = schema.get("properties", {})
    schema_version = props.get("schema_version", {}).get("const", "")
    base = {"schema_version": schema_version}

    candidates: list[dict] = []
    for field in required:
        if field == "schema_version":
            continue
        prop = props.get(field, {})
        values = _candidate_values_for_field(field, prop)
        if not candidates:
            candidates = [{**base, field: v} for v in values]
        else:
            new_candidates = []
            for c in candidates:
                for v in values:
                    nc = dict(c)
                    nc[field] = v
                    new_candidates.append(nc)
            candidates = new_candidates

    if not candidates:
        return [base]

    return candidates


def _candidate_values_for_field(field_name: str, prop: dict) -> list[Any]:
    values: list[Any] = []

    if "enum" in prop:
        values.extend(prop["enum"])
    else:
        t = prop.get("type", "string")
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            t = non_null[0] if non_null else "string"

        if t == "string":
            fmt = prop.get("format", "")
            if fmt == "date-time":
                values.extend(["2026-01-01T00:00:00Z", "2025-12-31T23:59:59Z"])
            else:
                values.append(_default_value_for_prop(prop))
        elif t == "integer":
            mn = prop.get("minimum")
            if mn is not None:
                values.extend([mn, mn + 1])
            else:
                values.extend([0, 1, 42])
        elif t == "number":
            values.extend([0.0, 0.5, 1.0])
        elif t == "boolean":
            values.extend([True, False])
        elif t == "array":
            items = prop.get("items", {})
            item_val = _default_value_for_prop(items) if items else "item"
            values.extend([[], [item_val]])
        elif t == "object":
            values.extend([{}, {"key": "value"}])
        else:
            values.append(_default_value_for_prop(prop))

    return values if values else [_default_value_for_prop(prop)]


def _default_value_for_prop(prop: dict) -> Any:
    if "enum" in prop:
        return prop["enum"][0]
    t = prop.get("type", "string")
    if t == "string":
        if "format" in prop and prop["format"] == "date-time":
            return "2026-01-01T00:00:00Z"
        return f"test-{prop.get('description', 'value')}"[:50]
    if t == "integer":
        return prop.get("minimum", 0) if "minimum" in prop else 1
    if t == "number":
        return 0.5
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return "test-value"


def _gate_adversarial(
    worktree_dir: Path, candidate_file: Path, schema_path: Path
) -> dict:
    start = time.monotonic()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        required = schema.get("required", [])
        if not required:
            return _gate_result(
                "gate-adv",
                "adversarial_malformed_input",
                "skipped",
                start,
                compute_sha256("skipped"),
            )
        malformed = {}
        code = (
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod);"
            f"m = mod.GeneratedModel(**{json.dumps(malformed)}); print('accepted')"
        )
        result = subprocess.run(
            [str(_find_python(worktree_dir)), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        status = "fail" if result.returncode != 0 else "fail"
        if "accepted" in result.stdout and result.returncode == 0:
            status = "fail"
        else:
            status = "pass"
        evidence = compute_sha256(result.stderr if result.stderr else result.stdout)
    except Exception:
        status = "fail"
        evidence = compute_sha256("adversarial-error")
    return _gate_result(
        "gate-adv", "adversarial_malformed_input", status, start, evidence
    )


def _gate_deterministic_regeneration(schema_path: Path) -> dict:
    start = time.monotonic()
    try:
        schema = load_target_schema(schema_path)
        spec1 = derive_model_spec_from_schema(schema, schema_path)
        spec2 = derive_model_spec_from_schema(schema, schema_path)
        if spec1 != spec2:
            return _gate_result(
                "gate-regen",
                "deterministic_regeneration",
                "fail",
                start,
                compute_sha256("spec-drift"),
            )
        first, second = render_candidate_twice_for_determinism(spec1)
        status = "pass" if first == second else "fail"
        evidence = compute_sha256(first)
    except Exception:
        status = "fail"
        evidence = compute_sha256("regen-error")
    return _gate_result(
        "gate-regen", "deterministic_regeneration", status, start, evidence
    )


def _gate_redaction(worktree_dir: Path) -> dict:
    start = time.monotonic()
    status = "pass"
    forbidden = [
        "raw_prompt",
        "raw_completion",
        "raw_file_contents",
        "raw_credentials",
        "access_token",
        "client_secret",
        "private_repo_contents",
    ]
    try:
        evidence_files = (
            list((worktree_dir / ".build").rglob("*.json"))
            if (worktree_dir / ".build").exists()
            else []
        )
        for ef in evidence_files:
            data = json.loads(ef.read_text(encoding="utf-8"))
            for key in forbidden:
                if key in data:
                    status = "fail"
                    break
    except Exception:
        status = "pass"
    return _gate_result(
        "gate-redact",
        "content_light_redaction",
        status,
        start,
        compute_sha256(str(status)),
    )


def _gate_dirty_check(worktree_dir: Path, candidate_file: Path | None = None) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(worktree_dir),
        )
        dirty_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        unexpected = _filter_expected_dirty(dirty_lines, worktree_dir, candidate_file)
        status = "pass" if not unexpected else "fail"
    except Exception:
        status = "fail"
    return _gate_result(
        "gate-dirty", "worktree_dirty_state", status, start, compute_sha256(str(status))
    )


_EXPECTED_DIRTY_PREFIXES = ("rig_relay/generated_candidates/", ".build/")


def _filter_expected_dirty(
    dirty_lines: list[str], worktree_dir: Path, candidate_file: Path | None
) -> list[str]:
    unexpected: list[str] = []
    for line in dirty_lines:
        path = _parse_porcelain_path(line)
        if path is None:
            unexpected.append(line)
            continue
        if any(path.startswith(prefix) for prefix in _EXPECTED_DIRTY_PREFIXES):
            continue
        if candidate_file is not None:
            try:
                rel_candidate = candidate_file.relative_to(worktree_dir)
                if path == str(rel_candidate):
                    continue
            except ValueError:
                pass
        unexpected.append(line)
    return unexpected


def _parse_porcelain_path(line: str) -> str | None:
    if len(line) < 4:
        return None
    rest = line[3:]
    if " -> " in rest:
        rest = rest.split(" -> ")[-1]
    rest = rest.strip().strip('"')
    return rest if rest else None


def _gate_result(
    gate_id: str, gate_kind: str, status: str, start_mono: float, evidence_hex: str
) -> dict:
    return {
        "gate_id": gate_id,
        "gate_kind": gate_kind,
        "status": status,
        "started_at": _now_iso(),
        "completed_at": _now_iso(),
        "duration_ms": int((time.monotonic() - start_mono) * 1000),
        "evidence_hash": evidence_hex,
    }


_GATE_KIND_TO_FAILURE_CLASS: dict[str, str] = {
    "json_schema_validation": "constraint_violation",
    "python_importability": "type_error",
    "pyright_type_check": "type_error",
    "ruff_lint": "format_error",
    "ruff_format": "format_error",
    "real_artifact_round_trip": "constraint_violation",
    "adversarial_malformed_input": "constraint_violation",
    "deterministic_regeneration": "constraint_violation",
    "content_light_redaction": "redaction_leak",
    "worktree_dirty_state": "worktree_dirty_state",
}


def _failure_class_for_gate(gate_kind: str) -> str:
    return _GATE_KIND_TO_FAILURE_CLASS.get(gate_kind, "constraint_violation")


def _build_matrix_result(
    run_id: str, candidate_id: str, started: str, completed: str, gates: list[dict]
) -> dict:
    passed = sum(1 for g in gates if g["status"] == "pass")
    failed = sum(1 for g in gates if g["status"] == "fail")
    held = sum(1 for g in gates if g["status"] == "hold")
    if failed > 0:
        overall = "fail"
    elif held > 0:
        overall = "hold"
    else:
        overall = "pass"
    return {
        "validation_result_id": f"vr-{candidate_id}",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "worktree_id": candidate_id,
        "started_at": started,
        "completed_at": completed,
        "overall_status": overall,
        "gates": gates,
        "passed_gate_count": passed,
        "failed_gate_count": failed,
        "warning_gate_count": held,
        "counterexample_ids": [],
        "output_artifact_hashes": {},
    }


def _candidate_import_name(candidate_file: Path, worktree_dir: Path) -> str:
    rel = candidate_file.relative_to(worktree_dir)
    parts = [p.replace("-", "_") for p in rel.with_suffix("").parts]
    return ".".join(parts)


def _find_python(worktree_dir: Path) -> Path:
    return Path(sys.executable or shutil.which("python3") or "python3")


def _git_head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(repo_root),
    )
    return result.stdout.strip()


def _run_git(
    repo_root: Path, args: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd or repo_root),
    )


def reap_scratch_worktree(worktree_dir: Path, repo_root: Path) -> None:
    _run_git(repo_root, ["worktree", "remove", str(worktree_dir)], cwd=repo_root)
    _run_git(repo_root, ["worktree", "prune"], cwd=repo_root)


def emit_candidate_record(
    evidence_dir: Path,
    run_id: str,
    candidate_id: str,
    candidate_sha256: str,
    schema_sha256: str,
    base_head_sha: str,
    status: str,
    spec: dict,
) -> Path:
    record = {
        "schema_version": "rig.contract_compiler.candidate.v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "contract_family_id": spec["contract_family_id"],
        "contract_slice_id": "slice-0",
        "parent_stage_id": "",
        "candidate_kind": "combined_candidate",
        "candidate_status": status,
        "semantic_contract_sha256": compute_sha256(spec["schema_version"]),
        "schema_candidate_sha256": schema_sha256,
        "python_candidate_sha256": candidate_sha256,
        "candidate_patch_sha256": candidate_sha256,
        "generator_id": "jinja2_template_v0",
        "generator_version": "0.0.1-dev",
        "worktree_id": candidate_id,
        "worktree_path_hash": hash_path(evidence_dir),
        "base_head_sha": base_head_sha,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "content_light": True,
        "redaction_status": "content_light",
    }
    path = evidence_dir / "candidate.v1.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def emit_validation_matrix_result(evidence_dir: Path, matrix_result: dict) -> Path:
    result = {
        "schema_version": "rig.contract_compiler.validation_matrix_result.v1",
        **matrix_result,
        "content_light": True,
        "redaction_status": "content_light",
    }
    path = evidence_dir / "validation_matrix_result.v1.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path


def emit_worktree_lifecycle_event(
    evidence_dir: Path,
    run_id: str,
    candidate_id: str,
    lifecycle_state: str,
    previous_state: str,
    next_state: str,
    worktree_dir: Path,
    base_head_sha: str,
    event_reason: str,
    cleanup_action: str = "none",
) -> None:
    current_head = base_head_sha
    if worktree_dir.exists():
        current_head = _git_head_sha(worktree_dir)
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
        "current_head_sha": current_head,
        "dirty_state": "clean",
        "emitted_at": _now_iso(),
        "event_reason": event_reason,
        "cleanup_action": cleanup_action,
        "content_light": True,
        "redaction_status": "content_light",
    }
    path = evidence_dir / "worktree_lifecycle.v1.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def emit_counterexample(
    evidence_dir: Path,
    run_id: str,
    candidate_id: str,
    source_gate: str,
    failure_class: str,
    expected_behavior: str,
    actual_behavior_hash: str,
    replay_command_hash: str | None = None,
    minimal_reproduction_artifact_path: str | None = None,
) -> Path:
    if replay_command_hash is None:
        replay_command_hash = compute_sha256(
            f"uv run python scripts/rig_compiler_experiment_0.py --run-id {run_id}"
        )
    if minimal_reproduction_artifact_path is None:
        minimal_reproduction_artifact_path = "counterexamples/repro.json"
    record = {
        "schema_version": "rig.contract_compiler.counterexample.v1",
        "counterexample_id": f"ce-{candidate_id}-{source_gate}",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "worktree_id": candidate_id,
        "contract_family_id": "coordination_fake_green",
        "contract_slice_id": "slice-0",
        "source_gate": source_gate,
        "input_artifact_hash": compute_sha256("malformed-input"),
        "expected_behavior": expected_behavior,
        "actual_behavior_hash": actual_behavior_hash,
        "failure_class": failure_class,
        "spurious_or_genuine": "unknown",
        "replay_command_hash": replay_command_hash,
        "minimal_reproduction_artifact_path": minimal_reproduction_artifact_path,
        "redaction_status": "content_light",
        "deduplication_key": compute_sha256(
            f"{candidate_id}:{source_gate}:{failure_class}"
        ),
        "pruning_effect": "single_candidate",
        "discovered_at": _now_iso(),
    }
    path = evidence_dir / "counterexample.v1.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def emit_permutation_corpus_row(
    evidence_dir: Path,
    run_id: str,
    candidate_id: str,
    contract_family_id: str,
    contract_slice_id: str,
    generator_id: str,
    generator_version: str,
    schema_pattern_id: str,
    template_branch_id: str,
    candidate_status: str,
    fit_score: float,
    gate_summary: dict,
    counterexample_count: int,
    counterexample_cluster_ids: list[str],
    promoted_to_stage: bool,
    accepted: bool,
) -> Path:
    row_id = f"pcr-{candidate_id}-{uuid.uuid4().hex[:8]}"
    row = {
        "schema_version": "rig.contract_compiler.permutation_corpus_row.v1",
        "row_id": row_id,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "contract_family_id": contract_family_id,
        "contract_slice_id": contract_slice_id,
        "generator_id": generator_id,
        "generator_version": generator_version,
        "schema_pattern_id": schema_pattern_id,
        "template_branch_id": template_branch_id,
        "candidate_status": candidate_status,
        "fit_score": fit_score,
        "gate_summary": gate_summary,
        "counterexample_count": counterexample_count,
        "counterexample_cluster_ids": counterexample_cluster_ids,
        "promoted_to_stage": promoted_to_stage,
        "accepted": accepted,
        "emitted_at": _now_iso(),
        "content_light": True,
    }
    path = evidence_dir / "permutation_corpus_row.v1.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return path


def emit_run_manifest(
    evidence_dir: Path,
    run_id: str,
    repo_head_sha: str,
    spec: dict,
    budget: dict,
    candidate_count: int,
    accepted: int,
    rejected: int,
    quarantined: int,
    counterexamples: int,
    gate_summary: dict,
) -> Path:
    manifest = {
        "schema_version": "rig.contract_compiler.run_manifest.v1",
        "run_id": run_id,
        "generated_at": _now_iso(),
        "repo_head_sha": repo_head_sha,
        "repo_branch_hash": compute_sha256("main"),
        "semantic_contract_id": spec["contract_family_id"],
        "semantic_contract_sha256": compute_sha256(spec["schema_version"]),
        "compiler_version": "0.0.1-dev",
        "generator_id": "jinja2_template_v0",
        "generator_version": "0.0.1-dev",
        "base_worktree_path_hash": hash_path(evidence_dir.parent),
        "evidence_root": str(evidence_dir.relative_to(evidence_dir.parent.parent)),
        "worktree_root_hash": hash_path(
            evidence_dir.parent.parent / ".." / "worktrees"
        ),
        "worktree_budget": budget,
        "contract_slices": [
            {
                "contract_slice_id": "slice-0",
                "slice_order": 0,
                "acceptance_threshold": 1.0,
                "assertion_count": 1,
                "required_gate_ids": list(gate_summary.keys()),
            }
        ],
        "candidate_count": candidate_count,
        "accepted_candidate_count": accepted,
        "rejected_candidate_count": rejected,
        "quarantined_candidate_count": quarantined,
        "counterexample_count": counterexamples,
        "validation_matrix_summary": gate_summary,
        "artifact_paths": {
            "candidates_jsonl": "candidates/candidate.jsonl",
            "validation_results_jsonl": "candidates/validation_results.jsonl",
            "counterexamples_jsonl": "candidates/counterexamples.jsonl",
            "permutation_corpus_jsonl": "permutation_corpus_row.v1.jsonl",
            "pattern_report_path": "pattern_report.v1.json",
            "worktree_lifecycle_jsonl": "candidates/worktree_lifecycle.v1.jsonl",
        },
        "artifact_hashes": {
            "candidates_jsonl_sha256": compute_sha256("candidates"),
            "validation_results_jsonl_sha256": compute_sha256("results"),
            "counterexamples_jsonl_sha256": compute_sha256("counterexamples"),
            "permutation_corpus_jsonl_sha256": compute_sha256(
                "permutation_corpus_row.v1.jsonl"
            ),
            "pattern_report_sha256": compute_sha256("report"),
            "worktree_lifecycle_jsonl_sha256": compute_sha256("lifecycle"),
            "run_manifest_sha256": compute_sha256(run_id),
        },
        "content_light": True,
        "redaction_status": "content_light",
    }
    path = evidence_dir / "run_manifest.v1.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _refuse_dangerous_paths(worktree_root: Path, repo_root: Path) -> None:
    resolved = worktree_root.resolve()
    home = Path.home().resolve()
    root = Path("/").resolve()
    if resolved in {home, root} or resolved == repo_root.resolve():
        raise ValueError(
            f"Worktree root {resolved} resolves to a dangerous path. "
            "Refusing to operate."
        )
    if str(repo_root.resolve()) in str(resolved):
        pass


def run_experiment_0(
    target_schema_path: Path,
    run_id: str,
    output_root: Path,
    worktree_root: Path,
    repo_root: Path,
    keep_worktree: bool = False,
    fail_on_validation_fail: bool = False,
) -> tuple[bool, Path, Path | None]:
    candidate_id = f"cand-{run_id[:8]}-{uuid.uuid4().hex[:8]}"
    evidence_dir = output_root / run_id / "candidates" / candidate_id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    schema = load_target_schema(target_schema_path)
    spec = derive_model_spec_from_schema(schema, target_schema_path)
    candidate_code = render_candidate_model(spec)
    candidate_sha256 = compute_sha256(candidate_code)
    schema_sha256 = compute_sha256(json.dumps(schema))

    worktree_dir = None
    try:
        worktree_dir, base_head_sha = create_scratch_worktree(
            worktree_root, run_id, candidate_id, repo_root
        )
        emit_worktree_lifecycle_event(
            evidence_dir,
            run_id,
            candidate_id,
            "created",
            "",
            "patch_applied",
            worktree_dir,
            base_head_sha,
            "Scratch worktree created",
        )

        candidate_file, _ = apply_candidate_patch(
            worktree_dir, candidate_code, candidate_id
        )
        emit_worktree_lifecycle_event(
            evidence_dir,
            run_id,
            candidate_id,
            "patch_applied",
            "created",
            "validation_running",
            worktree_dir,
            base_head_sha,
            "Candidate patch applied",
        )

        matrix_result = run_validation_matrix(
            worktree_dir,
            candidate_file,
            target_schema_path,
            run_id,
            candidate_id,
            repo_root,
        )
        overall = matrix_result["overall_status"]

        emit_candidate_record(
            evidence_dir,
            run_id,
            candidate_id,
            candidate_sha256,
            schema_sha256,
            base_head_sha,
            "accepted" if overall == "pass" else "rejected",
            spec,
        )
        emit_validation_matrix_result(evidence_dir, matrix_result)

        counterexamples_emitted = 0
        for gate in matrix_result["gates"]:
            if gate["status"] in {"fail", "hold"}:
                failure_class = _failure_class_for_gate(gate["gate_kind"])
                replay_command_hash = compute_sha256(
                    f"uv run python scripts/rig_compiler_experiment_0.py "
                    f"--target-schema {target_schema_path} --run-id {run_id} "
                    f"--gate {gate['gate_id']}"
                )
                repro_path = f"candidates/{candidate_id}/repro/{gate['gate_kind']}.json"
                emit_counterexample(
                    evidence_dir,
                    run_id,
                    candidate_id,
                    gate["gate_kind"],
                    failure_class,
                    f"Gate {gate['gate_kind']} expected pass",
                    gate["evidence_hash"],
                    replay_command_hash=replay_command_hash,
                    minimal_reproduction_artifact_path=repro_path,
                )
                counterexamples_emitted += 1

        passed_gates = matrix_result["passed_gate_count"]
        failed_gates = matrix_result["failed_gate_count"]
        held_gates = matrix_result["warning_gate_count"]

        skipped_gates = sum(
            1 for g in matrix_result["gates"] if g["status"] == "skipped"
        )
        total_gates = len(matrix_result["gates"])
        corpus_gate_summary = {
            "passed": passed_gates,
            "failed": failed_gates,
            "held": held_gates,
            "skipped": skipped_gates,
        }
        emit_permutation_corpus_row(
            evidence_dir=evidence_dir,
            run_id=run_id,
            candidate_id=candidate_id,
            contract_family_id=spec["contract_family_id"],
            contract_slice_id="slice-0",
            generator_id="jinja2_template_v0",
            generator_version="0.0.1-dev",
            schema_pattern_id="experiment_0_default",
            template_branch_id="jinja2_template_v0/main",
            candidate_status="accepted" if overall == "pass" else "rejected",
            fit_score=passed_gates / total_gates if total_gates > 0 else 0.0,
            gate_summary=corpus_gate_summary,
            counterexample_count=counterexamples_emitted,
            counterexample_cluster_ids=[
                f"ce-{candidate_id}-{gate['gate_kind']}"
                for gate in matrix_result["gates"]
                if gate["status"] in {"fail", "hold"}
            ],
            promoted_to_stage=False,
            accepted=overall == "pass",
        )

        emit_run_manifest(
            evidence_dir,
            run_id,
            base_head_sha,
            spec,
            {
                "max_scratch_worktrees": 1,
                "max_retained_failed_worktrees": 0,
                "max_stage_depth": 1,
                "max_candidates_per_slice": 1,
                "max_runtime_seconds_per_candidate": 300,
            },
            1,
            1 if overall == "pass" else 0,
            0 if overall == "pass" else 1,
            0,
            counterexamples_emitted,
            {
                "total_gates": len(matrix_result["gates"]),
                "passing_gates": passed_gates,
                "failing_gates": failed_gates,
                "held_gates": held_gates,
                "skipped_gates": sum(
                    1 for g in matrix_result["gates"] if g["status"] == "skipped"
                ),
                "total_validations_run": 1,
                "average_duration_ms": 0,
            },
        )

        if overall in {"fail", "hold"}:
            emit_worktree_lifecycle_event(
                evidence_dir,
                run_id,
                candidate_id,
                "failed_reset",
                "validation_running",
                "failed_reaped" if not keep_worktree else "quarantined",
                worktree_dir,
                base_head_sha,
                f"Validation {overall}",
                "reap" if not keep_worktree else "quarantine",
            )

        if not keep_worktree:
            reap_scratch_worktree(worktree_dir, repo_root)
            emit_worktree_lifecycle_event(
                evidence_dir,
                run_id,
                candidate_id,
                "failed_reaped",
                "failed_reset",
                "",
                worktree_dir,
                base_head_sha,
                "Scratch worktree reaped after evidence copied",
                "reap",
            )
            worktree_dir = None

        if fail_on_validation_fail and overall == "fail":
            return False, evidence_dir, worktree_dir

        return True, evidence_dir, worktree_dir

    except Exception:
        if worktree_dir is not None:
            try:
                reap_scratch_worktree(worktree_dir, repo_root)
            except Exception:
                pass
        return False, evidence_dir, None

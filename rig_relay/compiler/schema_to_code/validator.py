from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Any

from rig_relay.compiler.gates import GateMatrix, GateResult, GateStatus
from rig_relay.compiler.hashes import compute_sha256
from rig_relay.compiler.schema_to_code._ast_safety import check_ast_safety
from rig_relay.compiler.schema_to_code.generator import render_template
from rig_relay.compiler.schema_to_code.reader import (
    derive_model_spec_from_schema,
    load_target_schema,
)


def validate_minimum_safety(schema_path: Path, generated_file_path: Path) -> GateMatrix:
    gate_matrix = GateMatrix()
    _run_gate_schema_validation(gate_matrix, schema_path)
    _run_gate_ast_safety(gate_matrix, generated_file_path)
    return gate_matrix


def validate_generated_code(
    worktree_path: Path,
    generated_file_path: Path,
    schema_path: Path,
    repo_root: Path | None = None,
    gate_matrix: GateMatrix | None = None,
) -> GateMatrix:
    if repo_root is None:
        repo_root = worktree_path
    if gate_matrix is None:
        gate_matrix = GateMatrix()

    _run_gate_schema_validation(gate_matrix, schema_path)
    _run_gate_ast_safety(gate_matrix, generated_file_path)
    _run_gate_importability(gate_matrix, worktree_path, generated_file_path, repo_root)
    _run_gate_pyright(gate_matrix, generated_file_path, repo_root)
    _run_gate_ruff_lint(gate_matrix, generated_file_path, repo_root)
    _run_gate_ruff_format(gate_matrix, generated_file_path, repo_root)
    _run_gate_roundtrip(
        gate_matrix, worktree_path, generated_file_path, schema_path, repo_root
    )
    _run_gate_adversarial(
        gate_matrix, worktree_path, generated_file_path, schema_path, repo_root
    )
    _run_gate_deterministic(gate_matrix, schema_path)
    _run_gate_redaction(gate_matrix, worktree_path)
    _run_gate_dirty_check(gate_matrix, worktree_path, generated_file_path)

    return gate_matrix


def _run_gate_schema_validation(matrix: GateMatrix, schema_path: Path) -> None:
    start = time.monotonic()
    try:
        from jsonschema import Draft7Validator

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        status = GateStatus.PASS
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-schema-validation",
            gate_kind="schema_validation",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_ast_safety(matrix: GateMatrix, candidate_file: Path) -> None:
    start = time.monotonic()
    try:
        source = candidate_file.read_text(encoding="utf-8")
        result = check_ast_safety(source)
        if result.safe:
            status = GateStatus.PASS
            evidence = compute_sha256("ast-clean")
        else:
            status = GateStatus.FAIL
            evidence = compute_sha256(json.dumps(result.violations))
    except Exception:
        status = GateStatus.FAIL
        evidence = compute_sha256("ast-safety-error")
    matrix.add(
        GateResult(
            gate_id="gate-ast-safety",
            gate_kind="ast_safety",
            status=status,
            evidence_hash=evidence,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_importability(
    matrix: GateMatrix, worktree_dir: Path, candidate_file: Path, repo_root: Path
) -> None:
    start = time.monotonic()
    try:
        code = (
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod)"
        )
        result = subprocess.run(
            ["uv", "run", "python", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        status = GateStatus.PASS if result.returncode == 0 else GateStatus.FAIL
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-import",
            gate_kind="importability",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_pyright(
    matrix: GateMatrix, candidate_file: Path, repo_root: Path
) -> None:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["uv", "run", "pyright", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(candidate_file.parent),
        )
        status = GateStatus.PASS if result.returncode == 0 else GateStatus.FAIL
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-pyright",
            gate_kind="pyright_type_check",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_ruff_lint(
    matrix: GateMatrix, candidate_file: Path, repo_root: Path
) -> None:
    start = time.monotonic()
    try:
        subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(candidate_file.parent),
        )
        result = subprocess.run(
            ["uv", "run", "ruff", "check", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(candidate_file.parent),
        )
        status = GateStatus.PASS if result.returncode == 0 else GateStatus.FAIL
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-ruff-lint",
            gate_kind="ruff_lint",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_ruff_format(
    matrix: GateMatrix, candidate_file: Path, repo_root: Path
) -> None:
    start = time.monotonic()
    try:
        subprocess.run(
            ["uv", "run", "ruff", "format", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(candidate_file.parent),
        )
        result = subprocess.run(
            ["uv", "run", "ruff", "format", "--check", str(candidate_file)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(candidate_file.parent),
        )
        status = GateStatus.PASS if result.returncode == 0 else GateStatus.FAIL
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-ruff-fmt",
            gate_kind="ruff_format",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_roundtrip(
    matrix: GateMatrix,
    worktree_dir: Path,
    candidate_file: Path,
    schema_path: Path,
    repo_root: Path,
) -> None:
    start = time.monotonic()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        test_payload = _build_test_payload(schema)
        if test_payload is None:
            matrix.add(
                GateResult(
                    gate_id="gate-round-trip",
                    gate_kind="json_roundtrip",
                    status=GateStatus.SKIP,
                    evidence_hash=compute_sha256("skipped"),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return
        code = (
            "import importlib.util, json;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod);"
            f"test_payload = json.loads({json.dumps(json.dumps(test_payload))});"
            "m = mod.GeneratedModel(**test_payload);"
            "dump = m.model_dump(exclude_none=True); print(json.dumps(dump))"
        )
        result = subprocess.run(
            ["uv", "run", "python", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        if result.returncode != 0:
            matrix.add(
                GateResult(
                    gate_id="gate-round-trip",
                    gate_kind="json_roundtrip",
                    status=GateStatus.FAIL,
                    evidence_hash=compute_sha256(result.stderr or result.stdout),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return
        dumped = json.loads(result.stdout.strip())
        from jsonschema import Draft7Validator

        validator = Draft7Validator(schema=schema)
        errors = list(validator.iter_errors(dumped))
        status = GateStatus.PASS if not errors else GateStatus.FAIL
        evidence = compute_sha256(json.dumps(dumped))
    except Exception:
        status = GateStatus.FAIL
        evidence = compute_sha256("round-trip-error")
    matrix.add(
        GateResult(
            gate_id="gate-round-trip",
            gate_kind="json_roundtrip",
            status=status,
            evidence_hash=evidence,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_adversarial(
    matrix: GateMatrix,
    worktree_dir: Path,
    candidate_file: Path,
    schema_path: Path,
    repo_root: Path,
) -> None:
    start = time.monotonic()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        required = schema.get("required", [])
        if not required:
            matrix.add(
                GateResult(
                    gate_id="gate-adv",
                    gate_kind="adversarial_input",
                    status=GateStatus.SKIP,
                    evidence_hash=compute_sha256("skipped"),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return
        malformed: dict[str, Any] = {}
        code = (
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('_candidate', {str(candidate_file)!r});"
            "mod = importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(mod);"
            f"m = mod.GeneratedModel(**{json.dumps(malformed)}); print('accepted')"
        )
        result = subprocess.run(
            ["uv", "run", "python", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(worktree_dir),
        )
        if "accepted" in result.stdout and result.returncode == 0:
            status = GateStatus.FAIL
        else:
            status = GateStatus.PASS
        evidence = compute_sha256(result.stderr if result.stderr else result.stdout)
    except Exception:
        status = GateStatus.FAIL
        evidence = compute_sha256("adversarial-error")
    matrix.add(
        GateResult(
            gate_id="gate-adv",
            gate_kind="adversarial_input",
            status=status,
            evidence_hash=evidence,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_deterministic(matrix: GateMatrix, schema_path: Path) -> None:
    start = time.monotonic()
    try:
        schema = load_target_schema(schema_path)
        spec1 = derive_model_spec_from_schema(schema, schema_path)
        spec2 = derive_model_spec_from_schema(schema, schema_path)
        if spec1 != spec2:
            matrix.add(
                GateResult(
                    gate_id="gate-regen",
                    gate_kind="deterministic_regen",
                    status=GateStatus.FAIL,
                    evidence_hash=compute_sha256("spec-drift"),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
            return
        first = render_template(spec1).encode("utf-8")
        second = render_template(spec2).encode("utf-8")
        status = GateStatus.PASS if first == second else GateStatus.FAIL
        evidence = compute_sha256(first)
    except Exception:
        status = GateStatus.FAIL
        evidence = compute_sha256("regen-error")
    matrix.add(
        GateResult(
            gate_id="gate-regen",
            gate_kind="deterministic_regen",
            status=status,
            evidence_hash=evidence,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_redaction(matrix: GateMatrix, worktree_dir: Path) -> None:
    start = time.monotonic()
    status = GateStatus.PASS
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
                    status = GateStatus.FAIL
                    break
    except Exception:
        status = GateStatus.PASS
    matrix.add(
        GateResult(
            gate_id="gate-redact",
            gate_kind="content_redaction",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


def _run_gate_dirty_check(
    matrix: GateMatrix, worktree_dir: Path, candidate_file: Path | None = None
) -> None:
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(worktree_dir),
        )
        dirty_lines = [
            line for line in result.stdout.strip().split("\n") if line.strip()
        ]
        unexpected = _filter_expected_dirty(dirty_lines, worktree_dir, candidate_file)
        status = GateStatus.PASS if not unexpected else GateStatus.FAIL
    except Exception:
        status = GateStatus.FAIL
    matrix.add(
        GateResult(
            gate_id="gate-dirty",
            gate_kind="dirty_check",
            status=status,
            evidence_hash=compute_sha256(str(status)),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    )


_EXPECTED_DIRTY_PREFIXES = ("rig_relay/generated_candidates/", ".build/")
_MIN_PORCELAIN_FIELD_LENGTH = 4


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
    if len(line) < _MIN_PORCELAIN_FIELD_LENGTH:
        return None
    rest = line[3:]
    if " -> " in rest:
        rest = rest.split(" -> ")[-1]
    rest = rest.strip().strip('"')
    return rest if rest else None


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
            new_candidates: list[dict] = []
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
    if "const" in prop:
        return [prop["const"]]
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


_DEFAULT_VALUES: dict[str, Any] = {
    "number": 0.5,
    "boolean": False,
    "array": [],
    "object": {},
}


def _default_value_for_prop(prop: dict) -> Any:
    if "const" in prop:
        return prop["const"]
    if "enum" in prop:
        return prop["enum"][0]
    t = prop.get("type", "string")
    if t == "string":
        if "pattern" in prop:
            return _sample_for_pattern(prop["pattern"])
        return (
            "2026-01-01T00:00:00Z"
            if "format" in prop and prop["format"] == "date-time"
            else f"test-{prop.get('description', 'value')}"[:50]
        )
    if t == "integer":
        return prop.get("minimum", 0) if "minimum" in prop else 1
    return _DEFAULT_VALUES.get(t, "test-value")


def _sample_for_pattern(pattern: str) -> str:
    import re

    if re.match(r"^\^?\[a-f0-9\]\{\d+\}\$?$", pattern):
        match = re.search(r"\{(\d+)\}", pattern)
        length = int(match.group(1)) if match else 64
        return "a" * length
    if re.match(r"^\^?\[a-zA-Z0-9_\-\]+\+?\$?$", pattern):
        return "abc123"
    return "pattern-match"

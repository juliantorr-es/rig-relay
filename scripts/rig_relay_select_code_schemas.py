#!/usr/bin/env python3
"""Deterministic code schema router for the Rig Relay context assembler.

Loads the code schema registry, validates authority, matches incoming
requests against active schemas using deterministic signal scoring, and
returns a CodeSchemaSelection with ranked schemas, context packs,
invariants, and validation commands.

Usage:
  uv run python scripts/rig_relay_select_code_schemas.py \\
    --prompt "fix frontend trace endpoint" \\
    --changed-file frontend/desktop/js/utils.js \\
    --test test_frontend_trace_endpoint.py \\
    --traceback-file /tmp/tb.txt

Output:
  JSON CodeSchemaSelection to stdout.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "json" / "code_schemas" / "index.v1.json"

_EXCLUDE_CONTEXT_GLOBS = [
    "docs/pages/**",
    "docs/collections/**",
    "docs/assets/**",
    "docs/search-index.json",
    "docs/render-manifest.json",
    "**/*.html",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _match_pattern(text: str, pattern: str) -> bool:
    return pattern.lower() in text.lower()


def _match_pattern_list(text: str, patterns: list[str]) -> bool:
    return any(_match_pattern(text, p) for p in patterns)


def _glob_match(path: str, glob: str) -> bool:
    if glob.endswith("/**"):
        prefix = glob[:-3]
        return path.startswith(prefix) or path.startswith(prefix.rstrip("/") + "/")
    if glob.startswith("**/"):
        suffix = glob[3:]
        return path == suffix or path.endswith("/" + suffix)
    return path == glob or path.startswith(glob)


def _is_excluded_context(path: str) -> bool:
    return any(_glob_match(path, g) for g in _EXCLUDE_CONTEXT_GLOBS)


def _validate_authority(
    schema: dict[str, Any], schema_path: Path
) -> tuple[bool, str | None]:
    authority = schema.get("authority", {})
    if not authority.get("trusted"):
        return False, "authority not trusted"
    source_path_str = authority.get("source_path")
    if not source_path_str:
        return False, "missing source_path"
    source_file = REPO_ROOT / source_path_str
    if not source_file.is_file():
        return False, f"source_path file not found: {source_path_str}"
    expected_hash = authority.get("source_hash", "")
    actual_bytes = source_file.read_bytes()
    actual_hash = f"sha256:{sha256(actual_bytes).hexdigest()}"
    if actual_hash != expected_hash:
        return (
            False,
            f"source_hash mismatch: expected {expected_hash}, got {actual_hash}",
        )
    return True, None


def _load_registry(registry_path: Path | None = None) -> list[dict[str, Any]]:
    path = registry_path or REGISTRY_PATH
    if not path.is_file():
        print(json.dumps({"error": "registry not found", "path": str(path)}))
        sys.exit(1)
    return _load_json(path).get("entries", [])


def _load_active_schema(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("status") != "active":
        return None
    if not entry.get("authority_trusted"):
        return None
    schema_path = REPO_ROOT / entry["path"]
    if not schema_path.is_file():
        return None
    try:
        schema = _load_json(schema_path)
    except (json.JSONDecodeError, OSError):
        return None
    if schema.get("status") != "active":
        return None
    return schema


def _score_schema(
    schema: dict[str, Any],
    schema_path: Path,
    prompt: str,
    changed_files: list[str],
    failing_tests: list[str],
    traceback_text: str,
) -> tuple[int, list[str]]:
    score = 0
    signals: list[str] = []

    intent_patterns: list[str] = schema.get("intent_patterns", [])
    applies_when: dict[str, list[str]] = schema.get("applies_when", {})

    if prompt and intent_patterns and _match_pattern_list(prompt, intent_patterns):
        score += 3
        signals.append("intent_patterns")

    if prompt:
        user_patterns: list[str] = applies_when.get("user_prompt_patterns", [])
        if user_patterns and _match_pattern_list(prompt, user_patterns):
            score += 2
            signals.append("user_prompt_patterns")

    for cf in changed_files:
        file_patterns: list[str] = applies_when.get("file_patterns", [])
        for fp in file_patterns:
            if cf.endswith(fp) or fp.endswith(cf) or cf == fp or cf.endswith("/" + fp):
                score += 2
                signals.append(f"file_pattern:{cf}")
                break

    for ft in failing_tests:
        test_patterns: list[str] = applies_when.get("test_patterns", [])
        for tp in test_patterns:
            if ft.endswith(tp) or tp.endswith(ft) or ft == tp:
                score += 2
                signals.append(f"test_pattern:{ft}")
                break

    if traceback_text:
        tb_patterns: list[str] = applies_when.get("traceback_patterns", [])
        if tb_patterns and _match_pattern_list(traceback_text, tb_patterns):
            score += 2
            signals.append("traceback_patterns")

    schema_id = schema.get("schema_id", "")
    if prompt and schema_id.lower() in prompt.lower():
        score += 10
        signals.append("explicit_schema_id")

    return score, signals


def select_schemas(
    prompt: str = "",
    changed_files: list[str] | None = None,
    failing_tests: list[str] | None = None,
    traceback_text: str = "",
    registry_path: Path | None = None,
) -> dict[str, Any]:
    changed_files = changed_files or []
    failing_tests = failing_tests or []

    entries = _load_registry(registry_path)
    warnings: list[str] = []
    results: list[dict[str, Any]] = []

    for entry in entries:
        schema = _load_active_schema(entry)
        if schema is None:
            continue

        result = _evaluate_entry(
            entry,
            schema,
            prompt,
            changed_files,
            failing_tests,
            traceback_text,
            warnings,
        )
        if result is not None:
            results.append(result)

    results.sort(key=lambda r: (-r["score"], r["schema_id"]))

    selected = [r for r in results if r["score"] > 0]
    reported = [r for r in results if r["score"] == 0]

    return {
        "selected_schemas": selected,
        "reported_schemas": [
            {"schema_id": r["schema_id"], "title": r["title"], "score": r["score"]}
            for r in reported
        ],
        "total_active": len(entries),
        "total_loaded": len(results),
        "total_selected": len(selected),
        "warnings": warnings,
        "selection_input": {
            "prompt_length": len(prompt),
            "changed_files_count": len(changed_files),
            "failing_tests_count": len(failing_tests),
            "traceback_text_length": len(traceback_text),
        },
    }


def _evaluate_entry(
    entry: dict[str, Any],
    schema: dict[str, Any],
    prompt: str,
    changed_files: list[str],
    failing_tests: list[str],
    traceback_text: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    schema_id = entry.get("schema_id", "unknown")
    source_path = entry["path"]
    schema_path = REPO_ROOT / source_path

    is_authoritative, auth_err = _validate_authority(schema, schema_path)
    score, signals = _score_schema(
        schema, schema_path, prompt, changed_files, failing_tests, traceback_text
    )

    if not is_authoritative:
        warnings.append(f"{schema_id}: authority check failed — {auth_err}")
        if score > 0:
            warnings.append(
                f"{schema_id}: matched with score={score} but authority check failed; not selected as authoritative"
            )
        return None

    context_pack = schema.get("context_pack", {})
    return {
        "schema_id": schema_id,
        "title": schema.get("title", ""),
        "change_kind": schema.get("change_kind", ""),
        "score": score,
        "matched_signals": signals,
        "model_facing_summary": schema.get("model_facing_summary", ""),
        "required_invariants": schema.get("required_invariants", []),
        "validation_commands": schema.get("validation_commands", []),
        "forbidden_patterns": schema.get("forbidden_patterns", []),
        "context_pack": _filter_context(context_pack),
        "authority": {
            "trusted": schema.get("authority", {}).get("trusted", False),
            "source_path": schema.get("authority", {}).get("source_path", ""),
            "source_hash": schema.get("authority", {}).get("source_hash", ""),
        },
    }


def _filter_context(context_pack: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {
        "include_files": [],
        "include_docs": [],
        "include_schemas": [],
        "exclude_patterns": list(context_pack.get("exclude_patterns", [])),
        "max_context_notes": context_pack.get("max_context_notes", 0),
    }
    for key in ("include_files", "include_docs", "include_schemas"):
        for item in context_pack.get(key, []):
            if not _is_excluded_context(item):
                filtered[key].append(item)
    return filtered


def _normalize_glob_for_prompt(glob: str) -> str:
    if glob.endswith("/**"):
        return f"paths under {glob[:-3]}/"
    if glob.startswith("**/"):
        return glob[3:]
    return glob


def _format_selection_output(selection: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Relevant Code Schemas:")
    lines.append("")
    for i, schema in enumerate(selection.get("selected_schemas", []), 1):
        lines.append(
            f"{i}. {schema['schema_id']} — {schema['title']} (score={schema['score']})"
        )
        lines.append(f"   Why: {', '.join(schema['matched_signals'])}")
        lines.append(f"   Summary: {schema['model_facing_summary']}")
        invariants = schema.get("required_invariants", [])
        if invariants:
            lines.append("   Required Invariants:")
            for inv in invariants:
                lines.append(f"     - {inv}")
        validation = schema.get("validation_commands", [])
        if validation:
            lines.append("   Validation Commands:")
            for vc in validation:
                lines.append(f"     $ {vc}")
        lines.append("")
    reported = selection.get("reported_schemas", [])
    if reported:
        lines.append("Also Active (no match):")
        for r in reported:
            lines.append(f"  - {r['schema_id']}: {r['title']}")
        lines.append("")
    warnings = selection.get("warnings", [])
    if warnings:
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  ! {w}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select relevant code schemas for a task/request."
    )
    parser.add_argument(
        "--prompt", type=str, default="", help="User prompt or task description"
    )
    parser.add_argument(
        "--changed-file",
        type=str,
        action="append",
        default=[],
        dest="changed_files",
        help="Changed file path (repeatable)",
    )
    parser.add_argument(
        "--test",
        type=str,
        action="append",
        default=[],
        dest="failing_tests",
        help="Failing test name or path (repeatable)",
    )
    parser.add_argument(
        "--traceback-file",
        type=str,
        default="",
        help="Path to a file containing traceback text",
    )
    parser.add_argument(
        "--registry-path",
        type=str,
        default="",
        help="Path to code schema registry JSON (default: docs/json/code_schemas/index.v1.json)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args()

    traceback_text = ""
    if args.traceback_file:
        traceback_path = Path(args.traceback_file)
        if traceback_path.is_file():
            traceback_text = traceback_path.read_text(encoding="utf-8")

    selection = select_schemas(
        prompt=args.prompt,
        changed_files=args.changed_files,
        failing_tests=args.failing_tests,
        traceback_text=traceback_text,
        registry_path=Path(args.registry_path) if args.registry_path else None,
    )

    if args.format == "text":
        print(_format_selection_output(selection))
    else:
        print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rig Relay Semantic Change Snippet Exporter.

Reads write_file/search_replace/checkpoint artifacts and coordination events,
then produces anonymized content-light semantic change snippets.

Usage:
    uv run python scripts/rig_relay_export_semantic_change_snippets.py
    uv run python scripts/rig_relay_export_semantic_change_snippets.py --strict
    uv run python scripts/rig_relay_export_semantic_change_snippets.py --test-input 'def foo(): pass'

Content-light: never exports raw source code, identifiers, literals, comments,
secrets, file paths, prompts, model outputs, diffs, or stdout/stderr bodies.
"""

from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.semantic_change_snippet.v1.schema.json"
DEFAULT_OUTPUT = BUILD_ROOT / "derived" / "semantic_change_snippets.jsonl"
MANIFEST_PATH = BUILD_ROOT / "derived" / "semantic_change_snippets_manifest.json"

MAX_SNIPPET_LINES = 20

# ── Forbidden content patterns ───────────────────────────────────────────

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "api_token",
        re.compile(
            r"(?i)(api[_-]?key|api[_-]?token|secret[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]"
        ),
    ),
    (
        "private_key_marker",
        re.compile(r"(?i)(-----BEGIN\s+(RSA|EC|OPENSSH|PRIVATE)\s+KEY-----)"),
    ),
    ("raw_diff_header", re.compile(r"^diff --git a/", re.MULTILINE)),
    (
        "raw_prompt_marker",
        re.compile(r"(?i)(<\|im_start\|>|<\|user\|>|<\|assistant\|>)"),
    ),
    ("file_content_marker", re.compile(r"^# File: .+$", re.MULTILINE)),
    ("stdout_stderr_block", re.compile(r"```\s*(stdout|stderr)\s*\n")),
]

# ── Identifiers for stable placeholder mapping ────────────────────────────

_placeholder_counters: dict[str, int] = {}
_placeholder_map: dict[str, str] = {}


def _reset_placeholders() -> None:
    _placeholder_counters.clear()
    _placeholder_map.clear()


def _placeholder_for(prefix: str, original: str) -> str:
    """Return a stable placeholder like FN_001 for a given identifier."""
    if original not in _placeholder_map:
        _placeholder_counters.setdefault(prefix, 0)
        _placeholder_counters[prefix] += 1
        _placeholder_map[original] = f"{prefix}_{_placeholder_counters[prefix]:03d}"
    return _placeholder_map[original]


# ── Python anonymizer ────────────────────────────────────────────────────


def _anonymize_python_source(source: str) -> str:
    """Anonymize Python source: strip comments, replace identifiers and
    literals with stable placeholders, preserve control-flow shape.

    Uses stdlib ast for structure analysis plus line-level replacement.
    Tree-sitter deferred for multi-language support in a later version.
    """
    _reset_placeholders()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _basic_anonymize(source, "python")

    # Step 1: collect all identifier positions from AST
    replacements: list[tuple[int, int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            p = _placeholder_for("FN", node.name)
            replacements.append((
                node.lineno,
                node.col_offset,
                node.col_offset + len(node.name),
                p,
            ))
        elif isinstance(node, ast.AsyncFunctionDef):
            p = _placeholder_for("FN", node.name)
            replacements.append((
                node.lineno,
                node.col_offset,
                node.col_offset + len(node.name),
                p,
            ))
        elif isinstance(node, ast.ClassDef):
            p = _placeholder_for("CLASS", node.name)
            replacements.append((
                node.lineno,
                node.col_offset,
                node.col_offset + len(node.name),
                p,
            ))
        elif isinstance(node, ast.Name):
            p = _placeholder_for("VAR", node.id)
            replacements.append((
                node.lineno,
                node.col_offset,
                node.col_offset + len(node.id),
                p,
            ))
        elif isinstance(node, ast.Attribute):
            p = _placeholder_for("ATTR", node.attr)
            val_end = getattr(node.value, "end_col_offset", node.col_offset)
            attr_start = val_end + 1  # skip the dot
            replacements.append((
                node.lineno,
                attr_start,
                attr_start + len(node.attr),
                p,
            ))

    # Step 2: apply replacements in reverse order (right to left, bottom to top)
    lines = list(source.splitlines())
    replacements.sort(key=lambda r: (r[0], -r[1]))

    for lineno, col_start, col_end, placeholder in replacements:
        idx = lineno - 1
        if 0 <= idx < len(lines):
            line = lines[idx]
            if 0 <= col_start < col_end <= len(line):
                lines[idx] = line[:col_start] + placeholder + line[col_end:]

    # Step 3: strip comment-only lines
    lines = [l for l in lines if not l.lstrip().startswith("#")]

    # Step 4: strip string/number literals
    combined = "\n".join(lines)
    combined = _strip_literals([combined])[0]

    # Step 5: remove empty lines
    final_lines = [l for l in combined.split("\n") if l.strip()]
    return "\n".join(final_lines)


def _strip_literals(lines: list[str]) -> list[str]:
    """Replace string and numeric literals with placeholders."""
    result: list[str] = []
    for line in lines:
        line = re.sub(r'""".*?"""', "<STR>", line, flags=re.DOTALL)
        line = re.sub(r"'''.*?'''", "<STR>", line, flags=re.DOTALL)
        line = re.sub(r'"[^"]*"', "<STR>", line)
        line = re.sub(r"'[^']*'", "<STR>", line)
        line = re.sub(r"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", "<NUM>", line)
        line = re.sub(r"\bTrue\b", "<BOOL>", line)
        line = re.sub(r"\bFalse\b", "<BOOL>", line)
        line = re.sub(r"\bNone\b", "<NONE>", line)
        result.append(line)
    return result


def _basic_anonymize(text: str, language: str) -> str:
    """Fallback anonymizer for non-Python or unparseable code."""
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        if language in {"json", "yaml", "toml"}:
            result.append(line)
        elif language == "markdown":
            if line.startswith("#"):
                result.append(line)
        else:
            result.append(line)
    return "\n".join(result)


# ── Classification ────────────────────────────────────────────────────────


def _classify_change_kind(lines_before: list[str], lines_after: list[str]) -> str:
    """Classify change intent from anonymized shape."""
    added = "\n".join(lines_after)
    keywords: list[tuple[str, list[str]]] = [
        ("guard_added", ["if", "return"]),
        ("refusal_branch_added", ["return", "<ATTR_", "error"]),
        ("test_added", ["def test_", "assert"]),
        ("schema_added", ["schema_version"]),
        ("schema_validation_added", ["validate_schema", "check_forbidden"]),
        ("checkpoint_added", ["checkpoint"]),
        ("coordination_event_added", ["coordination"]),
        ("artifact_emission_added", ["payload_sha256"]),
        ("import_added", ["import "]),
        ("docs_updated", ["## "]),
    ]
    for kind, patterns in keywords:
        if all(p in added for p in patterns):
            return kind
    return "unknown"


def _classify_operation(lines_before: list[str], lines_after: list[str]) -> str:
    """Classify the structural operation."""
    bc = len(lines_before)
    ac = len(lines_after)
    if bc == 0 and ac > 0:
        return "insert"
    if bc > 0 and ac == 0:
        return "delete"
    if "def " in "\n".join(lines_after) and "def " not in "\n".join(lines_before):
        return "split"
    if lines_before != lines_after:
        return "replace"
    return "unknown"


def _classify_symbol_kind(text: str) -> str:
    """Classify the symbol kind from anonymized text."""
    if "def test_" in text:
        return "test"
    if "def " in text:
        return "function"
    if "class " in text:
        return "class"
    if "schema_version" in text or '"$schema"' in text:
        return "schema"
    if text.strip().startswith("#"):
        return "doc_section"
    return "unknown"


# ── Forbidden content scanning ────────────────────────────────────────────


def _detect_forbidden_content(text: str) -> list[str]:
    """Scan text for forbidden content patterns."""
    warnings: list[str] = []
    for label, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            warnings.append(f"Forbidden content detected: {label}")
    return warnings


# ── Hashing ────────────────────────────────────────────────────────────────


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_path(path: str) -> str:
    return "sha256:" + hashlib.sha256(path.encode("utf-8")).hexdigest()


def _compute_shape_hash(lines: list[str]) -> str:
    body = "\n".join(lines)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _guess_language(path_str: str) -> str:
    ext = Path(path_str).suffix.lower()
    mapping: dict[str, str] = {
        ".py": "python",
        ".json": "json",
        ".md": "markdown",
        ".rst": "markdown",
        ".sh": "shell",
        ".bash": "shell",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".cfg": "config",
        ".ini": "config",
    }
    return mapping.get(ext, "unknown")


# ── Snippet production ────────────────────────────────────────────────────


def _anonymize_snippet(
    source_text: str,
    language: str,
    path_str: str,
    source_event_id: str | None = None,
    source_artifact_sha256: str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Produce a single anonymized snippet row, or None if forbidden content in strict mode."""
    forbidden = _detect_forbidden_content(source_text)
    if forbidden:
        if strict:
            return None
        snippet_id = f"snippet_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return {
            "schema_version": "rig.relay.semantic_change_snippet.v1",
            "snippet_id": snippet_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source_event_id": source_event_id,
            "source_artifact_sha256": source_artifact_sha256,
            "language": language,
            "repo_area_hash": _hash_path(str(Path(path_str).parent.as_posix())),
            "path_hash": _hash_path(path_str),
            "change_kind": "unknown",
            "operation": "unknown",
            "symbol_kind": "unknown",
            "symbol_hash": None,
            "before_shape_hash": None,
            "after_shape_hash": None,
            "snippet_lines": [],
            "semantic_labels": ["forbidden_content_excluded"],
            "safety_labels": [],
            "added_line_count": 0,
            "removed_line_count": 0,
            "privacy_class": "content_light",
            "redaction_level": "structure_only",
            "forbidden_content_detected": True,
            "warnings": forbidden,
        }

    anonymized = (
        _anonymize_python_source(source_text)
        if language == "python"
        else _basic_anonymize(source_text, language)
    )
    if not anonymized.strip():
        return None

    lines = anonymized.splitlines()[:MAX_SNIPPET_LINES]
    if len(lines) < 1:
        return None

    after_shape_hash = _compute_shape_hash(lines)
    change_kind = _classify_change_kind([], lines)
    operation = _classify_operation([], lines)
    symbol_kind = _classify_symbol_kind(anonymized)

    snippet_id = (
        f"snippet_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )

    return {
        "schema_version": "rig.relay.semantic_change_snippet.v1",
        "snippet_id": snippet_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_event_id": source_event_id,
        "source_artifact_sha256": source_artifact_sha256,
        "language": language,
        "repo_area_hash": _hash_path(str(Path(path_str).parent.as_posix())),
        "path_hash": _hash_path(path_str),
        "change_kind": change_kind,
        "operation": operation,
        "symbol_kind": symbol_kind,
        "symbol_hash": None,
        "before_shape_hash": None,
        "after_shape_hash": after_shape_hash,
        "snippet_lines": lines,
        "semantic_labels": [change_kind],
        "safety_labels": [],
        "added_line_count": len(lines),
        "removed_line_count": 0,
        "privacy_class": "content_light",
        "redaction_level": "identifier_anonymized",
        "forbidden_content_detected": False,
        "warnings": None,
    }


# ── Input readers ────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return rows


def _read_artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Main export logic ────────────────────────────────────────────────────


def export_snippets(
    artifacts_dir: Path | None,
    coordination_events: Path | None,
    output_path: Path,
    strict: bool = False,
) -> tuple[int, int, list[str]]:
    """Export semantic change snippets from available sources.

    Returns (snippet_count, skipped_count, warnings).
    """
    snippets: list[dict[str, Any]] = []
    warnings: list[str] = []
    skipped = 0

    if artifacts_dir and artifacts_dir.is_dir():
        for af in sorted(artifacts_dir.glob("*.json")):
            artifact = _read_artifact(af)
            if artifact is None:
                skipped += 1
                continue
            source_text = json.dumps(artifact, sort_keys=True, indent=2)
            row = _anonymize_snippet(
                source_text=source_text,
                language="json",
                path_str=str(af),
                source_artifact_sha256=_hash_text(source_text),
                strict=strict,
            )
            if row is None:
                skipped += 1
            else:
                snippets.append(row)

    if coordination_events and coordination_events.is_file():
        events = _read_jsonl(coordination_events)
        for ev in events:
            event_id = ev.get("event_id") or ev.get("id", "")
            source_text = json.dumps(ev, sort_keys=True, indent=2)
            row = _anonymize_snippet(
                source_text=source_text,
                language="json",
                path_str=str(coordination_events),
                source_event_id=event_id,
                source_artifact_sha256=_hash_text(source_text),
                strict=strict,
            )
            if row is None:
                skipped += 1
            else:
                snippets.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for sn in snippets:
            f.write(json.dumps(sn, sort_keys=True, separators=(",", ":")) + "\n")

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "input_paths": {
            "artifacts_dir": str(artifacts_dir) if artifacts_dir else None,
            "coordination_events": str(coordination_events)
            if coordination_events
            else None,
        },
        "output_path": str(output_path),
        "snippet_count": len(snippets),
        "skipped_count": skipped,
        "warnings": warnings,
        "content_light_guarantee": True,
        "schema_path": str(SCHEMA_PATH),
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    return len(snippets), skipped, warnings


# ── CLI ───────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export anonymized semantic change snippets from artifacts and events."
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Directory containing individual JSON artifact files.",
    )
    parser.add_argument(
        "--coordination-events",
        type=Path,
        default=BUILD_ROOT / "coordination" / "events.jsonl",
        help=f"Path to coordination events.jsonl (default: {BUILD_ROOT / 'coordination' / 'events.jsonl'})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSONL path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Refuse to export snippets containing forbidden content.",
    )
    parser.add_argument(
        "--test-input",
        type=str,
        default=None,
        help="Inline Python source text for testing (ignores other inputs).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.test_input:
        row = _anonymize_snippet(
            source_text=args.test_input,
            language="python",
            path_str="test_input.py",
            strict=args.strict,
        )
        if row:
            print(json.dumps(row, indent=2))
        else:
            print("Empty or forbidden snippet.")
        return 0

    snippet_count, skipped_count, warnings = export_snippets(
        artifacts_dir=args.artifacts_dir,
        coordination_events=args.coordination_events,
        output_path=args.output,
        strict=args.strict,
    )

    print("Semantic change snippet export complete.")
    print(f"  Snippets written: {snippet_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Output: {args.output}")
    print(f"  Manifest: {MANIFEST_PATH}")
    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

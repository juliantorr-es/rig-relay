#!/usr/bin/env python3
"""Duplicate test content audit — identifies exact and near-duplicate tests.

Scans all test_*.py files, extracts test functions, normalizes AST bodies,
and groups duplicates by exact match, normalized AST, and assertion shape.

Output:
    docs/audits/test-suite/duplicate_test_groups.jsonl
    docs/audits/test-suite/duplicate_test_audit.json
    docs/audits/test-suite/duplicate_test_audit.md

Usage:
    uv run python scripts/rig_relay_test_duplicate_audit.py
    uv run python scripts/rig_relay_test_duplicate_audit.py --exact-only
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent if __file__ else Path.cwd()
TESTS_DIR = REPO_ROOT / "tests"
OUTPUT_DIR = REPO_ROOT / "docs" / "audits" / "test-suite"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_TRUNCATE_LIMIT = 5


def _normalize_ast(node: ast.AST) -> str:
    """Normalize an AST node for structural comparison.

    Strips identifiers, string/numeric literals, and positions.
    Keeps node type structure, call patterns, and assert structure.
    """

    class Normalizer(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.Name:
            return ast.Name(id="VAR", ctx=ast.Load())

        def visit_arg(self, node: ast.arg) -> ast.arg:
            return ast.arg(arg="ARG")

        def visit_Constant(self, node: ast.Constant) -> ast.Constant:
            if isinstance(node.value, str):
                return ast.Constant(value="STR")
            if isinstance(node.value, (int, float)):
                return ast.Constant(value=0)
            return node

    normalizer = Normalizer()
    normalized = normalizer.visit(node)
    return ast.dump(normalized, annotate_fields=False)


def _extract_assert_shape(node: ast.AST) -> str:
    """Extract assertion structure: assert types and comparison patterns."""

    class AssertVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.asserts: list[str] = []

        def visit_Assert(self, node: ast.Assert) -> None:
            self.asserts.append(_normalize_ast(node))
            self.generic_visit(node)

    visitor = AssertVisitor()
    visitor.visit(node)
    return "|".join(sorted(visitor.asserts))


def _extract_calls(node: ast.AST) -> str:
    """Extract called function/attribute names."""

    class CallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.calls: list[str] = []

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                self.calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                self.calls.append(node.func.attr)
            self.generic_visit(node)

    visitor = CallVisitor()
    visitor.visit(node)
    return ",".join(sorted(set(visitor.calls)))


def scan_tests() -> list[dict[str, Any]]:
    """Scan all test files and extract test function metadata."""
    results: list[dict[str, Any]] = []
    for py_file in sorted(TESTS_DIR.rglob("test_*.py")):
        if "__pycache__" in str(py_file):
            continue
        path = str(py_file.relative_to(REPO_ROOT))
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue

            body = node.body
            if not body:
                continue

            raw_body = ast.get_source_segment(py_file.read_text(), node) or ""
            body_sha = hashlib.sha256(raw_body.encode()).hexdigest()

            markers = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if isinstance(dec.func.value, ast.Name) and dec.func.value.id == "pytest":
                        markers.append(dec.func.attr)

            results.append({
                "nodeid": f"{path}::{node.name}",
                "path": path,
                "name": node.name,
                "class_name": "",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "markers": markers,
                "body_sha256": body_sha,
                "body_line_count": len(body),
                "assert_count": sum(1 for _ in ast.walk(node) if isinstance(_, ast.Assert)),
                "call_signature": _extract_calls(node),
                "normalized_ast_hash": hashlib.sha256(_normalize_ast(node).encode()).hexdigest(),
                "assert_shape_hash": hashlib.sha256(_extract_assert_shape(node).encode()).hexdigest(),
            })
    return results


def group_duplicates(tests: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Group tests by duplication type."""
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "exact_body": {},
        "normalized_ast": {},
        "assert_shape": {},
    }

    for t in tests:
        for key, hash_field in [
            ("exact_body", "body_sha256"),
            ("normalized_ast", "normalized_ast_hash"),
            ("assert_shape", "assert_shape_hash"),
        ]:
            h = t[hash_field]
            groups[key].setdefault(h, []).append(t)

    return {
        "exact_body_duplicates": {k: v for k, v in groups["exact_body"].items() if len(v) > 1},
        "normalized_ast_duplicates": {k: v for k, v in groups["normalized_ast"].items() if len(v) > 1},
        "assert_shape_duplicates": {k: v for k, v in groups["assert_shape"].items() if len(v) > 1},
    }


def write_outputs(dupes: dict, tests: list[dict[str, Any]]) -> None:
    """Write JSONL, JSON, and Markdown outputs."""
    # JSON summary
    summary = {
        "total_tests_scanned": len(tests),
        "exact_body_groups": len(dupes["exact_body_duplicates"]),
        "normalized_ast_groups": len(dupes["normalized_ast_duplicates"]),
        "assert_shape_groups": len(dupes["assert_shape_duplicates"]),
        "exact_body_test_count": sum(len(v) for v in dupes["exact_body_duplicates"].values()),
        "normalized_ast_test_count": sum(len(v) for v in dupes["normalized_ast_duplicates"].values()),
        "assert_shape_test_count": sum(len(v) for v in dupes["assert_shape_duplicates"].values()),
    }
    with open(OUTPUT_DIR / "duplicate_test_audit.json", "w") as f:
        json.dump(summary, f, indent=2)

    # JSONL groups
    group_id = 0
    with open(OUTPUT_DIR / "duplicate_test_groups.jsonl", "w") as f:
        for dup_type, groups in dupes.items():
            for _hash_val, members in groups.items():
                group_id += 1
                row = {
                    "group_id": f"dupe_{group_id:04d}",
                    "duplicate_type": dup_type,
                    "member_count": len(members),
                    "members": [m["nodeid"] for m in members],
                    "recommended_action": "parametrize" if dup_type == "normalized_ast" else "defer_manual_review",
                    "risk": "low",
                    "reason": f"{dup_type} duplicate with {len(members)} members",
                }
                f.write(json.dumps(row) + "\n")

    # Markdown report
    md = [
        "# Duplicate Test Audit",
        "",
        f"**Scanned**: {summary['total_tests_scanned']} tests",
        f"**Exact body duplicates**: {summary['exact_body_groups']} groups ({summary['exact_body_test_count']} tests)",
        f"**Normalized AST duplicates**: {summary['normalized_ast_groups']} groups ({summary['normalized_ast_test_count']} tests)",
        f"**Assert shape duplicates**: {summary['assert_shape_groups']} groups ({summary['assert_shape_test_count']} tests)",
        "",
        "## Top Exact Duplicate Groups",
        "",
    ]
    exact_sorted = sorted(dupes["exact_body_duplicates"].items(), key=lambda x: -len(x[1]))
    for hash_val, members in exact_sorted[:20]:
        md.append(f"- {len(members)} tests with body hash `{hash_val[:16]}`")
        for m in members[:_TRUNCATE_LIMIT]:
            md.append(f"  - `{m['nodeid']}`")
        if len(members) > _TRUNCATE_LIMIT:
            md.append(f"  - ... and {len(members) - _TRUNCATE_LIMIT} more")
        md.append("")

    md.append("## Top Normalized AST Duplicate Groups")
    md.append("")
    norm_sorted = sorted(dupes["normalized_ast_duplicates"].items(), key=lambda x: -len(x[1]))
    for _hash_val, members in norm_sorted[:20]:
        md.append(f"- {len(members)} tests with normalized hash `{_hash_val[:16]}`")
        for m in members[:_TRUNCATE_LIMIT]:
            md.append(f"  - `{m['nodeid']}`")
        if len(members) > _TRUNCATE_LIMIT:
            md.append(f"  - ... and {len(members) - _TRUNCATE_LIMIT} more")
        md.append("")

    with open(OUTPUT_DIR / "duplicate_test_audit.md", "w") as f:
        f.write("\n".join(md))

    print(f"Wrote: {OUTPUT_DIR / 'duplicate_test_audit.json'}")
    print(f"Wrote: {OUTPUT_DIR / 'duplicate_test_groups.jsonl'}")
    print(f"Wrote: {OUTPUT_DIR / 'duplicate_test_audit.md'}")


def main() -> None:
    tests = scan_tests()
    print(f"Scanned {len(tests)} tests")
    dupes = group_duplicates(tests)
    exact_count = len(dupes["exact_body_duplicates"])
    norm_count = len(dupes["normalized_ast_duplicates"])
    shape_count = len(dupes["assert_shape_duplicates"])
    print(f"  Exact body groups: {exact_count}")
    print(f"  Normalized AST groups: {norm_count}")
    print(f"  Assert shape groups: {shape_count}")
    write_outputs(dupes, tests)

    if "--fail-on-exact-duplicates" in sys.argv and exact_count > 0:
        print(f"\nFAIL: {exact_count} exact body duplicate group(s) found.")
        print("  Run dedup or use --max-exact-duplicate-groups=N.")
        sys.exit(1)

    for arg in sys.argv:
        if arg.startswith("--max-exact-duplicate-groups="):
            max_exact = int(arg.split("=")[1])
            if exact_count > max_exact:
                print(f"\nFAIL: {exact_count} groups exceeds max {max_exact}.")
                sys.exit(1)


if __name__ == "__main__":
    main()

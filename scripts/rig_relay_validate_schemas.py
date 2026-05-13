#!/usr/bin/env python3
"""Rig Relay Schema Validator.

Parses and validates all JSON Schema files under docs/schemas/.
Checks for:
- Valid JSON parsing
- No Python syntax contamination (e.g. from __future__ import annotations)
- Optional jsonschema Draft 7 self-validation if jsonschema is available

Usage:
    uv run python scripts/rig_relay_validate_schemas.py
    uv run python scripts/rig_relay_validate_schemas.py --strict
    uv run python scripts/rig_relay_validate_schemas.py --schema-dir docs/schemas/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"

FORBIDDEN_PYTHON_TOKENS: list[str] = [
    "from __future__ import",
    "import ",
    "def ",
    "class ",
    "# ruff:",
    "__annotations__",
]


def check_forbidden_tokens(text: str, filename: str) -> list[str]:
    """Check for Python syntax contamination in a supposed JSON file.

    Only checks text before the first JSON structural character ({ or [),
    to avoid false positives from field names inside valid JSON content.
    """
    errors: list[str] = []
    # Find first JSON structural character
    first_brace = text.find("{")
    first_bracket = text.find("[")
    cutoff = len(text)
    if first_brace >= 0 and first_brace < cutoff:
        cutoff = first_brace
    if first_bracket >= 0 and first_bracket < cutoff:
        cutoff = first_bracket
    preamble = text[:cutoff]

    for token in FORBIDDEN_PYTHON_TOKENS:
        if token in preamble:
            errors.append(f"{filename}: Contains forbidden Python token: {token!r}")
    return errors


def validate_schema(path: Path, strict: bool = False) -> tuple[bool, list[str]]:
    """Validate a single schema file.

    Returns (is_valid, list_of_errors).
    """
    errors: list[str] = []

    # Read raw text
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, [f"{path.name}: Cannot read: {e}"]

    # Check for Python contamination
    errors.extend(check_forbidden_tokens(raw, path.name))

    # Parse as JSON
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(f"{path.name}: Invalid JSON: {e}")
        return False, errors

    # Check for required schema fields (Draft-7 convention)
    if "$schema" in data:
        expected = "http://json-schema.org/draft-07/schema#"
        if data["$schema"] != expected:
            errors.append(
                f"{path.name}: Unexpected $schema value: "
                f"{data['$schema']!r} (expected {expected!r})"
            )

    # Optional: self-validate as JSON Schema Draft 7
    if strict:
        try:
            import jsonschema

            # Self-validate the schema
            validator = jsonschema.Draft7Validator(data)
            schema_errors = list(validator.iter_errors(data))
            for se in schema_errors:
                errors.append(f"{path.name}: Schema self-validation: {se.message}")
        except Exception as e:
            errors.append(f"{path.name}: Schema validation exception: {e}")

    return len(errors) == 0, errors


def validate_all_schemas(
    schema_dir: Path, strict: bool = False
) -> tuple[bool, list[str], int, int]:
    """Validate all JSON schema files in a directory.

    Returns (all_valid, all_errors, total_files, failed_files).
    """
    all_errors: list[str] = []
    total = 0
    failed = 0

    if not schema_dir.is_dir():
        return False, [f"Schema directory not found: {schema_dir}"], 0, 0

    for path in sorted(schema_dir.glob("*.json")):
        if not path.is_file():
            continue
        total += 1
        is_valid, errors = validate_schema(path, strict=strict)
        if not is_valid:
            failed += 1
            all_errors.extend(errors)

    return failed == 0, all_errors, total, failed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate all JSON Schema files for JSON correctness "
        "and Python token contamination."
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=DEFAULT_SCHEMA_DIR,
        help=f"Schema directory (default: {DEFAULT_SCHEMA_DIR})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable jsonschema Draft 7 self-validation (requires jsonschema)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-file validation results"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    all_valid, all_errors, total, failed = validate_all_schemas(
        args.schema_dir, strict=args.strict
    )

    if args.verbose:
        schemas = sorted(args.schema_dir.glob("*.json"))
        for s in schemas:
            is_valid, errs = validate_schema(s, strict=args.strict)
            status = "PASS" if is_valid else "FAIL"
            print(f"  [{status}] {s.name}")
            for e in errs:
                print(f"         {e}")

    print("\nSchema validation summary:")
    print(f"  Total: {total}")
    print(f"  Passed: {total - failed}")
    print(f"  Failed: {failed}")
    print("  jsonschema: available (core dependency)")

    if all_errors:
        print("\nErrors:")
        for e in all_errors:
            print(f"  - {e}")

    if not all_valid:
        print(f"\nFAILED: {failed} schema(s) have errors.")
        return 1

    print("\nAll schemas valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

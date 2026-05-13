"""Tests for the schema validation utility and ruff boundary hardening."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.rig_relay_validate_schemas import (
    check_forbidden_tokens,
    validate_all_schemas,
    validate_schema,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


# ── All schemas parse as JSON ────────────────────────────────────────────


def test_all_schema_files_parse_as_json():
    """Every *.schema.json file in docs/schemas/ parses as valid JSON."""
    failures: list[str] = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            failures.append(f"{path.name}: {e}")
    assert not failures, "Schema JSON parse failures:\n" + "\n".join(failures)


# ── No Python syntax contamination ───────────────────────────────────────


def test_no_schema_contains_python_syntax():
    """No schema file contains Python syntax like from __future__."""
    failures: list[str] = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            failures.append(f"{path.name}: Cannot read: {e}")
            continue
        errors = check_forbidden_tokens(raw, path.name)
        failures.extend(errors)
    assert not failures, "Python syntax contamination found:\n" + "\n".join(failures)


# ── check_forbidden_tokens unit tests ────────────────────────────────────


def test_forbidden_tokens_detects_from_future():
    """check_forbidden_tokens detects from __future__ import annotations."""
    text = 'from __future__ import annotations\n\n{"$schema": "..."}'
    errors = check_forbidden_tokens(text, "test.json")
    # Both 'from __future__ import' and 'import ' tokens match
    assert len(errors) >= 1
    assert any("from __future__ import" in e for e in errors)


def test_forbidden_tokens_detects_ruff_directive():
    """check_forbidden_tokens detects # ruff: directives."""
    text = '# ruff: noqa\n{"$schema": "..."}'
    errors = check_forbidden_tokens(text, "test.json")
    assert len(errors) == 1
    assert "# ruff:" in errors[0]


def test_forbidden_tokens_clean_json():
    """Clean JSON produces no errors."""
    text = '{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}'
    errors = check_forbidden_tokens(text, "clean.json")
    assert len(errors) == 0


def test_forbidden_tokens_detects_import():
    """check_forbidden_tokens detects import statements."""
    text = 'import os\n{"$schema": "..."}'
    errors = check_forbidden_tokens(text, "test.json")
    assert any("import " in e for e in errors)


# ── validate_schema unit tests ────────────────────────────────────────────


def test_validate_schema_clean(tmp_path):
    """validate_schema returns True for a valid JSON schema."""
    s = tmp_path / "test.schema.json"
    s.write_text(
        '{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}'
    )
    is_valid, errors = validate_schema(s)
    assert is_valid
    assert len(errors) == 0


def test_validate_schema_invalid_json(tmp_path):
    """validate_schema returns False for invalid JSON."""
    s = tmp_path / "bad.json"
    s.write_text('{"unclosed": true')
    is_valid, errors = validate_schema(s)
    assert not is_valid
    assert any("Invalid JSON" in e for e in errors)


def test_validate_schema_contaminated(tmp_path):
    """validate_schema returns False for Python-contaminated files."""
    s = tmp_path / "contaminated.json"
    s.write_text('from __future__ import annotations\n{"$schema": "..."}')
    is_valid, errors = validate_schema(s)
    assert not is_valid
    assert any("forbidden" in e.lower() for e in errors)


def test_validate_schema_unexpected_draft(tmp_path):
    """validate_schema warns on unexpected $schema value."""
    s = tmp_path / "draft4.json"
    s.write_text('{"$schema": "http://json-schema.org/draft-04/schema#"}')
    is_valid, errors = validate_schema(s)
    # This is a warning but not a hard fail for non-strict mode
    # Actually it IS currently an error in validate_schema
    # The function adds it to errors
    assert not is_valid


def test_validate_all_schemas_on_real_dir():
    """validate_all_schemas passes on the actual schema directory."""
    all_valid, all_errors, total, failed = validate_all_schemas(SCHEMAS_DIR)
    assert total >= 30, f"Expected at least 30 schemas, got {total}"
    assert all_valid, "Schema validation errors:\n" + "\n".join(all_errors)
    assert failed == 0


# ── Each schema has a $schema field ──────────────────────────────────────


def test_all_schemas_have_dollar_schema():
    """Every schema file declares $schema as draft-07."""
    failures: list[str] = []
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "$schema" not in data:
            failures.append(f"{path.name}: Missing $schema field")
        elif data["$schema"] != "http://json-schema.org/draft-07/schema#":
            failures.append(f"{path.name}: Unexpected $schema: {data['$schema']}")
    assert not failures, "\n" + "\n".join(failures)

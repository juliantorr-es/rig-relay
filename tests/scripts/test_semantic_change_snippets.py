"""Tests for semantic change snippet anonymizer and exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────

SIMPLE_FUNCTION = """
def my_function(param_one, param_two):
    \"\"\"This is a docstring.\"\"\"
    # This is a comment
    result = param_one + param_two
    return result
"""

GUARD_FUNCTION = """
if guard_result.refused:
    return WriteFileResult(error=guard_result.reason)
"""

CLASS_WITH_METHODS = """
class DataProcessor:
    def process(self, data):
        self.data = data
        return self.data
"""

FORBIDDEN_SAMPLE = """
api_key = "sk-1234567890abcdef"
"""

DIFF_HEADER_SAMPLE = """diff --git a/file.py b/file.py
index abc..def 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
+print("hello")
"""

# Dynamically locate the script
_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts"
_SCRIPT_FILE = _SCRIPT_PATH / "rig_relay_export_semantic_change_snippets.py"
_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.semantic_change_snippet.v1.schema.json"
)


@pytest.fixture(scope="session")
def anonymizer() -> object:
    """Import and return the anonymizer module."""
    import importlib.util as iu

    spec = iu.spec_from_file_location("snippet_exporter", _SCRIPT_FILE)
    assert spec is not None, f"Could not load spec from {_SCRIPT_FILE}"
    assert spec.loader is not None, f"No loader for {_SCRIPT_FILE}"
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def schema() -> dict:
    """Load the schema for validation."""
    return json.loads(_SCHEMA_PATH.read_text("utf-8"))


# ── Python anonymizer ────────────────────────────────────────────────────


class TestPythonAnonymizer:
    def test_replaces_identifiers(self, anonymizer):
        result = anonymizer._anonymize_python_source(SIMPLE_FUNCTION)
        assert "my_function" not in result, f"Raw identifier found: {result}"
        assert "FN_" in result or "VAR_" in result, f"No placeholders found: {result}"
        assert "param_one" not in result

    def test_strips_string_literals(self, anonymizer):
        result = anonymizer._anonymize_python_source(SIMPLE_FUNCTION)
        # String literal should be replaced
        assert "<STR>" in result or "This is a docstring" not in result

    def test_strips_numeric_literals(self, anonymizer):
        code = "x = 42\ny = 3.14\nz = 0"
        result = anonymizer._anonymize_python_source(code)
        assert "<NUM>" in result, f"No numeric placeholder: {result}"

    def test_removes_comments(self, anonymizer):
        result = anonymizer._anonymize_python_source(SIMPLE_FUNCTION)
        assert "# This is a comment" not in result

    def test_removes_docstrings(self, anonymizer):
        result = anonymizer._anonymize_python_source(SIMPLE_FUNCTION)
        assert "This is a docstring" not in result

    def test_preserves_control_flow_keywords(self, anonymizer):
        code = "if x > 0:\n    return True\nelse:\n    return False"
        result = anonymizer._anonymize_python_source(code)
        assert "if" in result, f"Control-flow keyword stripped: {result}"
        assert "return" in result

    def test_preserves_indentation_shape(self, anonymizer):
        result = anonymizer._anonymize_python_source(GUARD_FUNCTION)
        # Should still look like a guard clause with proper indentation
        lines = result.splitlines()
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) >= 1

    def test_anonymizes_class_names(self, anonymizer):
        result = anonymizer._anonymize_python_source(CLASS_WITH_METHODS)
        assert "DataProcessor" not in result
        assert "CLASS_" in result or "FN_" in result

    def test_anonymizes_method_names(self, anonymizer):
        result = anonymizer._anonymize_python_source(CLASS_WITH_METHODS)
        assert "process" not in result
        assert "FN_" in result

    def test_anonymizes_attributes(self, anonymizer):
        code = "guard_result.refused\n"
        result = anonymizer._anonymize_python_source(code)
        assert "guard_result" not in result
        assert "refused" not in result

    def test_handles_empty_input(self, anonymizer):
        result = anonymizer._anonymize_python_source("")
        assert result == ""

    def test_handles_syntax_error(self, anonymizer):
        code = "def broken("
        result = anonymizer._anonymize_python_source(code)
        # Should not crash; returns empty or partial
        assert result is not None


class TestForbiddenContent:
    def test_detects_api_key(self, anonymizer):
        result = anonymizer._detect_forbidden_content(FORBIDDEN_SAMPLE)
        assert len(result) > 0, "Should detect API key pattern"
        assert any("api_token" in w for w in result)

    def test_detects_diff_header(self, anonymizer):
        result = anonymizer._detect_forbidden_content(DIFF_HEADER_SAMPLE)
        assert any("raw_diff_header" in w for w in result)

    def test_clean_text_passes(self, anonymizer):
        result = anonymizer._detect_forbidden_content("if x > 0:\n    return x")
        assert len(result) == 0, f"Clean text should not trigger: {result}"


class TestAnonymizeSnippet:
    def test_returns_anonymized_row(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text=GUARD_FUNCTION, language="python", path_str="test.py"
        )
        assert row is not None
        assert row["privacy_class"] == "content_light"
        assert row["forbidden_content_detected"] is False
        assert len(row["snippet_lines"]) > 0
        assert row["schema_version"] == "rig.relay.semantic_change_snippet.v1"

    def test_snippet_no_raw_identifiers(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text=GUARD_FUNCTION, language="python", path_str="test.py"
        )
        lines = "\n".join(row["snippet_lines"])
        assert "guard_result" not in lines
        assert "WriteFileResult" not in lines

    def test_forbidden_content_excluded_non_strict(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text=FORBIDDEN_SAMPLE,
            language="python",
            path_str="test.py",
            strict=False,
        )
        assert row is not None
        assert row["forbidden_content_detected"] is True
        assert row["semantic_labels"] == ["forbidden_content_excluded"]

    def test_forbidden_content_strict_returns_none(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text=FORBIDDEN_SAMPLE,
            language="python",
            path_str="test.py",
            strict=True,
        )
        assert row is None


class TestClassification:
    def test_classify_change_kind_guard(self, anonymizer):
        kind = anonymizer._classify_change_kind(
            [], ["if <GUARD_RESULT>.<REFUSED_FLAG>:"]
        )
        assert kind == "guard_added"

    def test_classify_change_kind_test(self, anonymizer):
        kind = anonymizer._classify_change_kind([], ["def test_something():"])
        assert kind == "test_added"

    def test_classify_change_kind_schema(self, anonymizer):
        kind = anonymizer._classify_change_kind(
            [], ['"schema_version":', '"type": "object"']
        )
        assert kind == "schema_added"

    def test_classify_operation_insert(self, anonymizer):
        op = anonymizer._classify_operation([], ["line1", "line2"])
        assert op == "insert"

    def test_classify_operation_delete(self, anonymizer):
        op = anonymizer._classify_operation(["line1", "line2"], [])
        assert op == "delete"

    def test_classify_symbol_kind_test(self, anonymizer):
        kind = anonymizer._classify_symbol_kind("def test_example():")
        assert kind == "test"

    def test_classify_symbol_kind_function(self, anonymizer):
        kind = anonymizer._classify_symbol_kind("def process_data():")
        assert kind == "function"

    def test_classify_symbol_kind_schema(self, anonymizer):
        kind = anonymizer._classify_symbol_kind('{"schema_version": "test"}')
        assert kind == "schema"


class TestSchemaValidation:
    def test_schema_validates_sample(self, schema, anonymizer):
        """A well-formed snippet should validate against the schema."""
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        row = anonymizer._anonymize_snippet(
            source_text=GUARD_FUNCTION, language="python", path_str="test.py"
        )
        assert row is not None

        validator = js.Draft7Validator(schema)
        errors = list(validator.iter_errors(row))
        assert len(errors) == 0, f"Schema validation errors: {errors}"

    def test_schema_rejects_missing_fields(self, schema):
        """An empty object should fail schema validation."""
        try:
            import jsonschema as js
        except ImportError:
            pytest.skip("jsonschema not available")

        validator = js.Draft7Validator(schema)
        errors = list(validator.iter_errors({}))
        assert len(errors) > 0

    def test_output_has_valid_schema_version(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text=GUARD_FUNCTION, language="python", path_str="test.py"
        )
        assert row["schema_version"] == "rig.relay.semantic_change_snippet.v1"


class TestEmptyOrMissingInput:
    def test_empty_source_returns_none(self, anonymizer):
        row = anonymizer._anonymize_snippet(
            source_text="", language="python", path_str="empty.py"
        )
        assert row is None


class TestContentLightGuarantee:
    def test_output_does_not_contain_raw_identifiers(self, anonymizer):
        """Integration test: make sure no raw names leak through."""
        source = """
class SecretClassName:
    def secret_method(self, secret_param):
        return secret_param + "sensitive_data"
"""
        row = anonymizer._anonymize_snippet(
            source_text=source, language="python", path_str="secret.py"
        )
        assert row is not None
        lines = "\n".join(row["snippet_lines"])
        for word in [
            "SecretClassName",
            "secret_method",
            "secret_param",
            "sensitive_data",
        ]:
            assert word not in lines, f"Raw identifier leaked: {word}"

"""Model-dump-vs-JSON-Schema contract tests for hardened tools.

Validates that actual Pydantic model dumps conform to their corresponding
JSON Schema definitions. Covers bash, search_replace, and validate
result/receipt/invocation models.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from vibe.core.tools.builtins.bash import BashArgs, BashReceipt, BashResult
from vibe.core.tools.builtins.search_replace import (
    SearchReplaceArgs,
    SearchReplaceReceipt,
    SearchReplaceResult,
)
from vibe.core.tools.builtins.validate_models import (
    ValidateArgs,
    ValidateReceipt,
    ValidateResult,
)
from vibe.core.tools.builtins.write_file import WriteFileReceipt

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    assert path.is_file(), f"Schema not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(instance: dict, schema: dict, label: str) -> None:
    jsonschema.validate(instance=instance, schema=schema)
    # If no exception, it's valid


# ── Bash ──────────────────────────────────────────────────────────────


class TestBashSchema:
    """Model dump validates against JSON Schema for bash models."""

    def test_bash_result_schema(self) -> None:
        schema = _load_schema("rig.relay.bash_result.v1.schema.json")
        instance = BashResult(
            command="echo hi",
            stdout="hi\n",
            stderr="",
            returncode=0,
            status="success",
            stdout_bytes=3,
            stderr_bytes=0,
        ).model_dump(mode="json")
        _validate(instance, schema, "BashResult")

    def test_bash_receipt_schema(self) -> None:
        schema = _load_schema("rig.relay.bash_receipt.v1.schema.json")
        instance = BashReceipt(
            command="echo hi",
            status="success",
            exit_code=0,
            stdout_bytes=3,
            stderr_bytes=0,
            stdout_sha256="abc",
        ).model_dump(mode="json", exclude_none=True)
        _validate(instance, schema, "BashReceipt")

    def test_bash_args_schema(self) -> None:
        schema = _load_schema("rig.relay.bash_invocation.v1.schema.json")
        instance = BashArgs(command="echo hi").model_dump(mode="json")
        _validate(instance, schema, "BashArgs")

    def test_bash_result_extra_forbidden(self) -> None:
        """additionalProperties=false rejects unknown fields."""
        schema = _load_schema("rig.relay.bash_result.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "command": "x",
                    "status": "success",
                    "returncode": 0,
                    "unknown_field": "bad",
                },
                schema=schema,
            )

    def test_bash_receipt_nullable(self) -> None:
        """Nullable fields error_kind, refusal_reason, stdout_sha256 accept null."""
        schema = _load_schema("rig.relay.bash_receipt.v1.schema.json")
        instance = BashReceipt(
            command="echo hi",
            status="success",
            exit_code=0,
            error_kind=None,
            refusal_reason=None,
            stdout_sha256=None,
            stderr_sha256=None,
        ).model_dump(mode="json", exclude_none=True)
        # Should pass without error
        _validate(instance, schema, "BashReceipt nullable")


# ── SearchReplace ─────────────────────────────────────────────────────


class TestSearchReplaceSchema:
    """Model dump validates against JSON Schema for search_replace models."""

    def test_search_replace_result_schema(self) -> None:
        schema = _load_schema("rig.relay.search_replace_result.v1.schema.json")
        instance = SearchReplaceResult(
            file="test.py",
            blocks_applied=1,
            lines_changed=2,
            content="x = 1\n",
            warnings=[],
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            replacements=1,
            before_bytes=6,
            after_bytes=6,
            status="success",
            duration_ms=5.0,
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceResult")

    def test_search_replace_receipt_schema(self) -> None:
        schema = _load_schema("rig.relay.search_replace_receipt.v1.schema.json")
        instance = SearchReplaceReceipt(
            file="test.py",
            status="success",
            blocks_applied=1,
            lines_changed=2,
            replacements=1,
            warnings=[],
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            before_bytes=6,
            after_bytes=6,
            duration_ms=5.0,
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceReceipt")

    def test_search_replace_args_schema(self) -> None:
        schema = _load_schema("rig.relay.search_replace_invocation.v1.schema.json")
        instance = SearchReplaceArgs(
            file_path="test.py", content="x = 2\n", allow_multiple=False
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceArgs")

    def test_search_replace_result_blocked(self) -> None:
        schema = _load_schema("rig.relay.search_replace_result.v1.schema.json")
        instance = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="blocked",
            error_kind="path_reserved",
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceResult blocked")

    def test_search_replace_result_refused(self) -> None:
        schema = _load_schema("rig.relay.search_replace_result.v1.schema.json")
        instance = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="refused",
            error_kind="file_not_found",
            refusal_reason="File does not exist",
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceResult refused")

    def test_search_replace_receipt_blocked(self) -> None:
        schema = _load_schema("rig.relay.search_replace_receipt.v1.schema.json")
        instance = SearchReplaceReceipt(
            file="test.py",
            status="blocked",
            blocks_applied=0,
            lines_changed=0,
            error_kind="path_reserved",
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceReceipt blocked")

    def test_search_replace_receipt_refused(self) -> None:
        schema = _load_schema("rig.relay.search_replace_receipt.v1.schema.json")
        instance = SearchReplaceReceipt(
            file="test.py",
            status="refused",
            blocks_applied=0,
            lines_changed=0,
            error_kind="file_not_found",
            refusal_reason="File does not exist",
        ).model_dump(mode="json")
        _validate(instance, schema, "SearchReplaceReceipt refused")


# ── Validate ──────────────────────────────────────────────────────────


class TestWriteFileSchema:
    """Model dump validates against JSON Schema for write_file models."""

    def test_write_file_receipt_schema(self) -> None:
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        instance = WriteFileReceipt(
            path="/tmp/test.py",
            status="success",
            bytes_written=10,
            after_sha256="abc",
            file_existed=False,
            created_file=True,
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileReceipt")

    def test_write_file_receipt_refused_schema(self) -> None:
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        instance = WriteFileReceipt(
            path="/tmp/test.py",
            status="refused",
            bytes_written=0,
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileReceipt refused")

    def test_write_file_receipt_blocked_schema(self) -> None:
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        instance = WriteFileReceipt(
            path="/tmp/test.py",
            status="blocked",
            bytes_written=0,
            error_kind="path_reserved",
            refusal_reason="Reservation refused",
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileReceipt blocked")

    def test_write_file_receipt_extra_forbidden(self) -> None:
        """additionalProperties=false rejects unknown fields."""
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={"path": "/tmp/x.py", "status": "success", "content": "bad"},
                schema=schema,
            )


class TestValidateSchema:
    """Model dump validates against JSON Schema for validate models."""

    def test_validate_result_schema(self) -> None:
        schema = _load_schema("rig.relay.validate_result.v1.schema.json")
        instance = ValidateResult(
            status="passed",
            profile="quick",
            command_count=1,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
            duration_ms=10.0,
        ).model_dump(mode="json")
        _validate(instance, schema, "ValidateResult")

    def test_validate_result_nullable(self) -> None:
        """before_git_state/after_git_state accept null."""
        schema = _load_schema("rig.relay.validate_result.v1.schema.json")
        instance = ValidateResult(
            status="passed",
            profile="quick",
            command_count=1,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
            before_git_state=None,
            after_git_state=None,
        ).model_dump(mode="json")
        _validate(instance, schema, "ValidateResult nullable git state")

    def test_validate_receipt_schema(self) -> None:
        schema = _load_schema("rig.relay.validate_receipt.v1.schema.json")
        instance = ValidateReceipt(
            profile="quick",
            status="passed",
            command_count=1,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
            before_git_summary=None,
            after_git_summary=None,
        ).model_dump(mode="json")
        _validate(instance, schema, "ValidateReceipt")

    def test_validate_args_schema(self) -> None:
        schema = _load_schema("rig.relay.validate_invocation.v1.schema.json")
        instance = ValidateArgs(profile="schemas").model_dump(mode="json")
        _validate(instance, schema, "ValidateArgs")

    def test_validate_args_extra_forbidden(self) -> None:
        """additionalProperties=false rejects unknown fields."""
        schema = _load_schema("rig.relay.validate_invocation.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={"profile": "quick", "unknown_field": "bad"}, schema=schema
            )

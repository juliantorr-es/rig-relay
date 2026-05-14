"""Model-dump-vs-JSON-Schema contract tests for hardened tools.

Validates that actual Pydantic model dumps conform to their corresponding
JSON Schema definitions. Covers bash, search_replace, write_file, and
validate result/receipt/invocation models.

Isolation guarantees:
- Schema files are read-only, never written by any test in this suite.
- ``SCHEMAS_DIR`` is a module-level constant computed from ``__file__``.
  Under xdist each worker process imports this module independently, so
  the path is correct per-worker (no cross-worker interference).
- There is no shared mutable state between test methods.
- The ``schemas_dir`` fixture in ``tests/tools/conftest.py`` may be used
  by new tests; existing tests use the module-level constant for brevity.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.core.tools.builtins.bash import BashArgs, BashReceipt, BashResult
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplaceArgs,
    SearchReplaceReceipt,
    SearchReplaceResult,
)
from rig_relay.core.tools.builtins.validate_models import (
    ValidateArgs,
    ValidateReceipt,
    ValidateResult,
)
from rig_relay.core.tools.builtins.write_file import (
    WriteFileArgs,
    WriteFileReceipt,
    WriteFileResult,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    assert path.is_file(), f"Schema not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(instance: dict, schema: dict, label: str) -> None:
    jsonschema.validate(instance=instance, schema=schema)
    # If no exception, it's valid


# ── Regression: order independence under xdist ────────────────────────


def test_schema_contracts_do_not_depend_on_execution_order(schemas_dir: Path) -> None:
    """Verify every schema contract test constructs valid instances.

    This single test exercises ALL request/result/receipt model
    constructors used by the class-based tests below.  If it passes
    then the per-class tests cannot fail due to execution order,
    because each model is constructed and validated independently.

    Under xdist every worker runs this test and gets the same result,
    proving there is no shared mutable state between test invocations.
    """
    from rig_relay.core.tools.builtins.bash import BashArgs, BashReceipt, BashResult
    from rig_relay.core.tools.builtins.search_replace import (
        SearchReplaceArgs,
        SearchReplaceReceipt,
        SearchReplaceResult,
    )
    from rig_relay.core.tools.builtins.validate_models import (
        ValidateArgs,
        ValidateReceipt,
        ValidateResult,
    )
    from rig_relay.core.tools.builtins.write_file import (
        WriteFileArgs,
        WriteFileReceipt,
        WriteFileResult,
    )

    cases: list[tuple[dict, str]] = [
        # Bash
        (
            BashResult(
                command="echo hi",
                stdout="hi\n",
                stderr="",
                returncode=0,
                status="success",
                stdout_bytes=3,
                stderr_bytes=0,
            ).model_dump(mode="json"),
            "rig.relay.bash_result.v1.schema.json",
        ),
        (
            BashReceipt(
                command="echo hi",
                status="success",
                exit_code=0,
                stdout_bytes=3,
                stderr_bytes=0,
                stdout_sha256="abc",
            ).model_dump(mode="json"),
            "rig.relay.bash_receipt.v1.schema.json",
        ),
        (
            BashArgs(command="echo hi").model_dump(mode="json"),
            "rig.relay.bash_invocation.v1.schema.json",
        ),
        # SearchReplace
        (
            SearchReplaceResult(
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
            ).model_dump(mode="json"),
            "rig.relay.search_replace_result.v1.schema.json",
        ),
        (
            SearchReplaceReceipt(
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
            ).model_dump(mode="json"),
            "rig.relay.search_replace_receipt.v1.schema.json",
        ),
        (
            SearchReplaceArgs(
                file_path="test.py", content="x = 2\n", allow_multiple=False
            ).model_dump(mode="json"),
            "rig.relay.search_replace_invocation.v1.schema.json",
        ),
        # WriteFile
        (
            WriteFileReceipt(
                path="/tmp/test.py",
                status="success",
                bytes_written=10,
                after_sha256="abc",
                file_existed=False,
                created_file=True,
            ).model_dump(mode="json"),
            "rig.relay.write_file_receipt.v1.schema.json",
        ),
        (
            WriteFileArgs(path="/tmp/test.py", content="print(1)\n").model_dump(
                mode="json"
            ),
            "rig.relay.write_file_invocation.v1.schema.json",
        ),
        (
            WriteFileResult(
                path="/tmp/test.py",
                bytes_written=10,
                file_existed=False,
                content="print(1)\n",
                after_sha256="abc",
                status="success",
                created_file=True,
            ).model_dump(mode="json"),
            "rig.relay.write_file_result.v1.schema.json",
        ),
        # Validate
        (
            ValidateResult(
                status="passed",
                profile="quick",
                command_count=1,
                passed_count=1,
                failed_count=0,
                skipped_count=0,
                duration_ms=10.0,
            ).model_dump(mode="json"),
            "rig.relay.validate_result.v1.schema.json",
        ),
        (
            ValidateReceipt(
                profile="quick",
                status="passed",
                command_count=1,
                passed_count=1,
                failed_count=0,
                skipped_count=0,
                before_git_summary=None,
                after_git_summary=None,
            ).model_dump(mode="json"),
            "rig.relay.validate_receipt.v1.schema.json",
        ),
        (
            ValidateArgs(profile="schemas").model_dump(mode="json"),
            "rig.relay.validate_invocation.v1.schema.json",
        ),
    ]

    errors: list[str] = []
    for instance, schema_name in cases:
        schema_path = schemas_dir / schema_name
        assert schema_path.is_file(), f"Schema not found: {schema_path}"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(instance=instance, schema=schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{schema_name}: {e.message}")

    assert not errors, f"{len(errors)} schema validation(s) failed:\n" + "\n".join(
        errors
    )


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
        ).model_dump(mode="json")
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
        ).model_dump(mode="json")
        _validate(instance, schema, "BashReceipt nullable")

    def test_bash_result_required_fields_validates(self) -> None:
        """Minimal BashResult with stdout/stderr validates against schema."""
        schema = _load_schema("rig.relay.bash_result.v1.schema.json")
        instance = BashResult(
            command="echo hi", stdout="hi\n", stderr="", returncode=0, status="success"
        ).model_dump(mode="json")
        _validate(instance, schema, "BashResult minimal required fields")


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


# ── WriteFile ─────────────────────────────────────────────────────────


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

    def test_write_file_invocation_schema(self) -> None:
        schema = _load_schema("rig.relay.write_file_invocation.v1.schema.json")
        instance = WriteFileArgs(path="/tmp/test.py", content="print(1)\n").model_dump(
            mode="json"
        )
        _validate(instance, schema, "WriteFileArgs")

    def test_write_file_invocation_with_overwrite(self) -> None:
        schema = _load_schema("rig.relay.write_file_invocation.v1.schema.json")
        instance = WriteFileArgs(
            path="/tmp/test.py",
            content="print(2)\n",
            overwrite=True,
            allow_overwrite_protected=True,
            expected_before_sha256="sha256:abc123",
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileArgs with overwrite")

    def test_write_file_result_schema(self) -> None:
        schema = _load_schema("rig.relay.write_file_result.v1.schema.json")
        instance = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=10,
            file_existed=False,
            content="print(1)\n",
            after_sha256="abc",
            status="success",
            created_file=True,
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileResult")

    def test_write_file_result_refused(self) -> None:
        schema = _load_schema("rig.relay.write_file_result.v1.schema.json")
        instance = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=0,
            file_existed=True,
            content="",
            after_sha256="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        ).model_dump(mode="json")
        _validate(instance, schema, "WriteFileResult refused")

    def test_write_file_invocation_extra_forbidden(self) -> None:
        """WriteFile invocation schema rejects unknown fields."""
        schema = _load_schema("rig.relay.write_file_invocation.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "path": "/tmp/test.py",
                    "content": "print(1)\n",
                    "unknown_field": "bad",
                },
                schema=schema,
            )

    def test_write_file_result_extra_forbidden(self) -> None:
        """WriteFile result schema rejects unknown fields."""
        schema = _load_schema("rig.relay.write_file_result.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "path": "/tmp/test.py",
                    "bytes_written": 0,
                    "file_existed": False,
                    "content": "",
                    "status": "success",
                    "unknown_field": "bad",
                },
                schema=schema,
            )

    def test_write_file_result_after_sha256_rejects_null(self) -> None:
        """WriteFile result schema rejects null after_sha256 (model is non-nullable str)."""
        schema = _load_schema("rig.relay.write_file_result.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "path": "/tmp/test.py",
                    "bytes_written": 10,
                    "file_existed": False,
                    "content": "data",
                    "after_sha256": None,
                    "status": "success",
                },
                schema=schema,
            )


# ── Validate ──────────────────────────────────────────────────────────


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

    def test_validate_result_unknown_status_schema(self) -> None:
        """ValidateResult with status='unknown' validates against schema."""
        schema = _load_schema("rig.relay.validate_result.v1.schema.json")
        instance = ValidateResult(status="unknown", profile="quick").model_dump(
            mode="json"
        )
        _validate(instance, schema, "ValidateResult unknown status")

    def test_validate_result_check_result_extra_forbidden(self) -> None:
        """ValidateCheckResult nested object rejects unknown fields."""
        schema = _load_schema("rig.relay.validate_result.v1.schema.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                instance={
                    "status": "passed",
                    "profile": "quick",
                    "command_count": 0,
                    "passed_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "checks": [
                        {
                            "check_id": "c1",
                            "command_kind": "pytest",
                            "status": "passed",
                            "unknown_field": "bad",
                        }
                    ],
                },
                schema=schema,
            )

    def test_validate_args_pydantic_rejects_extra(self) -> None:
        """ValidateArgs Pydantic model rejects extra fields at construction."""
        with pytest.raises((TypeError, ValueError)):
            ValidateArgs(profile="quick", unknown_field="bad")  # type: ignore[call-arg]

    def test_validate_args_cache_policy_fields(self) -> None:
        """ValidateArgs serializes new cache/scheduler/parallel fields."""
        schema = _load_schema("rig.relay.validate_invocation.v1.schema.json")
        instance = ValidateArgs(
            profile="quick",
            cache_policy="enabled",
            allow_failed_cache_reuse=False,
            cache_root="/tmp/cache",
            scheduler_policy="enabled",
            lock_running_checks=True,
            validation_phase="edit",
            parallel_policy="auto",
            max_workers=4,
            xdist_distribution="loadscope",
        ).model_dump(mode="json")
        _validate(instance, schema, "ValidateArgs cache policy")

    def test_validate_args_cache_policy_defaults(self) -> None:
        """ValidateArgs default values validate against schema."""
        schema = _load_schema("rig.relay.validate_invocation.v1.schema.json")
        instance = ValidateArgs(profile="quick").model_dump(mode="json")
        _validate(instance, schema, "ValidateArgs defaults")

    def test_validate_check_result_metadata_fields(self) -> None:
        """ValidateCheckResult with new metadata fields validates against schema."""
        schema = _load_schema("rig.relay.validate_result.v1.schema.json")
        instance = ValidateResult(
            status="passed",
            profile="quick",
            command_count=1,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
            checks=[
                {
                    "check_id": "c1",
                    "command_kind": "pytest",
                    "status": "passed",
                    "cache_status": "hit",
                    "cache_key": "sha256:abc123",
                    "cache_record_sha256": "sha256:def456",
                    "input_fingerprint": "sha256:fp123",
                    "reused_from": "sha256:src789",
                    "scheduler_status": "running",
                    "parallel_status": "enabled",
                    "worker_count": 4,
                    "distribution": "loadfile",
                    "validation_phase": "edit",
                }
            ],
        ).model_dump(mode="json")
        _validate(instance, schema, "ValidateCheckResult metadata")

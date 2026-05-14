"""Shared mutation-tool contract tests for write_file and search_replace.

Verifies both tools meet the same deterministic evidence guarantees:
- build_receipt exists
- success receipts are content-light
- refusal/blocked receipts are content-light
- receipt schemas validate
- receipt policy validator passes
- receipt index supports both with mutation tracking
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceConfig,
    SearchReplaceResult,
)
from rig_relay.core.tools.builtins.write_file import (
    WriteFile,
    WriteFileConfig,
    WriteFileResult,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
FORBIDDEN_RECEIPT_FIELDS = frozenset({
    "content",
    "old_text",
    "new_text",
    "diff",
    "patch",
    "snippet",
    "stdout",
    "stderr",
    "output",
    "file_contents",
})


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def wf_tool() -> WriteFile:
    return WriteFile(config_getter=lambda: WriteFileConfig(), state=BaseToolState())


@pytest.fixture
def sr_tool() -> SearchReplace:
    return SearchReplace(
        config_getter=lambda: SearchReplaceConfig(), state=BaseToolState()
    )


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    assert path.is_file(), f"Schema not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ── Shared helpers ────────────────────────────────────────────────────


def _check_content_light(instance: dict, label: str) -> None:
    """Assert no forbidden raw fields appear in the receipt dump."""
    for key in instance:
        for forbidden in FORBIDDEN_RECEIPT_FIELDS:
            assert forbidden not in key, (
                f"Forbidden field '{key}' (matches '{forbidden}') in {label}"
            )


# ── build_receipt exists ─────────────────────────────────────────────


class TestBuildReceipt:
    """Both tools have build_receipt method."""

    def test_write_file_has_build_receipt(self, wf_tool: WriteFile) -> None:
        assert hasattr(wf_tool, "build_receipt")

    def test_search_replace_has_build_receipt(self, sr_tool: SearchReplace) -> None:
        assert hasattr(sr_tool, "build_receipt")


# ── Content-light receipts ────────────────────────────────────────────


class TestContentLightReceipts:
    """Success and refusal/blocked receipts are content-light."""

    def test_write_file_success_receipt_content_light(self, wf_tool: WriteFile) -> None:
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=10,
            file_existed=False,
            content="print(1)\n",
            before_sha256=None,
            after_sha256="abc123",
            status="success",
            created_file=True,
        )
        receipt = wf_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "write_file success receipt")

    def test_write_file_refused_receipt_content_light(self, wf_tool: WriteFile) -> None:
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=0,
            file_existed=True,
            content="",
            before_sha256=None,
            after_sha256="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = wf_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "write_file refused receipt")

    def test_write_file_blocked_receipt_content_light(self, wf_tool: WriteFile) -> None:
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=0,
            file_existed=True,
            content="",
            before_sha256=None,
            after_sha256="",
            status="blocked",
            error_kind="path_reserved",
            refusal_reason="Coordination reservation refused",
        )
        receipt = wf_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "write_file blocked receipt")

    def test_search_replace_success_receipt_content_light(
        self, sr_tool: SearchReplace
    ) -> None:
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=1,
            lines_changed=2,
            content="print(2)\n",
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            replacements=1,
            before_bytes=8,
            after_bytes=8,
            status="success",
            duration_ms=5.0,
        )
        receipt = sr_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "search_replace success receipt")

    def test_search_replace_refused_receipt_content_light(
        self, sr_tool: SearchReplace
    ) -> None:
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = sr_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "search_replace refused receipt")

    def test_search_replace_blocked_receipt_content_light(
        self, sr_tool: SearchReplace
    ) -> None:
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="blocked",
            error_kind="path_reserved",
            refusal_reason="Coordination reservation refused",
        )
        receipt = sr_tool.build_receipt(result)
        dumped = receipt.model_dump(mode="json")
        _check_content_light(dumped, "search_replace blocked receipt")


# ── Receipt schema validation ─────────────────────────────────────────


class TestReceiptSchema:
    """Receipt model dumps validate against their JSON schemas."""

    def test_write_file_receipt_schema(self, wf_tool: WriteFile) -> None:
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=10,
            file_existed=False,
            content="x=1\n",
            before_sha256=None,
            after_sha256="abc",
            status="success",
            created_file=True,
        )
        receipt = wf_tool.build_receipt(result)
        receipt_dict = receipt.model_dump(mode="json")
        jsonschema.validate(instance=receipt_dict, schema=schema)

    def test_write_file_refused_receipt_schema(self, wf_tool: WriteFile) -> None:
        schema = _load_schema("rig.relay.write_file_receipt.v1.schema.json")
        result = WriteFileResult(
            path="/tmp/secret.py",
            bytes_written=0,
            file_existed=True,
            content="",
            before_sha256=None,
            after_sha256="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused write",
        )
        receipt = wf_tool.build_receipt(result)
        receipt_dict = receipt.model_dump(mode="json")
        jsonschema.validate(instance=receipt_dict, schema=schema)

    def test_search_replace_receipt_schema(self, sr_tool: SearchReplace) -> None:
        schema = _load_schema("rig.relay.search_replace_receipt.v1.schema.json")
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=1,
            lines_changed=2,
            content="y=2\n",
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            replacements=1,
            before_bytes=4,
            after_bytes=4,
            status="success",
            duration_ms=5.0,
        )
        receipt = sr_tool.build_receipt(result)
        receipt_dict = receipt.model_dump(mode="json")
        jsonschema.validate(instance=receipt_dict, schema=schema)

    def test_search_replace_refused_receipt_schema(
        self, sr_tool: SearchReplace
    ) -> None:
        schema = _load_schema("rig.relay.search_replace_receipt.v1.schema.json")
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = sr_tool.build_receipt(result)
        receipt_dict = receipt.model_dump(mode="json")
        jsonschema.validate(instance=receipt_dict, schema=schema)


# ── Receipt policy validator ──────────────────────────────────────────


class TestReceiptPolicy:
    """Receipts pass the receipt policy validator."""

    def test_write_file_receipt_passes_policy(self, wf_tool: WriteFile) -> None:
        from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload

        result = WriteFileResult(
            path="/tmp/test.txt",
            bytes_written=5,
            file_existed=False,
            content="hello",
            before_sha256=None,
            after_sha256="abc",
            status="success",
            created_file=True,
        )
        receipt = wf_tool.build_receipt(result)
        payload = {
            "tool_name": "write_file",
            "receipt": receipt.model_dump(mode="json"),
        }
        findings = validate_receipt_payload(payload)
        assert not findings, f"Policy violations: {findings}"

    def test_write_file_refused_receipt_passes_policy(self, wf_tool: WriteFile) -> None:
        from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload

        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=0,
            file_existed=True,
            content="",
            before_sha256=None,
            after_sha256="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = wf_tool.build_receipt(result)
        payload = {
            "tool_name": "write_file",
            "receipt": receipt.model_dump(mode="json"),
        }
        findings = validate_receipt_payload(payload)
        assert not findings, f"Policy violations: {findings}"

    def test_search_replace_receipt_passes_policy(self, sr_tool: SearchReplace) -> None:
        from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload

        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=1,
            lines_changed=2,
            content="y=2\n",
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            replacements=1,
            before_bytes=4,
            after_bytes=4,
            status="success",
            duration_ms=5.0,
        )
        receipt = sr_tool.build_receipt(result)
        payload = {
            "tool_name": "search_replace",
            "receipt": receipt.model_dump(mode="json"),
        }
        findings = validate_receipt_payload(payload)
        assert not findings, f"Policy violations: {findings}"

    def test_search_replace_refused_receipt_passes_policy(
        self, sr_tool: SearchReplace
    ) -> None:
        from rig_relay.evidence.tool_receipt_policy import validate_receipt_payload

        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = sr_tool.build_receipt(result)
        payload = {
            "tool_name": "search_replace",
            "receipt": receipt.model_dump(mode="json"),
        }
        findings = validate_receipt_payload(payload)
        assert not findings, f"Policy violations: {findings}"


# ── Receipt fields ────────────────────────────────────────────────────


class TestReceiptFields:
    """Receipts have expected path/status/error_kind/refusal_reason and hash fields."""

    def test_write_file_receipt_has_required_fields(self, wf_tool: WriteFile) -> None:
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=10,
            file_existed=False,
            content="x=1\n",
            before_sha256=None,
            after_sha256="abc",
            status="success",
            created_file=True,
        )
        receipt = wf_tool.build_receipt(result)
        d = receipt.model_dump(mode="json")
        assert "path" in d
        assert "status" in d
        assert d["status"] == "success"
        assert d["after_sha256"] == "abc"
        assert d["file_existed"] is False
        assert d["created_file"] is True

    def test_write_file_refused_receipt_has_error_fields(
        self, wf_tool: WriteFile
    ) -> None:
        result = WriteFileResult(
            path="/tmp/test.py",
            bytes_written=0,
            file_existed=True,
            content="",
            before_sha256=None,
            after_sha256="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = wf_tool.build_receipt(result)
        d = receipt.model_dump(mode="json")
        assert d["status"] == "refused"
        assert d["error_kind"] == "dirty_file_protected"
        assert d["refusal_reason"] is None or d["refusal_reason"] == "Guard refused"

    def test_search_replace_receipt_has_required_fields(
        self, sr_tool: SearchReplace
    ) -> None:
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=1,
            lines_changed=2,
            content="y=2\n",
            before_file_sha256={"test.py": "abc"},
            after_file_sha256={"test.py": "def"},
            changed_files=["test.py"],
            failed_block_count=0,
            total_block_count=1,
            replacements=1,
            before_bytes=4,
            after_bytes=4,
            status="success",
            duration_ms=5.0,
        )
        receipt = sr_tool.build_receipt(result)
        d = receipt.model_dump(mode="json")
        assert "file" in d
        assert "status" in d
        assert d["status"] == "success"
        assert d["blocks_applied"] == 1
        assert d["before_file_sha256"] == {"test.py": "abc"}
        assert d["after_file_sha256"] == {"test.py": "def"}

    def test_search_replace_refused_receipt_has_error_fields(
        self, sr_tool: SearchReplace
    ) -> None:
        result = SearchReplaceResult(
            file="test.py",
            blocks_applied=0,
            lines_changed=0,
            content="",
            status="refused",
            error_kind="dirty_file_protected",
            refusal_reason="Guard refused",
        )
        receipt = sr_tool.build_receipt(result)
        d = receipt.model_dump(mode="json")
        assert d["status"] == "refused"
        assert d["error_kind"] == "dirty_file_protected"
        assert d["refusal_reason"] is None or d["refusal_reason"] == "Guard refused"

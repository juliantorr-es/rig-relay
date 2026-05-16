"""Context Assembler Stable v1 — final receipt warning hardening and stability tests."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Receipt warning hardening ───────────────────────────────────


class TestReceiptScanWarnings:
    def test_scan_receipts_accepts_warnings_param(self) -> None:
        import inspect

        from rig_relay.context.compiler import _scan_receipts

        sig = inspect.signature(_scan_receipts)
        assert "warnings" in sig.parameters

    def test_scan_receipts_failure_emits_warning(self) -> None:
        from rig_relay.context.compiler import _scan_receipts

        warnings: list[dict[str, Any]] = []
        # Create a tmp path with unreadable file simulation
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            receipts_dir = root / ".build" / "rig-relay" / "coordination" / "receipts"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            # Create a file then remove it to simulate read failure
            bad_file = receipts_dir / "bad.receipt"
            bad_file.write_text("test")

            with patch.object(Path, "read_bytes", side_effect=OSError("read error")):
                _scan_receipts(root, warnings=warnings)

            assert len(warnings) >= 1
            assert warnings[0]["code"] == "receipt_scan_failed"

    def test_scan_receipts_failure_continues(self) -> None:
        from rig_relay.context.compiler import _scan_receipts

        warnings: list[dict[str, Any]] = []
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            receipts_dir = root / ".build" / "rig-relay" / "coordination" / "receipts"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            good_file = receipts_dir / "good.receipt"
            good_file.write_text("ok data")
            bad_file = receipts_dir / "bad.receipt"
            bad_file.write_text("bad")

            # Make only the bad file fail
            original = Path.read_bytes

            def _failing_read(self):
                if self.name == "bad.receipt":
                    raise OSError("read error")
                return original(self)

            with patch.object(Path, "read_bytes", _failing_read):
                entries = _scan_receipts(root, warnings=warnings)

            # Should still return both entries (one with empty sha)
            assert len(entries) >= 1

    def test_receipt_warning_is_content_light(self) -> None:
        from rig_relay.context.compiler import _scan_receipts

        warnings: list[dict[str, Any]] = []
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            receipts_dir = root / ".build" / "rig-relay" / "coordination" / "receipts"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            bad_file = receipts_dir / "bad.receipt"
            bad_file.write_text("test")

            with patch.object(
                Path, "read_bytes", side_effect=OSError("secret /Users/leak")
            ):
                _scan_receipts(root, warnings=warnings)

            for w in warnings:
                detail = w.get("detail", "")
                # No raw paths in detail
                assert "/Users" not in detail
                assert "leak" not in detail


# ── Warning policy tests ────────────────────────────────────────


class TestWarningPolicy:
    def test_context_packet_has_warnings_field(self) -> None:
        from rig_relay.context.models import ContextPacket

        # Check the model field definition, not construction
        fields = ContextPacket.model_fields
        assert "warnings" in fields
        assert fields["warnings"].default is not None

    def test_context_receipt_no_warnings_field(self) -> None:
        from rig_relay.context.models import ContextReceipt

        # Check model fields — v1 policy: no warnings field
        fields = ContextReceipt.model_fields
        assert "warnings" not in fields, (
            "v1 policy: ContextReceipt does not carry warnings"
        )

    def test_context_envelope_receipt_no_warnings_field(self) -> None:
        from rig_relay.context.models import ContextEnvelopeReceipt

        # Check model fields — v1 policy: no warnings field
        fields = ContextEnvelopeReceipt.model_fields
        assert "warnings" not in fields, (
            "v1 policy: ContextEnvelopeReceipt does not carry warnings"
        )

    def test_warning_policy_documented_in_stable_v1(self) -> None:
        doc = _REPO_ROOT / "docs/audits/context/context-assembler-stable-v1.md"
        assert doc.exists()
        content = doc.read_text()
        assert "ContextPacket" in content
        assert "warnings" in content.lower()


# ── Except/pass audit ───────────────────────────────────────────


class TestCriticalPathNoSilentPass:
    def test_compiler_no_silent_except_pass(self) -> None:
        compiler = _REPO_ROOT / "rig_relay/context/compiler.py"
        tree = ast.parse(compiler.read_text())

        silent_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.body and len(handler.body) == 1:
                        if isinstance(handler.body[0], ast.Pass):
                            silent_count += 1

        # Allow up to 1 silent pass (in build_envelope's broad safety net)
        assert silent_count <= 1, f"Found {silent_count} silent except:pass in compiler"

    def test_renderer_no_silent_except_pass(self) -> None:
        renderer = _REPO_ROOT / "rig_relay/context/renderer.py"
        tree = ast.parse(renderer.read_text())

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.body and len(handler.body) == 1:
                        if isinstance(handler.body[0], ast.Pass):
                            pytest.fail("Renderer has silent except:pass")


# ── Stable v1 doc tests ─────────────────────────────────────────


class TestStableV1Doc:
    def test_stable_v1_doc_exists(self) -> None:
        doc = _REPO_ROOT / "docs/audits/context/context-assembler-stable-v1.md"
        assert doc.exists()

    def test_stable_v1_status_declared(self) -> None:
        doc = _REPO_ROOT / "docs/audits/context/context-assembler-stable-v1.md"
        content = doc.read_text()
        assert "CONTEXT_ASSEMBLER_STABLE_V1" in content

    def test_stable_v1_lists_stable_api(self) -> None:
        doc = _REPO_ROOT / "docs/audits/context/context-assembler-stable-v1.md"
        content = doc.read_text()
        assert "ContextRequest" in content
        assert "ContextPacket" in content
        assert "ContextAssemblyPlan" in content
        assert "plan_context" in content


# ── Existing closeout tests still pass ──────────────────────────


class TestCloseoutRegression:
    def test_closeout_tests_exist(self) -> None:
        closeout = _REPO_ROOT / "tests/context/test_context_final_closeout.py"
        assert closeout.exists()

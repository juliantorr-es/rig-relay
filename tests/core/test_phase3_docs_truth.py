"""Phase 3 docs truth — proves documentation matches implementation status."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestPhase3DocsTruth:
    def test_extraction_plan_reflects_phase3_status(self) -> None:
        doc = (
            _REPO_ROOT
            / "docs"
            / "audits"
            / "agent-loop"
            / "conversation-runtime-extraction-plan.md"
        )
        content = doc.read_text()
        assert "Phase 3" in content, "Extraction plan must mention Phase 3"

    def test_middleware_adapter_is_real(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        source = path.read_text()
        assert "NotImplementedError" not in source, (
            "No production NotImplementedError in adapter"
        )

    def test_context_adapter_no_run_until_complete(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        source = path.read_text()
        # Check that run_until_complete is only in comments/docstrings, not in code
        for line in source.split("\n"):
            stripped = line.strip()
            if "run_until_complete" in stripped and not stripped.startswith((
                "#",
                '"""',
            )):
                if "No run_until_complete" in stripped:
                    continue
                pytest.fail(f"run_until_complete found in code: {stripped[:80]}")

    def test_conversation_runtime_owns_loop(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "conversation_runtime" / "runtime.py"
        source = path.read_text()
        assert "async def execute_turn_loop" in source

    def test_agent_loop_delegates_to_cr(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        source = path.read_text()
        assert "cr.execute_turn_loop(adapter)" in source

    def test_middleware_is_async_in_protocol(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "conversation_runtime" / "models.py"
        source = path.read_text()
        assert "async def middleware_before_turn" in source, (
            "Middleware must be async in the callback protocol"
        )

    def test_context_is_async_in_protocol(self) -> None:
        path = _REPO_ROOT / "rig_relay" / "core" / "conversation_runtime" / "models.py"
        source = path.read_text()
        assert "async def build_context_envelope" in source, (
            "Context build must be async in the callback protocol"
        )

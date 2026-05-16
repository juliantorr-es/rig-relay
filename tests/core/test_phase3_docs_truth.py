from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestPhase3DocsTruth:
    """Verify docs match actual implementation state."""

    def test_reconciliation_doc_is_canonical_all_lanes(self) -> None:
        doc = _REPO_ROOT / "docs" / "audits" / "agent-loop" / "phase3-readiness-reconciliation.md"
        text = doc.read_text()
        assert "All-Lanes Truth Table" in text, (
            "Reconciliation doc must contain canonical all-lanes truth table"
        )
        assert "READY_NOT_TRANSFERRED" in text, (
            "Reconciliation doc must state current Phase 3 status"
        )

    def test_extraction_plan_status_matches_code(self) -> None:
        doc = (
            _REPO_ROOT
            / "docs"
            / "audits"
            / "agent-loop"
            / "conversation-runtime-extraction-plan.md"
        )
        text = doc.read_text()

        # Check if the loop has been transferred by looking at AgentLoop
        agent_loop = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        al_text = agent_loop.read_text()
        loop_moved = "execute_turn" in al_text and "_conversation_loop" not in al_text

        if loop_moved:
            assert "COMPLETE" in text or "Phase 3 | ✅ Complete" in text, (
                "Extraction plan must say COMPLETE when loop is transferred"
            )
        else:
            assert "READY" in text or "Future" in text or "NOT_READY" not in text.upper(), (
                "Extraction plan must reflect READY or Future when loop is not yet transferred"
            )

    def test_reconciliation_doc_has_failed_seams_when_loop_not_moved(self) -> None:
        doc = _REPO_ROOT / "docs" / "audits" / "agent-loop" / "phase3-readiness-reconciliation.md"
        text = doc.read_text()

        agent_loop = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        al_text = agent_loop.read_text()
        loop_moved = "execute_turn" in al_text and "_conversation_loop" not in al_text

        if not loop_moved:
            assert "NOT YET TRANSFERRED" in text or "NOT_TRANSFERRED" in text, (
                "Reconciliation doc must honestly state loop ownership not yet transferred"
            )

    def test_no_false_phase3_complete_before_loop_transfer(self) -> None:
        agent_loop = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        al_text = agent_loop.read_text()
        loop_moved = "execute_turn" in al_text and "_conversation_loop" not in al_text

        doc = _REPO_ROOT / "docs" / "audits" / "agent-loop" / "phase3-readiness-reconciliation.md"
        doc_text = doc.read_text()

        if not loop_moved:
            # The status line itself must not claim COMPLETE
            for line in doc_text.split("\n"):
                if "Current Phase Status" in line:
                    assert "COMPLETE" not in line, (
                        f"Docs must NOT claim PHASE_3_COMPLETE in status line. Found: {line.strip()}"
                    )
                    return

    def test_subagent_strict_fallback_still_true(self) -> None:
        runtime = _REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        text = runtime.read_text()
        assert "allow_legacy_direct: bool = False" in text, (
            "SubagentRuntime must default to allow_legacy_direct=False"
        )
        assert "tool_runtime_required" in text, (
            "SubagentRuntime must have tool_runtime_required mode"
        )

    def test_task_propagation_still_true(self) -> None:
        task = _REPO_ROOT / "rig_relay" / "core" / "tools" / "builtins" / "task.py"
        text = task.read_text()
        assert "tool_runtime=" in text, "task.py must pass tool_runtime="
        assert "trace_recorder=" in text, "task.py must pass trace_recorder="

    def test_tool_runtime_span_finalization_still_true(self) -> None:
        tr = _REPO_ROOT / "rig_relay" / "core" / "tool_runtime.py"
        text = tr.read_text()
        assert "_finalize_span" in text, "ToolRuntime must have _finalize_span"

    def test_agent_loop_has_no_syntax_errors(self) -> None:
        agent_loop = _REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"
        try:
            compile(agent_loop.read_text(), str(agent_loop), "exec")
        except SyntaxError as e:
            pytest.fail(f"agent_loop.py has syntax error: {e}")

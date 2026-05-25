from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.governance_runtime import GovernanceRuntime
from rig_relay.core._agent_init import InitHelpers

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LOOP_PATH = REPO_ROOT / "rig_relay" / "core" / "agent_loop.py"

DELETED_MIXIN_MODULES = frozenset({
    "rig_relay.core._governance",
    "rig_relay.core._llm_call",
    "rig_relay.core._middleware_metadata",
    "rig_relay.core._context_envelope",
    "rig_relay.core._session_lifecycle",
    "rig_relay.core._telemetry",
    "rig_relay.core._tool_response",
})


def _imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


class TestAgentLoopNoMixinInheritance:
    """Architecture contract: AgentLoop must not inherit from any core mixin."""

    def test_agent_loop_bases_are_object_only(self) -> None:
        assert AgentLoop.__bases__ == (object,), (
            f"AgentLoop.__bases__ must be (object,), got {AgentLoop.__bases__}"
        )

    def test_agent_loop_init_uses_composition(self) -> None:
        source = inspect.getsource(AgentLoop.__init__)
        assert "InitHelpers.init_core_managers" in source, (
            "AgentLoop.__init__ must call InitHelpers.init_core_managers"
        )
        assert "self._init_core_managers" not in source, (
            "AgentLoop.__init__ must not call self._init_core_managers"
        )

    def test_no_deleted_mixin_modules_imported(self) -> None:
        agent_loop_imports = _imports_in_file(AGENT_LOOP_PATH)
        violations = [i for i in agent_loop_imports if i in DELETED_MIXIN_MODULES]
        assert not violations, (
            f"agent_loop.py imports deleted mixin modules: {violations}"
        )


class TestAgentLoopGovernanceDelegation:
    """Architecture contract: governance façade delegates to GovernanceRuntime."""

    def test_governance_methods_exist_on_runtime(self) -> None:
        for method_name in (
            "set_tool_permission",
            "is_permission_covered",
            "approve_always",
        ):
            assert hasattr(GovernanceRuntime, method_name), (
                f"GovernanceRuntime missing method: {method_name}"
            )

    def test_governance_facade_delegates_to_runtime(self) -> None:
        source = inspect.getsource(AgentLoop.set_tool_permission)
        assert "self._governance_runtime.set_tool_permission" in source, (
            "AgentLoop.set_tool_permission must delegate to self._governance_runtime"
        )

        source = inspect.getsource(AgentLoop.approve_always)
        assert "self._governance_runtime.approve_always" in source, (
            "AgentLoop.approve_always must delegate to self._governance_runtime"
        )


class TestModelRuntimeInvariant:
    """Architecture contract: model/middleware must not bypass their runtime owner."""

    def test_chat_streaming_has_no_llmcalls_fallback(self) -> None:
        source = inspect.getsource(AgentLoop._chat_streaming)
        assert "LLMCallMixin" not in source, (
            "_chat_streaming must not reference LLMCallMixin"
        )

    def test_chat_streaming_raises_state_error(self) -> None:
        source = inspect.getsource(AgentLoop._chat_streaming)
        assert "AgentLoopStateError" in source, (
            "_chat_streaming must raise AgentLoopStateError on missing runtime"
        )

    def test_setup_middleware_no_mixin_fallback(self) -> None:
        source = inspect.getsource(AgentLoop._setup_middleware)
        assert "MiddlewareMetadataMixin" not in source, (
            "_setup_middleware must not reference MiddlewareMetadataMixin"
        )
        assert "_require_model_runtime" in source, (
            "_setup_middleware must delegate through _require_model_runtime"
        )

    def test_require_model_runtime_exists(self) -> None:
        assert hasattr(AgentLoop, "_require_model_runtime"), (
            "AgentLoop must have _require_model_runtime helper"
        )

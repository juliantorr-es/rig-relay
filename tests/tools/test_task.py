from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import build_test_vibe_config
from tests.mock.utils import collect_result
from vibe.core.agents.manager import AgentManager
from vibe.core.agents.models import BUILTIN_AGENTS, AgentType
from vibe.core.config import ProviderConfig
from vibe.core.paths._vibe_home import SESSIONS_ROOT
from vibe.core.tools.base import BaseToolState, InvokeContext, ToolError, ToolPermission
from vibe.core.tools.builtins.task import (
    Task,
    TaskArgs,
    TaskProviderOptions,
    TaskResult,
    TaskToolConfig,
)
from vibe.core.tools.permissions import PermissionContext
from vibe.core.types import AssistantEvent, LLMMessage, Role


@pytest.fixture
def task_tool() -> Task:
    return Task(config_getter=lambda: TaskToolConfig(), state=BaseToolState())


class TestTaskArgs:
    def test_default_agent_is_explore(self) -> None:
        args = TaskArgs(task="do something")
        assert args.agent == "explore"

    def test_custom_values(self) -> None:
        args = TaskArgs(task="do something", agent="explore")
        assert args.task == "do something"
        assert args.agent == "explore"


class TestTaskToolValidation:
    @pytest.fixture
    def ctx(self) -> InvokeContext:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        manager = AgentManager(lambda: config)
        return InvokeContext(tool_call_id="test-call-id", agent_manager=manager)

    @pytest.mark.asyncio
    async def test_rejects_primary_agent(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        args = TaskArgs(task="do something", agent="default")

        with pytest.raises(ToolError) as exc_info:
            await collect_result(task_tool.run(args, ctx))

        assert "agent" in str(exc_info.value).lower()
        assert "subagent" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_agent(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        args = TaskArgs(task="do something", agent="nonexistent")

        with pytest.raises(ToolError) as exc_info:
            await collect_result(task_tool.run(args, ctx))

        assert "Unknown agent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_requires_agent_manager_in_context(self, task_tool: Task) -> None:
        args = TaskArgs(task="do something", agent="explore")
        ctx = InvokeContext(tool_call_id="test-call-id")  # No agent_manager

        with pytest.raises(ToolError) as exc_info:
            await collect_result(task_tool.run(args, ctx))

        assert "agent_manager" in str(exc_info.value).lower()

    def test_explore_agent_is_valid_subagent(self) -> None:
        agent = BUILTIN_AGENTS["explore"]
        assert agent.agent_type == AgentType.SUBAGENT


class TestTaskToolResolvePermission:
    def test_explore_allowed_by_default(self, task_tool: Task) -> None:
        args = TaskArgs(task="do something", agent="explore")
        result = task_tool.resolve_permission(args)
        assert isinstance(result, PermissionContext)
        assert result.permission is ToolPermission.ALWAYS

    def test_unknown_agent_returns_none(self, task_tool: Task) -> None:
        args = TaskArgs(task="do something", agent="custom_agent")
        result = task_tool.resolve_permission(args)
        assert result is None

    def test_denylist_takes_precedence(self) -> None:
        config = TaskToolConfig(allowlist=["explore"], denylist=["explore"])
        tool = Task(config_getter=lambda: config, state=BaseToolState())
        args = TaskArgs(task="do something", agent="explore")
        result = tool.resolve_permission(args)
        assert isinstance(result, PermissionContext)
        assert result.permission is ToolPermission.NEVER

    def test_glob_pattern_in_allowlist(self) -> None:
        config = TaskToolConfig(allowlist=["exp*"])
        tool = Task(config_getter=lambda: config, state=BaseToolState())
        args = TaskArgs(task="do something", agent="explore")
        result = tool.resolve_permission(args)
        assert isinstance(result, PermissionContext)
        assert result.permission is ToolPermission.ALWAYS

    def test_glob_pattern_in_denylist(self) -> None:
        config = TaskToolConfig(denylist=["danger*"])
        tool = Task(config_getter=lambda: config, state=BaseToolState())
        args = TaskArgs(task="do something", agent="dangerous_agent")
        result = tool.resolve_permission(args)
        assert isinstance(result, PermissionContext)
        assert result.permission is ToolPermission.NEVER

    def test_empty_lists_returns_none(self) -> None:
        config = TaskToolConfig(allowlist=[], denylist=[])
        tool = Task(config_getter=lambda: config, state=BaseToolState())
        args = TaskArgs(task="do something", agent="explore")
        result = tool.resolve_permission(args)
        assert result is None

    def test_default_config_has_explore_in_allowlist(self) -> None:
        config = TaskToolConfig()
        assert "explore" in config.allowlist


class TestTaskToolExecution:
    @pytest.fixture
    def ctx(self) -> InvokeContext:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        manager = AgentManager(lambda: config)
        return InvokeContext(tool_call_id="test-call-id", agent_manager=manager)

    @pytest.mark.asyncio
    async def test_happy_path_returns_subagent_response(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        """Test that task tool successfully runs a subagent and returns its response."""
        mock_messages = [
            LLMMessage(role=Role.system, content="system"),
            LLMMessage(role=Role.user, content="task"),
            LLMMessage(role=Role.assistant, content="response 1"),
            LLMMessage(role=Role.assistant, content="response 2"),
        ]

        async def mock_act(task: str):
            yield AssistantEvent(content="Hello from subagent!")
            yield AssistantEvent(content=" More content.")

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.return_value = mock_agent_loop

            args = TaskArgs(task="explore the codebase", agent="explore")
            result = await collect_result(task_tool.run(args, ctx))

            assert isinstance(result, TaskResult)
            assert result.response == "Hello from subagent! More content."
            assert result.turns_used == 2  # 2 assistant messages in mock_messages
            assert result.completed is True
            assert result.provider is not None
            assert result.model is not None
            assert result.task_result_sha256 is not None

    @pytest.mark.asyncio
    async def test_deepseek_thinking_sets_provider_extra_body(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        mock_messages = [LLMMessage(role=Role.system, content="system")]

        async def mock_act(task: str):
            yield AssistantEvent(content="Done")

        captured_provider = {}

        def _capture_provider(provider: ProviderConfig) -> None:
            captured_provider["provider"] = provider

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.side_effect = lambda **kwargs: (
                _capture_provider(kwargs["config"].get_active_provider())
                or mock_agent_loop
            )

            args = TaskArgs(
                task="analyze",
                agent="explore",
                provider_options=TaskProviderOptions(
                    provider="deepseek", thinking_enabled=True, reasoning_effort="high"
                ),
            )
            result = await collect_result(task_tool.run(args, ctx))

            assert isinstance(result, TaskResult)
            assert result.completed is True
            provider = captured_provider["provider"]
            assert provider.name == "deepseek"
            assert provider.extra_body == {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            }
            assert result.thinking_requested is True
            assert result.thinking_enabled is True
            assert result.reasoning_effort == "high"
            assert result.provider == "deepseek"
            assert captured_provider["provider"] is not None

    @pytest.mark.asyncio
    async def test_deepseek_thinking_does_not_mutate_shared_provider_config(
        self, task_tool: Task, ctx: InvokeContext, tmp_path: Path
    ) -> None:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        original_provider = config.get_active_provider()
        assert original_provider.extra_body == {}

        session_dir = tmp_path / "session"
        child_dir = session_dir / "agents" / "child-session"
        child_dir.mkdir(parents=True)
        (child_dir / "manifest.json").write_text("{}", encoding="utf-8")

        async def mock_act(task: str):
            yield AssistantEvent(content="Done")

        with patch(
            "vibe.core.tools.builtins.task.VibeConfig.load", return_value=config
        ):
            with patch(
                "vibe.core.tools.builtins.task.AgentLoop"
            ) as mock_agent_loop_class:
                mock_agent_loop = MagicMock()
                mock_agent_loop.act = mock_act
                mock_agent_loop.messages = [
                    LLMMessage(role=Role.system, content="system")
                ]
                mock_agent_loop.set_approval_callback = MagicMock()
                mock_agent_loop.session_id = "child-session"
                mock_agent_loop.session_logger.session_dir = child_dir
                mock_agent_loop_class.return_value = mock_agent_loop

                args = TaskArgs(
                    task="analyze",
                    agent="explore",
                    provider_options=TaskProviderOptions(
                        provider="deepseek",
                        thinking_enabled=True,
                        reasoning_effort="high",
                    ),
                )
                test_ctx = InvokeContext(
                    tool_call_id="test-call-id",
                    agent_manager=ctx.agent_manager,
                    session_dir=session_dir,
                    parent_turn_id="parent-turn-1",
                )
                result = await collect_result(task_tool.run(args, test_ctx))

        assert isinstance(result, TaskResult)
        assert original_provider.extra_body == {}
        assert config.get_active_provider().extra_body == {}

    @pytest.mark.asyncio
    async def test_thinking_request_against_unsupported_provider_returns_warning(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        args = TaskArgs(
            task="analyze",
            agent="explore",
            provider_options=TaskProviderOptions(
                provider="mistral", thinking_enabled=True
            ),
        )

        result = await collect_result(task_tool.run(args, ctx))

        assert isinstance(result, TaskResult)
        assert result.completed is False
        assert result.turns_used == 0
        assert result.warnings
        assert "unsupported provider" in result.warnings[0].lower()
        assert result.thinking_requested is True
        assert result.thinking_enabled is None

    @pytest.mark.asyncio
    async def test_task_emits_task_session_link_artifact(
        self, task_tool: Task, ctx: InvokeContext, tmp_path: Path
    ) -> None:
        manager = ctx.agent_manager
        assert manager is not None
        session_dir = tmp_path / "session"
        child_dir = session_dir / "agents" / "child-session"
        child_dir.mkdir(parents=True)
        (child_dir / "manifest.json").write_text("{}", encoding="utf-8")

        async def mock_act(task: str):
            yield AssistantEvent(content="Answer")

        with patch(
            "vibe.core.tools.builtins.task.VibeConfig.load",
            return_value=manager.config,
        ):
            with patch(
                "vibe.core.tools.builtins.task.AgentLoop"
            ) as mock_agent_loop_class:
                mock_agent_loop = MagicMock()
                mock_agent_loop.act = mock_act
                mock_agent_loop.messages = [
                    LLMMessage(role=Role.system, content="system")
                ]
                mock_agent_loop.set_approval_callback = MagicMock()
                mock_agent_loop.session_id = "child-session"
                mock_agent_loop.session_logger.session_dir = child_dir
                mock_agent_loop_class.return_value = mock_agent_loop

                args = TaskArgs(task="analyze", agent="explore")
                test_ctx = InvokeContext(
                    tool_call_id="test-call-id",
                    agent_manager=manager,
                    session_dir=session_dir,
                    parent_turn_id="parent-turn-1",
                )
                result = await collect_result(task_tool.run(args, test_ctx))

        assert isinstance(result, TaskResult)
        artifact_dir = (
            SESSIONS_ROOT.path / session_dir.name / "artifacts" / "tool-results"
        )
        artifact_files = sorted(artifact_dir.glob("*.json"))
        assert artifact_files
        payload = json.loads(artifact_files[0].read_text(encoding="utf-8"))
        assert payload["artifact_kind"] == "task_session_link"
        assert payload["payload"]["parent_turn_id"] == "parent-turn-1"
        assert payload["payload"]["child_session_id"] == "child-session"
        assert payload["payload"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_non_thinking_deepseek_path_remains_available(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        mock_messages = [LLMMessage(role=Role.system, content="system")]

        async def mock_act(task: str):
            yield AssistantEvent(content="Answer")

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.return_value = mock_agent_loop

            args = TaskArgs(
                task="analyze",
                agent="explore",
                provider_options=TaskProviderOptions(provider="deepseek"),
            )
            result = await collect_result(task_tool.run(args, ctx))

            assert isinstance(result, TaskResult)
            assert result.completed is True
            assert result.thinking_requested is False
            assert result.thinking_enabled is False

    def test_task_result_hash_is_deterministic(self, task_tool: Task) -> None:
        first = TaskResult(response="x", turns_used=1, completed=True)
        second = TaskResult(response="x", turns_used=1, completed=True)
        assert task_tool._task_result_sha256(first) == task_tool._task_result_sha256(
            second
        )

    @pytest.mark.asyncio
    async def test_handles_stopped_by_middleware(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        """Test that task tool reports incomplete when stopped by middleware."""
        mock_messages = [
            LLMMessage(role=Role.system, content="system"),
            LLMMessage(role=Role.assistant, content="partial"),
        ]

        async def mock_act(task: str):
            yield AssistantEvent(content="Partial response", stopped_by_middleware=True)

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.return_value = mock_agent_loop

            args = TaskArgs(task="do something", agent="explore")
            result = await collect_result(task_tool.run(args, ctx))

            assert isinstance(result, TaskResult)
            assert result.completed is False

    @pytest.mark.asyncio
    async def test_handles_subagent_exception(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        """Test that task tool gracefully handles exceptions from subagent."""
        mock_messages = [LLMMessage(role=Role.system, content="system")]

        async def mock_act(task: str):
            yield AssistantEvent(content="Starting...")
            raise RuntimeError("Simulated error")

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.return_value = mock_agent_loop

            args = TaskArgs(task="do something", agent="explore")
            result = await collect_result(task_tool.run(args, ctx))

            assert isinstance(result, TaskResult)
            assert result.completed is False
            assert "Simulated error" in result.response

from __future__ import annotations

import asyncio
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
    TaskFleetSpec,
    TaskProviderOptions,
    TaskResult,
    TaskScope,
    TaskSpec,
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
        assert args.task_text == "do something"

    def test_custom_values(self) -> None:
        args = TaskArgs(task="do something", agent="explore")
        assert args.task == "do something"
        assert args.agent == "explore"

    def test_structured_task_spec_sets_task_text(self) -> None:
        spec = TaskSpec(task_id="task-1", task="inspect", agent_profile="explore")
        args = TaskArgs(task_spec=spec)
        assert args.task_text == "inspect"
        assert args.task_spec is spec


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
            "vibe.core.tools.builtins.task.VibeConfig.load", return_value=manager.config
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

        coordination_events = (
            Path.cwd() / ".build" / "rig-relay" / "coordination" / "events.jsonl"
        )
        events = [
            json.loads(line)
            for line in coordination_events.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [event["event_name"] for event in events] == [
            "coord.task.claimed",
            "coord.artifact.published",
        ]

    @pytest.mark.asyncio
    async def test_structured_task_spec_uses_agent_profile_and_scope(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        mock_messages = [LLMMessage(role=Role.system, content="system")]

        async def mock_act(task: str):
            yield AssistantEvent(content="Answer")

        captured = {}

        def _capture_provider(provider: ProviderConfig) -> None:
            captured["provider"] = provider

        with patch("vibe.core.tools.builtins.task.AgentLoop") as mock_agent_loop_class:
            mock_agent_loop = MagicMock()
            mock_agent_loop.act = mock_act
            mock_agent_loop.messages = mock_messages
            mock_agent_loop.set_approval_callback = MagicMock()
            mock_agent_loop_class.side_effect = lambda **kwargs: (
                _capture_provider(kwargs["config"].get_active_provider())
                or mock_agent_loop
            )

            spec = TaskSpec(
                task_id="audit-1",
                task="inspect repo",
                agent_profile="explore",
                intent="audit",
                scope=TaskScope(
                    allowed_paths=["vibe/core/tools/builtins/task.py"],
                    allow_write=False,
                    allow_bash=False,
                ),
            )
            result = await collect_result(task_tool.run(TaskArgs(task_spec=spec), ctx))

        assert isinstance(result, TaskResult)
        assert captured["provider"].extra_body == {}

    @pytest.mark.asyncio
    async def test_fleet_spec_returns_read_only_validation_packet(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        spec = TaskFleetSpec(
            tasks=[
                TaskSpec(
                    task_id="a",
                    task="inspect a",
                    scope=TaskScope(allowed_paths=["vibe/core/tools/builtins/task.py"]),
                ),
                TaskSpec(
                    task_id="b",
                    task="inspect b",
                    scope=TaskScope(allowed_paths=["vibe/core/tools/builtins/task.py"]),
                ),
            ]
        )

        result = await collect_result(task_tool.run(TaskArgs(fleet_spec=spec), ctx))

        assert isinstance(result, TaskResult)
        payload = json.loads(result.response)
        assert payload["tasks"] == 2
        assert payload["dependencies"] == 0
        assert payload["overlapping_path_groups"]

    @pytest.mark.asyncio
    async def test_fleet_spec_runs_non_overlapping_tasks_and_returns_report(
        self, task_tool: Task, ctx: InvokeContext, tmp_path: Path
    ) -> None:
        manager = ctx.agent_manager
        assert manager is not None
        session_dir = tmp_path / "session"
        child_a_dir = session_dir / "agents" / "child-a"
        child_b_dir = session_dir / "agents" / "child-b"
        child_a_dir.mkdir(parents=True)
        child_b_dir.mkdir(parents=True)
        (child_a_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (child_b_dir / "manifest.json").write_text("{}", encoding="utf-8")

        async def act_a(task: str):
            yield AssistantEvent(content="A done")

        async def act_b(task: str):
            yield AssistantEvent(content="B done")

        with patch(
            "vibe.core.tools.builtins.task.VibeConfig.load", return_value=manager.config
        ):
            with patch(
                "vibe.core.tools.builtins.task.AgentLoop"
            ) as mock_agent_loop_class:
                mock_agent_a = MagicMock()
                mock_agent_a.act = act_a
                mock_agent_a.messages = [LLMMessage(role=Role.system, content="system")]
                mock_agent_a.set_approval_callback = MagicMock()
                mock_agent_a.session_id = "child-a"
                mock_agent_a.session_logger.session_dir = child_a_dir

                mock_agent_b = MagicMock()
                mock_agent_b.act = act_b
                mock_agent_b.messages = [LLMMessage(role=Role.system, content="system")]
                mock_agent_b.set_approval_callback = MagicMock()
                mock_agent_b.session_id = "child-b"
                mock_agent_b.session_logger.session_dir = child_b_dir

                mock_agent_loop_class.side_effect = [mock_agent_a, mock_agent_b]

                spec = TaskFleetSpec(
                    tasks=[
                        TaskSpec(
                            task_id="a",
                            task="inspect a",
                            scope=TaskScope(
                                allowed_paths=["vibe/core/tools/builtins/task.py"]
                            ),
                        ),
                        TaskSpec(
                            task_id="b",
                            task="inspect b",
                            scope=TaskScope(
                                allowed_paths=["vibe/core/tools/builtins/write_file.py"]
                            ),
                        ),
                    ]
                )
                result = await collect_result(
                    task_tool.run(
                        TaskArgs(fleet_spec=spec),
                        InvokeContext(
                            tool_call_id="fleet-call-id",
                            agent_manager=manager,
                            session_dir=session_dir,
                            parent_turn_id="parent-turn-1",
                        ),
                    )
                )

        assert isinstance(result, TaskResult)
        payload = json.loads(result.response)
        assert payload["status"] == "completed"
        assert payload["children"]
        assert [child["task_id"] for child in payload["children"]] == ["a", "b"]
        assert payload["children"][0]["child_session_id"] == "child-a"
        assert payload["children"][1]["child_session_id"] == "child-b"
        assert payload["scheduled_groups"] == [["a", "b"]]

    @pytest.mark.asyncio
    async def test_fleet_spec_runs_non_overlapping_tasks_in_parallel(
        self, task_tool: Task, ctx: InvokeContext, tmp_path: Path
    ) -> None:
        manager = ctx.agent_manager
        assert manager is not None
        session_dir = tmp_path / "session"
        child_a_dir = session_dir / "agents" / "child-a"
        child_b_dir = session_dir / "agents" / "child-b"
        child_a_dir.mkdir(parents=True)
        child_b_dir.mkdir(parents=True)
        (child_a_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (child_b_dir / "manifest.json").write_text("{}", encoding="utf-8")

        started: list[str] = []
        release = asyncio.Event()

        async def act(task: str):
            started.append(task)
            if len(started) == 2:
                release.set()
            await release.wait()
            yield AssistantEvent(content=f"{task} done")

        with patch(
            "vibe.core.tools.builtins.task.VibeConfig.load", return_value=manager.config
        ):
            with patch(
                "vibe.core.tools.builtins.task.AgentLoop"
            ) as mock_agent_loop_class:
                mock_agent_a = MagicMock()
                mock_agent_a.act = act
                mock_agent_a.messages = [LLMMessage(role=Role.system, content="system")]
                mock_agent_a.set_approval_callback = MagicMock()
                mock_agent_a.session_id = "child-a"
                mock_agent_a.session_logger.session_dir = child_a_dir

                mock_agent_b = MagicMock()
                mock_agent_b.act = act
                mock_agent_b.messages = [LLMMessage(role=Role.system, content="system")]
                mock_agent_b.set_approval_callback = MagicMock()
                mock_agent_b.session_id = "child-b"
                mock_agent_b.session_logger.session_dir = child_b_dir

                mock_agent_loop_class.side_effect = [mock_agent_a, mock_agent_b]

                spec = TaskFleetSpec(
                    tasks=[
                        TaskSpec(
                            task_id="a",
                            task="inspect a",
                            scope=TaskScope(
                                allowed_paths=["vibe/core/tools/builtins/task.py"]
                            ),
                        ),
                        TaskSpec(
                            task_id="b",
                            task="inspect b",
                            scope=TaskScope(
                                allowed_paths=["vibe/core/tools/builtins/write_file.py"]
                            ),
                        ),
                    ]
                )
                result = await asyncio.wait_for(
                    collect_result(
                        task_tool.run(
                            TaskArgs(fleet_spec=spec),
                            InvokeContext(
                                tool_call_id="fleet-call-id",
                                agent_manager=manager,
                                session_dir=session_dir,
                                parent_turn_id="parent-turn-1",
                            ),
                        )
                    ),
                    timeout=2,
                )

        assert isinstance(result, TaskResult)
        assert len(started) == 2
        payload = json.loads(result.response)
        assert payload["status"] == "completed"

    @pytest.mark.asyncio
    async def test_fleet_spec_refuses_overlapping_paths(
        self, task_tool: Task, ctx: InvokeContext
    ) -> None:
        spec = TaskFleetSpec(
            tasks=[
                TaskSpec(
                    task_id="a",
                    task="inspect a",
                    scope=TaskScope(allowed_paths=["vibe/core/tools/builtins/task.py"]),
                ),
                TaskSpec(
                    task_id="b",
                    task="inspect b",
                    scope=TaskScope(allowed_paths=["vibe/core/tools/builtins/task.py"]),
                ),
            ]
        )

        result = await collect_result(task_tool.run(TaskArgs(fleet_spec=spec), ctx))

        assert isinstance(result, TaskResult)
        payload = json.loads(result.response)
        assert payload["status"] == "refused"
        assert payload["overlapping_path_groups"]
        assert payload["children"] == []

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

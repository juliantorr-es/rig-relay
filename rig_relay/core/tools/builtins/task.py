from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import UTC, datetime
import fnmatch
import hashlib
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.agents.models import AgentType, BuiltinAgentName
from rig_relay.core.config import ModelConfig, SessionLoggingConfig, VibeConfig
from rig_relay.coordination.store import CoordinationStore
from rig_relay.core.telemetry.artifacts import (
    TaskSessionLinkArtifact,
    ToolOutputArtifact,
    ToolOutputArtifactWriter,
)
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.permissions import PermissionContext
from rig_relay.core.tools.ui import (
    ToolCallDisplay,
    ToolResultDisplay,
    ToolUIData,
    ToolUIDataAdapter,
)
from rig_relay.core.types import (
    AssistantEvent,
    Role,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)


class TaskScope(BaseModel):
    allowed_paths: list[str] = Field(default_factory=list)
    dirty_file_policy: Literal["preserve_existing", "allow"] = "preserve_existing"
    allow_write: bool = False
    allow_bash: bool = False


class TaskSpec(BaseModel):
    mode: Literal["delegate"] = "delegate"
    task_id: str
    task: str
    agent_profile: str = "explore"
    intent: str = "explore"
    scope: TaskScope = Field(default_factory=TaskScope)
    provider_options: TaskProviderOptions | None = None
    expected_outputs: list[str] = Field(default_factory=list)


class TaskFleetEdge(BaseModel):
    from_task_id: str
    to_task_id: str


class TaskFleetSpec(BaseModel):
    tasks: list[TaskSpec] = Field(default_factory=list)
    dependencies: list[TaskFleetEdge] = Field(default_factory=list)


class TaskArgs(BaseModel):
    task: str | None = Field(
        default=None, description="The task to delegate to the subagent"
    )
    agent: str = Field(
        default="explore",
        description="Name of the agent profile to use (must be a subagent)",
    )
    task_spec: TaskSpec | None = Field(
        default=None,
        description="Structured delegation packet with mode, scope, and provider policy.",
    )
    fleet_spec: TaskFleetSpec | None = Field(
        default=None,
        description="Structured read-only fleet packet for parallel investigation.",
    )
    provider_options: TaskProviderOptions | None = Field(
        default=None,
        description="Explicit provider/model options for the delegated subagent.",
    )

    @property
    def task_text(self) -> str:
        if self.task_spec is not None:
            return self.task_spec.task
        if self.task is not None:
            return self.task
        raise ToolError("Task text is required")

    @property
    def is_fleet(self) -> bool:
        return self.fleet_spec is not None


class TaskResult(BaseModel):
    response: str = Field(description="The accumulated response from the subagent")
    turns_used: int = Field(description="Number of turns the subagent used")
    completed: bool = Field(description="Whether the task completed normally")
    provider: str | None = None
    model: str | None = None
    thinking_requested: bool = False
    thinking_enabled: bool | None = None
    thinking_type: str | None = None
    reasoning_effort: str | None = None
    tool_access_policy: str | None = None
    result_compression_policy: str | None = None
    timeout_seconds: float | None = None
    task_result_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


class TaskFleetValidationResult(BaseModel):
    tasks: int = 0
    dependencies: int = 0
    overlapping_path_groups: list[list[str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TaskFleetChildResult(BaseModel):
    task_id: str
    agent_profile: str
    child_session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    completed: bool = False
    turns_used: int = 0
    task_result_sha256: str | None = None
    child_artifact_manifest_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


class TaskFleetReport(TaskFleetValidationResult):
    status: Literal["completed", "failed", "refused"] = "completed"
    scheduled_groups: list[list[str]] = Field(default_factory=list)
    children: list[TaskFleetChildResult] = Field(default_factory=list)


class TaskExecutionSummary(BaseModel):
    result: TaskResult
    child_session_dir: str | None = None
    child_artifact_manifest_sha256: str | None = None


class TaskProviderOptions(BaseModel):
    provider: str | None = None
    model: str | None = None
    thinking_enabled: bool | None = None
    thinking_type: Literal["enabled", "disabled"] | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    tool_access_policy: str | None = None
    result_compression_policy: str | None = None


class TaskExecutionPlan(BaseModel):
    provider: str | None = None
    model: str | None = None
    thinking_requested: bool = False
    thinking_enabled: bool | None = None
    thinking_type: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    tool_access_policy: str | None = None
    result_compression_policy: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class TaskToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    allowlist: list[str] = Field(default=[BuiltinAgentName.EXPLORE])


class Task(
    BaseTool[TaskArgs, TaskResult, TaskToolConfig, BaseToolState],
    ToolUIData[TaskArgs, TaskResult],
):
    description: ClassVar[str] = (
        "Delegate a task to a subagent for independent execution. "
        "Useful for exploration, research, or parallel work that doesn't "
        "require user interaction. The subagent runs in-memory and "
        "saves interaction logs."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_PROVIDER
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        args = event.args
        if isinstance(args, TaskArgs):
            task_text = args.task_text
            agent_name = args.task_spec.agent_profile if args.task_spec else args.agent
            return ToolCallDisplay(summary=f"Running {agent_name} agent: {task_text}")
        return ToolCallDisplay(summary="Running subagent")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        result = event.result
        if isinstance(result, TaskResult):
            turn_word = "turn" if result.turns_used == 1 else "turns"
            if not result.completed:
                return ToolResultDisplay(
                    success=False,
                    message=f"Agent interrupted after {result.turns_used} {turn_word}",
                )
            return ToolResultDisplay(
                success=True,
                message=f"Agent completed in {result.turns_used} {turn_word}",
            )
        return ToolResultDisplay(success=True, message="Agent completed")

    @classmethod
    def get_status_text(cls) -> str:
        return "Running subagent"

    @staticmethod
    def _task_result_sha256(result: TaskResult) -> str:
        return Task._sha256_payload(result.model_dump(exclude_none=True))

    @staticmethod
    def _coordination_store(ctx: InvokeContext) -> CoordinationStore | None:
        if ctx.session_dir is None:
            return None
        return CoordinationStore(Path.cwd() / ".build" / "rig-relay" / "coordination")

    @staticmethod
    def _sha256_payload(payload: dict[str, Any]) -> str:
        return (
            "sha256:"
            + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()
        )

    @staticmethod
    def _prompt_sha256(prompt: str) -> str:
        return Task._sha256_payload({"prompt": prompt})

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        try:
            if not path.is_file():
                return None
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return None

    @staticmethod
    def _build_call_config(config: VibeConfig, plan: TaskExecutionPlan) -> VibeConfig:
        call_config = config.model_copy(deep=True)
        if plan.model:
            call_config.active_model = plan.model
        if plan.extra_body:
            provider = call_config.get_active_provider().with_overrides(
                extra_body=plan.extra_body
            )
            for index, candidate in enumerate(call_config.providers):
                if candidate.name == provider.name:
                    call_config.providers[index] = provider
                    break
        return call_config

    @staticmethod
    def _build_task_spec(args: TaskArgs) -> TaskSpec | None:
        if args.task_spec is None:
            return None
        if args.task is not None and args.task != args.task_spec.task:
            raise ToolError("task and task_spec.task must match when both are provided")
        return args.task_spec

    @staticmethod
    def _resolve_delegate_inputs(
        args: TaskArgs,
    ) -> tuple[TaskSpec | None, TaskProviderOptions | None, str]:
        task_spec = Task._build_task_spec(args)
        provider_options = (
            task_spec.provider_options
            if task_spec is not None
            else args.provider_options
        )
        agent_profile_name = task_spec.agent_profile if task_spec else args.agent
        return task_spec, provider_options, agent_profile_name

    @staticmethod
    def _path_groups(tasks: list[TaskSpec]) -> list[list[str]]:
        groups: list[list[str]] = []
        for task in tasks:
            if task.scope.allowed_paths:
                groups.append(
                    sorted({Path(path).as_posix() for path in task.scope.allowed_paths})
                )
        return groups

    @staticmethod
    def _detect_path_overlaps(path_groups: list[list[str]]) -> list[list[str]]:
        overlaps: list[list[str]] = []
        for index, group in enumerate(path_groups):
            group_set = set(group)
            for other in path_groups[index + 1 :]:
                if group_set & set(other):
                    merged = sorted(group_set | set(other))
                    if merged not in overlaps:
                        overlaps.append(merged)
        overlaps.sort(key=lambda item: (len(item), item))
        return overlaps

    @staticmethod
    def _validate_fleet_spec(fleet_spec: TaskFleetSpec) -> TaskFleetValidationResult:
        path_groups = Task._path_groups(fleet_spec.tasks)
        return TaskFleetValidationResult(
            tasks=len(fleet_spec.tasks),
            dependencies=len(fleet_spec.dependencies),
            overlapping_path_groups=Task._detect_path_overlaps(path_groups),
        )

    @staticmethod
    def _fleet_task_order(fleet_spec: TaskFleetSpec) -> dict[str, int]:
        return {task.task_id: index for index, task in enumerate(fleet_spec.tasks)}

    @staticmethod
    def _validate_fleet_scope(fleet_spec: TaskFleetSpec) -> list[str]:
        warnings: list[str] = []
        for task in fleet_spec.tasks:
            if task.scope.allow_write:
                warnings.append(f"Task '{task.task_id}' requests writes in fleet mode.")
            if task.scope.allow_bash:
                warnings.append(f"Task '{task.task_id}' requests bash in fleet mode.")
        return warnings

    @staticmethod
    def _validate_fleet_dependencies(
        fleet_spec: TaskFleetSpec, task_order: dict[str, int]
    ) -> tuple[list[list[str]], list[str]]:
        adjacency: dict[str, set[str]] = {
            task.task_id: set() for task in fleet_spec.tasks
        }
        indegree: dict[str, int] = {task.task_id: 0 for task in fleet_spec.tasks}
        warnings: list[str] = []

        for edge in fleet_spec.dependencies:
            if edge.from_task_id not in adjacency:
                warnings.append(
                    f"Dependency references unknown task '{edge.from_task_id}'."
                )
                continue
            if edge.to_task_id not in adjacency:
                warnings.append(
                    f"Dependency references unknown task '{edge.to_task_id}'."
                )
                continue
            if edge.to_task_id in adjacency[edge.from_task_id]:
                continue
            adjacency[edge.from_task_id].add(edge.to_task_id)
            indegree[edge.to_task_id] += 1

        ready = sorted(
            [task_id for task_id, degree in indegree.items() if degree == 0],
            key=task_order.__getitem__,
        )
        scheduled_groups: list[list[str]] = []
        scheduled_count = 0

        while ready:
            scheduled_groups.append(list(ready))
            scheduled_count += len(ready)
            next_ready: set[str] = set()
            for task_id in ready:
                for dependent in adjacency[task_id]:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        next_ready.add(dependent)
            ready = sorted(next_ready, key=task_order.__getitem__)

        if scheduled_count != len(fleet_spec.tasks):
            warnings.append("Fleet dependency graph contains a cycle.")

        return scheduled_groups, warnings

    @staticmethod
    def _task_fleet_report(
        *,
        fleet_result: TaskFleetValidationResult,
        status: Literal["completed", "failed", "refused"],
        scheduled_groups: list[list[str]] | None = None,
        children: list[TaskFleetChildResult] | None = None,
    ) -> TaskFleetReport:
        return TaskFleetReport(
            tasks=fleet_result.tasks,
            dependencies=fleet_result.dependencies,
            overlapping_path_groups=fleet_result.overlapping_path_groups,
            warnings=fleet_result.warnings,
            status=status,
            scheduled_groups=scheduled_groups or [],
            children=children or [],
        )

    @staticmethod
    def _build_fleet_child_result(
        *,
        task_spec: TaskSpec,
        result: TaskResult,
        child_session_dir: Path | None,
        child_artifact_manifest_sha256: str | None,
    ) -> TaskFleetChildResult:
        return TaskFleetChildResult(
            task_id=task_spec.task_id,
            agent_profile=task_spec.agent_profile,
            child_session_id=child_session_dir.name if child_session_dir else None,
            provider=result.provider,
            model=result.model,
            completed=result.completed,
            turns_used=result.turns_used,
            task_result_sha256=result.task_result_sha256,
            child_artifact_manifest_sha256=child_artifact_manifest_sha256,
            warnings=result.warnings,
        )

    @staticmethod
    def _ensure_subagent_agent(agent_manager: Any, agent_profile_name: str) -> None:
        try:
            agent = agent_manager.get_agent(agent_profile_name)
        except ValueError as e:
            raise ToolError(f"Unknown agent: {agent_profile_name}") from e
        if agent.agent_type != AgentType.SUBAGENT:
            raise ToolError(
                f"Agent '{agent_profile_name}' is a {agent.agent_type.value} agent. "
                "Only subagents can be used with the task tool. "
                "This is a security constraint to prevent recursive spawning."
            )

    async def _collect_subagent_output(
        self,
        *,
        ctx: InvokeContext,
        args: TaskArgs,
        agent_manager: Any,
        plan: TaskExecutionPlan,
        agent_profile_name: str,
        prompt_text: str,
        emit_tool_events: bool,
    ) -> tuple[TaskExecutionSummary, list[ToolStreamEvent]]:
        self._ensure_subagent_agent(agent_manager, agent_profile_name)
        subagent_loop = self._build_subagent_loop(
            ctx=ctx,
            args=args,
            agent_manager=agent_manager,
            plan=plan,
            agent_profile_name=agent_profile_name,
        )

        task_text = prompt_text
        if ctx.scratchpad_dir:
            task_text = (
                f"Scratchpad directory: {ctx.scratchpad_dir}\n"
                "You can read and write files here without permission prompts.\n\n"
                f"{prompt_text}"
            )

        accumulated_response: list[str] = []
        completed = True
        tool_events: list[ToolStreamEvent] = []
        try:
            async with aclosing(subagent_loop.act(task_text)) as events:
                async for event in events:
                    if isinstance(event, AssistantEvent) and event.content:
                        accumulated_response.append(event.content)
                        if event.stopped_by_middleware:
                            completed = False
                    elif isinstance(event, ToolResultEvent):
                        if event.skipped:
                            completed = False
                        elif emit_tool_events and event.result and event.tool_class:
                            adapter = ToolUIDataAdapter(event.tool_class)
                            display = adapter.get_result_display(event)
                            tool_events.append(
                                ToolStreamEvent(
                                    tool_name=self.get_name(),
                                    message=f"{event.tool_name}: {display.message}",
                                    tool_call_id=ctx.tool_call_id,
                                )
                            )
        except Exception as e:
            completed = False
            accumulated_response.append(f"\n[Subagent error: {e}]")

        turns_used = sum(msg.role == Role.assistant for msg in subagent_loop.messages)
        result = self._build_task_result(
            response="".join(accumulated_response),
            turns_used=turns_used,
            completed=completed,
            plan=plan,
        )
        child_session_dir = subagent_loop.session_logger.session_dir
        child_session_path = (
            child_session_dir if isinstance(child_session_dir, Path) else None
        )
        return (
            TaskExecutionSummary(
                result=result,
                child_session_dir=(
                    child_session_path.name if child_session_path is not None else None
                ),
                child_artifact_manifest_sha256=(
                    self._file_sha256(child_session_path / "manifest.json")
                    if child_session_path is not None
                    else None
                ),
            ),
            tool_events,
        )

    async def _execute_subagent_task(
        self,
        *,
        args: TaskArgs,
        ctx: InvokeContext,
        agent_manager: Any,
        plan: TaskExecutionPlan,
        agent_profile_name: str,
        task_id: str,
        task_spec: TaskSpec | None,
        prompt_text: str,
        emit_tool_events: bool,
    ) -> AsyncGenerator[ToolStreamEvent | TaskExecutionSummary, None]:
        store = self._coordination_store(ctx)
        session_id = ctx.session_dir.name if ctx.session_dir is not None else None
        reserved_paths = list(task_spec.scope.allowed_paths) if task_spec else []
        if store is not None and session_id is not None:
            store.claim_task(
                session_id=session_id,
                task_id=task_id,
                claim_kind="delegate" if task_spec is None else "fleet_child",
                ttl_seconds=300,
                scope={"allowed_paths": reserved_paths},
            )
            if reserved_paths:
                store.reserve_paths(
                    session_id=session_id,
                    task_id=task_id,
                    mode="write"
                    if task_spec and task_spec.scope.allow_write
                    else "read",
                    paths=reserved_paths,
                    ttl_seconds=300,
                )

        try:
            summary, tool_events = await self._collect_subagent_output(
                ctx=ctx,
                args=args,
                agent_manager=agent_manager,
                plan=plan,
                agent_profile_name=agent_profile_name,
                prompt_text=prompt_text,
                emit_tool_events=emit_tool_events,
            )
            artifact = self._write_task_session_link_artifact(
                ctx=ctx,
                args=args,
                prompt_text=prompt_text,
                plan=plan,
                result=summary.result,
                task_spec=task_spec,
                child_session_dir=(
                    Path(summary.child_session_dir)
                    if summary.child_session_dir is not None
                    else None
                ),
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            if artifact is not None and store is not None and session_id is not None:
                store.publish_artifact(
                    session_id=session_id,
                    task_id=task_id,
                    artifact_kind="task_session_link",
                    artifact_uri=artifact.path,
                    artifact_sha256=artifact.artifact_record_sha256
                    or artifact.payload_sha256,
                    schema_id="rig.relay.artifact.task_session_link.v1",
                )
            for event in tool_events:
                yield event
            yield summary
        finally:
            if store is not None and session_id is not None and reserved_paths:
                store.release_paths(
                    session_id=session_id, task_id=task_id, paths=reserved_paths
                )

    async def _run_fleet_child(
        self,
        *,
        args: TaskArgs,
        ctx: InvokeContext,
        agent_manager: Any,
        task_spec: TaskSpec,
    ) -> TaskFleetChildResult:
        plan = self._build_execution_plan(
            agent_manager.config, task_spec.provider_options
        )
        if plan.warnings:
            result = self._build_task_result(
                response="", turns_used=0, completed=False, plan=plan
            )
            return self._build_fleet_child_result(
                task_spec=task_spec,
                result=result,
                child_session_dir=None,
                child_artifact_manifest_sha256=None,
            )
        summary: TaskExecutionSummary | None = None
        async for item in self._execute_subagent_task(
            args=args,
            ctx=ctx,
            agent_manager=agent_manager,
            plan=plan,
            agent_profile_name=task_spec.agent_profile,
            task_id=task_spec.task_id,
            task_spec=task_spec,
            prompt_text=task_spec.task,
            emit_tool_events=False,
        ):
            if isinstance(item, TaskExecutionSummary):
                summary = item
        assert summary is not None
        return self._build_fleet_child_result(
            task_spec=task_spec,
            result=summary.result,
            child_session_dir=(
                Path(summary.child_session_dir)
                if summary.child_session_dir is not None
                else None
            ),
            child_artifact_manifest_sha256=summary.child_artifact_manifest_sha256,
        )

    async def _run_fleet_flow(
        self, args: TaskArgs, ctx: InvokeContext, agent_manager: Any
    ) -> AsyncGenerator[TaskFleetReport, None]:
        fleet_spec = args.fleet_spec
        assert fleet_spec is not None
        validation = self._validate_fleet_spec(fleet_spec)
        warnings = list(validation.warnings)
        warnings.extend(self._validate_fleet_scope(fleet_spec))
        task_order = self._fleet_task_order(fleet_spec)
        scheduled_groups: list[list[str]] = []
        children: list[TaskFleetChildResult] = []

        if validation.overlapping_path_groups:
            yield self._task_fleet_report(
                fleet_result=validation, status="refused", children=[]
            )
            return

        scheduled_groups, dependency_warnings = self._validate_fleet_dependencies(
            fleet_spec, task_order
        )
        warnings.extend(dependency_warnings)
        if warnings:
            yield self._task_fleet_report(
                fleet_result=validation,
                status="refused",
                scheduled_groups=scheduled_groups,
                children=[],
            )
            return

        task_by_id = {task.task_id: task for task in fleet_spec.tasks}
        for group in scheduled_groups:
            group_results = await asyncio.gather(*[
                self._run_fleet_child(
                    args=args,
                    ctx=ctx,
                    agent_manager=agent_manager,
                    task_spec=task_by_id[task_id],
                )
                for task_id in group
            ])
            children.extend(group_results)

        children.sort(key=lambda child: task_order[child.task_id])
        yield self._task_fleet_report(
            fleet_result=validation,
            status="completed",
            scheduled_groups=scheduled_groups,
            children=children,
        )

    async def _run_delegate_flow(
        self, args: TaskArgs, ctx: InvokeContext, agent_manager: Any
    ) -> AsyncGenerator[ToolStreamEvent | TaskResult, None]:
        task_spec, provider_options, agent_profile_name = self._resolve_delegate_inputs(
            args
        )
        plan = self._build_execution_plan(agent_manager.config, provider_options)
        if plan.warnings:
            yield self._build_task_result(
                response="", turns_used=0, completed=False, plan=plan
            )
            return
        async for item in self._execute_subagent_task(
            args=args,
            ctx=ctx,
            agent_manager=agent_manager,
            plan=plan,
            agent_profile_name=agent_profile_name,
            task_id=task_spec.task_id if task_spec is not None else ctx.tool_call_id,
            task_spec=task_spec,
            prompt_text=args.task_text,
            emit_tool_events=True,
        ):
            if isinstance(item, ToolStreamEvent):
                yield item
            else:
                yield item.result

    @staticmethod
    def _build_subagent_loop(
        *,
        ctx: InvokeContext,
        args: TaskArgs,
        agent_manager: Any,
        plan: TaskExecutionPlan,
        agent_profile_name: str,
    ) -> AgentLoop:
        call_config = Task._build_call_config(
            VibeConfig.load(
                session_logging=SessionLoggingConfig(
                    save_dir=str(ctx.session_dir / "agents") if ctx.session_dir else "",
                    session_prefix=agent_profile_name,
                    enabled=ctx.session_dir is not None,
                )
            ),
            plan,
        )
        subagent_loop = AgentLoop(
            config=call_config,
            agent_name=agent_profile_name,
            entrypoint_metadata=ctx.entrypoint_metadata,
            is_subagent=True,
            defer_heavy_init=True,
        )

        if ctx.approval_callback:
            subagent_loop.set_approval_callback(ctx.approval_callback)

        return subagent_loop

    @staticmethod
    def _derive_task_session_status(*, plan: TaskExecutionPlan, completed: bool) -> str:
        if plan.warnings:
            return "refused"
        if completed:
            return "completed"
        return "truncated"

    def _write_task_session_link_artifact(
        self,
        *,
        ctx: InvokeContext,
        args: TaskArgs,
        prompt_text: str,
        plan: TaskExecutionPlan,
        result: TaskResult,
        task_spec: TaskSpec | None,
        child_session_dir: Path | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> ToolOutputArtifact | None:
        if ctx.session_dir is None:
            return None

        writer = ToolOutputArtifactWriter(str(ctx.session_dir.name))
        child_session_id = child_session_dir.name if child_session_dir else None
        child_manifest_sha256 = None
        if child_session_dir is not None:
            child_manifest_sha256 = self._file_sha256(
                child_session_dir / "manifest.json"
            )

        linkage = TaskSessionLinkArtifact(
            task_mode=task_spec.mode if task_spec is not None else "delegate",
            parent_session_id=ctx.session_dir.name,
            parent_turn_id=ctx.parent_turn_id,
            parent_tool_call_id=ctx.tool_call_id,
            task_id=task_spec.task_id if task_spec is not None else ctx.tool_call_id,
            agent_profile=task_spec.agent_profile
            if task_spec is not None
            else args.agent,
            child_session_id=child_session_id,
            provider=result.provider,
            model=result.model,
            thinking_requested=result.thinking_requested,
            thinking_enabled=result.thinking_enabled,
            thinking_type=result.thinking_type,
            reasoning_effort=result.reasoning_effort,
            tool_access_policy=result.tool_access_policy,
            result_compression_policy=result.result_compression_policy,
            scope_allowed_paths=(
                task_spec.scope.allowed_paths if task_spec is not None else []
            ),
            scope_dirty_file_policy=(
                task_spec.scope.dirty_file_policy if task_spec is not None else None
            ),
            scope_allow_write=(
                task_spec.scope.allow_write if task_spec is not None else None
            ),
            scope_allow_bash=(
                task_spec.scope.allow_bash if task_spec is not None else None
            ),
            expected_outputs=(
                task_spec.expected_outputs if task_spec is not None else []
            ),
            timeout_seconds=result.timeout_seconds,
            input_prompt_sha256=self._prompt_sha256(prompt_text),
            output_result_sha256=result.task_result_sha256,
            child_artifact_manifest_sha256=child_manifest_sha256,
            linkage_sha256="",
            status=self._derive_task_session_status(
                plan=plan, completed=result.completed
            ),
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            warnings=result.warnings,
        )
        linkage.linkage_sha256 = self._sha256_payload(
            linkage.model_dump(
                exclude_none=True, exclude={"started_at", "completed_at"}
            )
        )
        return writer.write_task_session_link_artifact(
            artifact=linkage, tool_call_id=ctx.tool_call_id
        )

    @staticmethod
    def _resolve_model(
        config: VibeConfig, provider_options: TaskProviderOptions
    ) -> ModelConfig:
        if provider_options.model:
            for model in config.models:
                if provider_options.model in {model.alias, model.name}:
                    return model
            raise ToolError(f"Unknown model: {provider_options.model}")

        if provider_options.provider:
            for model in config.models:
                if model.provider == provider_options.provider:
                    return model
            raise ToolError(f"Unknown provider: {provider_options.provider}")

        return config.get_active_model()

    @staticmethod
    def _build_execution_plan(
        config: VibeConfig, provider_options: TaskProviderOptions | None
    ) -> TaskExecutionPlan:
        options = provider_options or TaskProviderOptions()
        model = Task._resolve_model(config, options)
        provider = config.get_provider_for_model(model)
        warnings: list[str] = []
        extra_body: dict[str, Any] = {}
        thinking_requested = bool(options.thinking_enabled)
        thinking_enabled: bool | None = None
        thinking_type = options.thinking_type

        if options.provider and options.provider != provider.name:
            raise ToolError(
                f"Requested provider '{options.provider}' does not match resolved model provider '{provider.name}'."
            )

        if thinking_requested:
            if provider.name != "deepseek":
                warnings.append(
                    f"Thinking mode requested for unsupported provider '{provider.name}'."
                )
            else:
                thinking_enabled = True
                thinking_type = thinking_type or "enabled"
                extra_body["thinking"] = {"type": "enabled"}
                if options.reasoning_effort:
                    extra_body["reasoning_effort"] = options.reasoning_effort
        elif provider.name == "deepseek" and options.reasoning_effort:
            extra_body["reasoning_effort"] = options.reasoning_effort

        if not thinking_requested and provider.name == "deepseek":
            thinking_enabled = False

        return TaskExecutionPlan(
            provider=provider.name,
            model=model.alias,
            thinking_requested=thinking_requested,
            thinking_enabled=thinking_enabled,
            thinking_type=thinking_type,
            reasoning_effort=options.reasoning_effort,
            max_tokens=options.max_tokens,
            timeout_seconds=options.timeout_seconds,
            tool_access_policy=options.tool_access_policy,
            result_compression_policy=options.result_compression_policy,
            extra_body=extra_body,
            warnings=warnings,
        )

    @staticmethod
    def _build_task_result(
        *, response: str, turns_used: int, completed: bool, plan: TaskExecutionPlan
    ) -> TaskResult:
        result = TaskResult(
            response=response,
            turns_used=turns_used,
            completed=completed,
            provider=plan.provider,
            model=plan.model,
            thinking_requested=plan.thinking_requested,
            thinking_enabled=plan.thinking_enabled,
            thinking_type=plan.thinking_type,
            reasoning_effort=plan.reasoning_effort,
            tool_access_policy=plan.tool_access_policy,
            result_compression_policy=plan.result_compression_policy,
            timeout_seconds=plan.timeout_seconds,
            warnings=plan.warnings,
        )
        result.task_result_sha256 = Task._task_result_sha256(result)
        return result

    def resolve_permission(self, args: TaskArgs) -> PermissionContext | None:
        agent_name = args.agent

        for pattern in self.config.denylist:
            if fnmatch.fnmatch(agent_name, pattern):
                return PermissionContext(permission=ToolPermission.NEVER)

        for pattern in self.config.allowlist:
            if fnmatch.fnmatch(agent_name, pattern):
                return PermissionContext(permission=ToolPermission.ALWAYS)

        return None

    async def run(
        self, args: TaskArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | TaskResult, None]:
        if not ctx or not ctx.agent_manager:
            raise ToolError("Task tool requires agent_manager in context")

        agent_manager = ctx.agent_manager
        if args.fleet_spec is not None:
            async for fleet_result in self._run_fleet_flow(args, ctx, agent_manager):
                yield TaskResult(
                    response=dump_canonical_json(fleet_result.model_dump()),
                    turns_used=0,
                    completed=fleet_result.status == "completed",
                    warnings=fleet_result.warnings,
                )
            return
        async for item in self._run_delegate_flow(args, ctx, agent_manager):
            yield item

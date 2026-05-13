from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import UTC, datetime
import fnmatch
import hashlib
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from vibe.core.agent_loop import AgentLoop
from vibe.core.agents.models import AgentType, BuiltinAgentName
from vibe.core.config import ModelConfig, SessionLoggingConfig, VibeConfig
from vibe.core.telemetry.artifacts import (
    TaskSessionLinkArtifact,
    ToolOutputArtifactWriter,
)
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.permissions import PermissionContext
from vibe.core.tools.ui import (
    ToolCallDisplay,
    ToolResultDisplay,
    ToolUIData,
    ToolUIDataAdapter,
)
from vibe.core.types import (
    AssistantEvent,
    Role,
    ToolCallEvent,
    ToolResultEvent,
    ToolStreamEvent,
)


class TaskArgs(BaseModel):
    task: str = Field(description="The task to delegate to the subagent")
    agent: str = Field(
        default="explore",
        description="Name of the agent profile to use (must be a subagent)",
    )
    provider_options: TaskProviderOptions | None = Field(
        default=None,
        description="Explicit provider/model options for the delegated subagent.",
    )


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
            return ToolCallDisplay(summary=f"Running {args.agent} agent: {args.task}")
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
        if not path.is_file():
            return None
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

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
        plan: TaskExecutionPlan,
        result: TaskResult,
        child_session_dir: Path | None,
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        if ctx.session_dir is None:
            return

        writer = ToolOutputArtifactWriter(str(ctx.session_dir.name))
        child_session_id = child_session_dir.name if child_session_dir else None
        child_manifest_sha256 = None
        if child_session_dir is not None:
            child_manifest_sha256 = self._file_sha256(
                child_session_dir / "manifest.json"
            )

        linkage = TaskSessionLinkArtifact(
            parent_session_id=ctx.session_dir.name,
            parent_turn_id=ctx.parent_turn_id,
            parent_tool_call_id=ctx.tool_call_id,
            task_id=ctx.tool_call_id,
            child_session_id=child_session_id,
            provider=result.provider,
            model=result.model,
            thinking_requested=result.thinking_requested,
            thinking_enabled=result.thinking_enabled,
            thinking_type=result.thinking_type,
            reasoning_effort=result.reasoning_effort,
            tool_access_policy=result.tool_access_policy,
            result_compression_policy=result.result_compression_policy,
            timeout_seconds=result.timeout_seconds,
            input_prompt_sha256=self._prompt_sha256(args.task),
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
        writer.write_task_session_link_artifact(
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
        plan = self._build_execution_plan(agent_manager.config, args.provider_options)
        if plan.warnings:
            yield self._build_task_result(
                response="", turns_used=0, completed=False, plan=plan
            )
            return

        try:
            agent_profile = agent_manager.get_agent(args.agent)
        except ValueError as e:
            raise ToolError(f"Unknown agent: {args.agent}") from e

        if agent_profile.agent_type != AgentType.SUBAGENT:
            raise ToolError(
                f"Agent '{args.agent}' is a {agent_profile.agent_type.value} agent. "
                f"Only subagents can be used with the task tool. "
                f"This is a security constraint to prevent recursive spawning."
            )

        call_config = self._build_call_config(
            VibeConfig.load(
                session_logging=SessionLoggingConfig(
                    save_dir=str(ctx.session_dir / "agents") if ctx.session_dir else "",
                    session_prefix=args.agent,
                    enabled=ctx.session_dir is not None,
                )
            ),
            plan,
        )
        subagent_loop = AgentLoop(
            config=call_config,
            agent_name=args.agent,
            entrypoint_metadata=ctx.entrypoint_metadata,
            is_subagent=True,
            defer_heavy_init=True,
        )

        if ctx and ctx.approval_callback:
            subagent_loop.set_approval_callback(ctx.approval_callback)

        task_text = args.task
        if ctx.scratchpad_dir:
            task_text = (
                f"Scratchpad directory: {ctx.scratchpad_dir}\n"
                "You can read and write files here without permission prompts.\n\n"
                f"{args.task}"
            )

        accumulated_response: list[str] = []
        completed = True
        started_at = datetime.now(UTC)
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
                        elif event.result and event.tool_class:
                            adapter = ToolUIDataAdapter(event.tool_class)
                            display = adapter.get_result_display(event)
                            message = f"{event.tool_name}: {display.message}"
                            yield ToolStreamEvent(
                                tool_name=self.get_name(),
                                message=message,
                                tool_call_id=ctx.tool_call_id,
                            )

            turns_used = sum(
                msg.role == Role.assistant for msg in subagent_loop.messages
            )

        except Exception as e:
            completed = False
            accumulated_response.append(f"\n[Subagent error: {e}]")
            turns_used = sum(
                msg.role == Role.assistant for msg in subagent_loop.messages
            )

        result = self._build_task_result(
            response="".join(accumulated_response),
            turns_used=turns_used,
            completed=completed,
            plan=plan,
        )
        self._write_task_session_link_artifact(
            ctx=ctx,
            args=args,
            plan=plan,
            result=result,
            child_session_dir=subagent_loop.session_logger.session_dir,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        yield result

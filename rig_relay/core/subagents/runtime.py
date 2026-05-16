"""SubagentRuntime — bounded mission execution without full AgentLoop.

Architecture boundary: must NOT import desktop, ralph, scripts, duckdb, or analytics.
Does NOT construct AgentLoop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import time
from typing import Any

from rig_relay.core.config import SessionLoggingConfig, VibeConfig
from rig_relay.core.llm.backend.factory import BACKEND_FACTORY
from rig_relay.core.llm.format import APIToolFormatHandler, ResolvedMessage
from rig_relay.core.llm.types import BackendLike
from rig_relay.core.subagents.models import SubagentMission, SubagentResult
from rig_relay.core.tools.manager import ToolManager
from rig_relay.core.types import LLMMessage, Role
from rig_relay.core.utils import TOOL_ERROR_TAG

try:
    from opentelemetry import trace as _otel_trace

    _OTEL = True
except ImportError:
    _OTEL = False
    _otel_trace = None


class SubagentRuntime:
    """Execute one bounded mission and return one bounded result."""

    def __init__(self, mission: SubagentMission) -> None:
        self._mission = mission
        self._messages: list[LLMMessage] = []
        self._backend: BackendLike | None = None
        self._tool_manager: ToolManager | None = None
        self._config: VibeConfig | None = None
        self._format_handler = APIToolFormatHandler()
        self._start_time: float = 0.0
        self._turns: int = 0
        self._tool_calls_attempted: int = 0
        self._tool_calls_succeeded: int = 0
        self._tool_calls_failed: int = 0
        self._trace_id: str | None = None

    async def execute(self) -> SubagentResult:
        self._start_time = time.monotonic()
        self._trace_id = self._capture_trace_id()

        try:
            self._setup_config()
            self._setup_backend()
            self._setup_tools()
            self._setup_messages()
            await self._run_loop()
        except asyncio.CancelledError:
            return self._build_result(status="cancelled", reason="cancelled")
        except Exception as exc:
            return self._build_result(status="error", reason=str(exc)[:500])

        return self._build_result(status="completed")

    def _build_result(self, *, status: str, reason: str = "") -> SubagentResult:
        summary = ""
        if self._messages:
            last = self._messages[-1]
            if last.role == Role.assistant and last.content:
                summary = last.content[:2000]

        errors = [reason] if reason and status in {"error", "cancelled"} else []

        return SubagentResult(
            mission_id=self._mission.mission_id,
            status=status,
            summary=summary,
            errors=errors,
            turns_used=self._turns,
            tool_calls_attempted=self._tool_calls_attempted,
            tool_calls_succeeded=self._tool_calls_succeeded,
            tool_calls_failed=self._tool_calls_failed,
            provider=self._mission.provider,
            model=self._mission.model,
            started_at=datetime.fromtimestamp(self._start_time, tz=UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            trace_id=self._trace_id,
        )

    def _setup_config(self) -> None:
        self._config = VibeConfig.load(
            session_logging=SessionLoggingConfig(
                enabled=True,
                save_dir=str(self._mission.parent_session_id),
                session_prefix=self._mission.agent_profile,
            )
        )
        if self._mission.model:
            self._config.active_model = self._mission.model
        if self._mission.enabled_tools:
            self._config.enabled_tools = self._mission.enabled_tools
        if self._mission.disabled_tools:
            self._config.disabled_tools = self._mission.disabled_tools

    def _setup_backend(self) -> None:
        assert self._config is not None
        provider = self._config.get_active_provider()
        timeout = self._config.api_timeout
        self._backend = BACKEND_FACTORY[provider.backend](
            provider=provider, timeout=timeout
        )

    def _setup_tools(self) -> None:
        assert self._config is not None
        cfg = self._config  # narrow type
        self._tool_manager = ToolManager(lambda: cfg)

    def _setup_messages(self) -> None:
        assert self._config is not None
        assert self._tool_manager is not None
        from rig_relay.core.agents.manager import AgentManager
        from rig_relay.core.skills.manager import SkillManager
        from rig_relay.core.system_prompt import get_universal_system_prompt

        cfg = self._config
        system = get_universal_system_prompt(
            self._tool_manager,
            cfg,
            SkillManager(lambda: cfg),
            AgentManager(lambda: cfg),
            headless=True,
        )
        self._messages = [LLMMessage(role=Role.system, content=system)]
        self._messages.append(LLMMessage(role=Role.user, content=self._mission.task))

    async def _run_loop(self) -> None:
        assert self._tool_manager is not None
        max_turns = self._mission.budget_max_turns
        for turn_index in range(max_turns):
            self._turns = turn_index + 1
            assistant = await self._call_llm()
            if assistant is None:
                break
            parsed = self._format_handler.parse_message(self._messages[-1])
            resolved = self._format_handler.resolve_tool_calls(
                parsed, self._tool_manager
            )
            if not resolved.tool_calls:
                break
            await self._execute_tool_calls(resolved)
            if self._tool_calls_attempted >= self._mission.budget_max_tool_calls:
                break

    async def _call_llm(self) -> LLMMessage | None:
        assert self._backend is not None
        assert self._config is not None
        assert self._tool_manager is not None
        tools = self._format_handler.get_available_tools(self._tool_manager)
        result = await self._backend.complete(
            model=self._config.get_active_model(),
            messages=self._messages,
            temperature=0.0,
            tools=tools,
            tool_choice="auto",
            extra_headers={},
            max_tokens=None,
        )
        if result is None or result.message is None:
            return None
        self._messages.append(result.message)
        return result.message

    async def _execute_tool_calls(self, resolved: ResolvedMessage) -> None:
        assert self._tool_manager is not None
        for tc in resolved.tool_calls:
            self._tool_calls_attempted += 1
            tool_class = self._tool_manager.available_tools.get(tc.tool_name)

            if tool_class is None:
                self._messages.append(
                    LLMMessage(
                        role=Role.tool,
                        content=f"<{TOOL_ERROR_TAG}>Tool '{tc.tool_name}' not available</{TOOL_ERROR_TAG}>",
                    )
                )
                self._tool_calls_failed += 1
                continue

            try:
                from rig_relay.core.tools.base import InvokeContext

                ctx = InvokeContext(tool_call_id=tc.call_id)
                tool_inst = self._tool_manager.get(tc.tool_name)
                result_model: Any = None
                text_output = ""

                async for event in tool_inst.run(tc.validated_args, ctx):
                    ev: Any = event
                    if hasattr(ev, "result"):
                        result_model = ev.result
                    if hasattr(ev, "content"):
                        text_output += str(ev.content)

                response: dict[str, Any]
                if result_model is not None and hasattr(result_model, "model_dump"):
                    response = result_model.model_dump()
                elif text_output:
                    response = {"output": text_output}
                else:
                    response = {"output": "ok"}

                text = "\n".join(f"{k}: {v}" for k, v in response.items())
                self._messages.append(LLMMessage(role=Role.tool, content=text))
                self._tool_calls_succeeded += 1

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._messages.append(
                    LLMMessage(
                        role=Role.tool,
                        content=f"<{TOOL_ERROR_TAG}>{tc.tool_name} failed: {exc}</{TOOL_ERROR_TAG}>",
                    )
                )
                self._tool_calls_failed += 1

    def _capture_trace_id(self) -> str | None:
        if not _OTEL or _otel_trace is None:
            return None
        try:
            span = _otel_trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx is not None and ctx.is_valid:
                return format(ctx.trace_id, "032x")
        except Exception:
            pass
        return None

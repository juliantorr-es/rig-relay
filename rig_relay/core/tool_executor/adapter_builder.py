from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from rig_relay.core.tool_runtime import ToolRuntime
from rig_relay.core.tools.base import InvokeContext

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.tool_executor.context import ToolSessionContext, ToolTurnContext
    from rig_relay.core.tools.base import BaseTool


class ToolRuntimeAdapterBuilder:
    """Builds ToolRuntime with all governance adapters.

    Accepts both an AgentLoop reference (for tool invocation
    infrastructure: tool_manager, agent_manager, session_logger, etc.)
    and a ToolSessionContext (for execution boundary state:
    session_id, trace_runtime, approval ports, etc.).

    Per-turn context is set via set_turn_context() before each batch.
    """

    __slots__ = ("_loop", "_session_ctx", "_turn_ctx", "_build_count")

    def __init__(self, *, loop: AgentLoop, session_ctx: ToolSessionContext) -> None:
        self._loop: AgentLoop = loop
        self._session_ctx = session_ctx
        self._turn_ctx: ToolTurnContext | None = None
        self._build_count = 0

    def set_turn_context(self, turn_ctx: ToolTurnContext) -> None:
        self._turn_ctx = turn_ctx

    def clear_turn_context(self) -> None:
        self._turn_ctx = None

    def build_tool_runtime(
        self,
        tool_class: type[BaseTool] | None = None,
        tool_instance: BaseTool | None = None,
        *,
        mission_authority: Any = None,
    ) -> ToolRuntime:
        self._build_count += 1

        runtime = ToolRuntime(
            invoke_tool=self._invoke_adapter,
            cache_check=self._cache_check,
            cache_store=self._cache_store,
            permission_decision=self._permission_decision,
            approval_request=self._approval_request,
            patch_gate_check=self._patch_gate_check,
            expand_args=self._expand_args,
            receipt_build=self._receipt_build,
            receipt_capture=self._receipt_capture,
            context_observe=self._context_observe,
            stats_delta=self._stats_delta,
            subprocess_runner=self._loop._build_subprocess_runner(),
            telemetry_client=self._loop.telemetry_client,
        )
        if mission_authority is not None:
            runtime._mission_authority = mission_authority
        return runtime

    # ── Invoke tool adapter ─────────────────────────────────

    async def _invoke_adapter(self, args_dict: dict) -> AsyncGenerator[Any, None]:
        loop = self._loop
        turn_ctx = self._turn_ctx
        user_message_id = turn_ctx.user_message_id if turn_ctx else ""
        tool_name = args_dict.pop("_tool_runtime_name", "")
        tool_meta = args_dict.pop("_tool_runtime_meta", {})
        subprocess_runner = tool_meta.get("subprocess_runner")
        tool_instance = loop.tool_manager.get(tool_name)
        async for item in tool_instance.invoke(
            ctx=InvokeContext(
                tool_call_id="",
                parent_turn_id=user_message_id,
                agent_manager=loop.agent_manager,
                session_dir=loop.session_logger.session_dir,
                entrypoint_metadata=loop.entrypoint_metadata,
                approval_callback=self._session_ctx.approval_callback,
                user_input_callback=loop.user_input_callback,
                sampling_callback=loop._sampling_handler,
                plan_file_path=loop._plan_session.plan_file_path,
                switch_agent_callback=loop.switch_agent,
                skill_manager=loop.skill_manager,
                scratchpad_dir=loop.scratchpad_dir,
                tool_manager=loop.tool_manager,
                subprocess_runner=subprocess_runner,
                trace_recorder=(
                    getattr(loop._tool_runtime, "_trace_recorder", None)
                    if loop._tool_runtime
                    else None
                ),
                tool_runtime=loop._tool_runtime,
                workspace_root=self._session_ctx.workspace_root,
            ),
            **args_dict,
        ):
            yield item

    # ── Cache adapters ──────────────────────────────────────

    def _cache_check(self, tool_name: str, args_dict: dict) -> tuple[bool, Any]:
        loop = self._loop
        tool_class = loop.tool_manager.available_tools.get(tool_name)
        if tool_class is None:
            return False, None
        determinism_cls = getattr(tool_class, "determinism_class", None)
        if determinism_cls is None:
            return False, None
        from rig_relay.core.tools.cache import get_cached_result

        determinism_str = str(determinism_cls.value)
        if determinism_str not in {"DETERMINISTIC_PURE", "DETERMINISTIC_REPO_STATE"}:
            return False, None
        cached = get_cached_result(
            tool_name=tool_name, args_dict=args_dict, determinism_class=determinism_str
        )
        if cached is not None:
            __args_model, _result_model = tool_class._get_type_hints()
            return True, _result_model(**cached)
        return False, None

    def _cache_store(self, tool_name: str, args_dict: dict, result_dict: dict) -> None:
        loop = self._loop
        tool_class = loop.tool_manager.available_tools.get(tool_name)
        if tool_class is None:
            return
        determinism_cls = getattr(tool_class, "determinism_class", None)
        if determinism_cls is None:
            return
        from rig_relay.core.tools.cache import set_cached_result

        determinism_str = str(determinism_cls.value)
        if determinism_str in {"DETERMINISTIC_PURE", "DETERMINISTIC_REPO_STATE"}:
            set_cached_result(
                tool_name=tool_name,
                args_dict=args_dict,
                result_dict=result_dict,
                determinism_class=determinism_str,
            )

    # ── Mutation detection ──────────────────────────────────

    def _is_mutation_tool(self, tool_name: str) -> bool:
        loop = self._loop
        try:
            tool_class = loop.tool_manager.available_tools.get(tool_name)
            if tool_class is None:
                return True

            mc = getattr(tool_class, "mutation_class", None)
            if mc is None:
                return False
            mc_val = str(mc.value) if hasattr(mc, "value") else str(mc)
            return mc_val not in {
                "read_only",
                "writes_evidence_only",
                "writes_temp_only",
                "unknown",
            }
        except Exception:
            return True

    # ── Permission decision ─────────────────────────────────

    async def _permission_decision(
        self, tool_name: str, args_dict: dict, call_id: str
    ) -> tuple[bool, str]:
        loop = self._loop
        if loop.bypass_tool_permissions:
            return True, ""
        try:
            clean_args = {
                k: v for k, v in args_dict.items() if not k.startswith("_tool_runtime")
            }
            decision = loop._governance_runtime.should_execute_tool(
                tool_call_id=call_id,
                tool_name=tool_name,
                tool_args=clean_args,
                execution_mode="tool",
            )
            from rig_relay.core._agent_models import ToolExecutionResponse

            if decision.verdict == ToolExecutionResponse.SKIP:
                return False, decision.feedback or "Tool execution skipped"
            return True, ""
        except Exception:
            reason = "permission_unavailable"
            turn_id = self._turn_ctx.user_message_id if self._turn_ctx else ""
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=%s session=%s turn=%s invocation=%s",
                reason,
                loop.session_id,
                turn_id,
                call_id,
            )
            if self._is_mutation_tool(tool_name):
                return False, reason
            return True, ""

    # ── Approval adapter ────────────────────────────────────

    async def _approval_request(
        self, tool_name: str, args_dict: dict, call_id: str
    ) -> tuple[bool, str]:
        loop = self._loop
        callback = self._session_ctx.approval_callback or loop.approval_callback
        if callback is None:
            return True, ""
        try:
            tool_instance = loop.tool_manager.get(tool_name)
            from rig_relay.core.types import ApprovalResponse

            try:
                args = tool_instance.ArgsModel(**args_dict)
            except Exception:
                args = args_dict

            response, feedback = await callback(tool_name, args, call_id, [])
            return response == ApprovalResponse.YES, feedback or ""
        except Exception:
            reason = "approval_unavailable"
            turn_id = self._turn_ctx.user_message_id if self._turn_ctx else ""
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=%s session=%s turn=%s invocation=%s",
                reason,
                loop.session_id,
                turn_id,
                call_id,
            )
            if self._is_mutation_tool(tool_name):
                return False, reason
            return True, ""

    # ── Patch gate adapter ──────────────────────────────────

    def _patch_gate_check(
        self, tool_call_ref: Any, tool_instance_ref: Any
    ) -> Any | None:
        loop = self._loop
        if tool_call_ref is None:
            return None
        tool_name = getattr(tool_call_ref, "tool_name", "")
        try:
            tool_instance = loop.tool_manager.get(tool_name)
        except Exception:
            reason = "patch_gate_unavailable"
            turn_id = self._turn_ctx.user_message_id if self._turn_ctx else ""
            from rig_relay.core.logger import logger

            logger.warning(
                "governance.degraded: reason=%s session=%s turn=%s",
                reason,
                loop.session_id,
                turn_id,
            )
            return reason
        return loop._check_patch_proposal_gating(tool_call_ref, tool_instance)

    # ── Expand args adapter ─────────────────────────────────

    def _expand_args(self, args_dict: dict) -> dict:
        return self._loop._expand_tool_call_args(args_dict)

    # ── Receipt adapters ────────────────────────────────────

    def _receipt_build(self, tool_name: str, result_model: Any) -> Any | None:
        loop = self._loop
        tool_class = loop.tool_manager.available_tools.get(tool_name)
        if tool_class is None:
            return None
        build_receipt = getattr(tool_class, "build_receipt", None)
        if build_receipt is None:
            return None
        return build_receipt(result_model)

    def _receipt_capture(
        self, session_id: str, tool_name: str, receipt_dict: dict
    ) -> None:
        loop = self._loop
        try:
            from rig_relay.evidence.model_observations import capture_tool_receipt

            capture_tool_receipt(
                session_id=loop.session_id, tool_name=tool_name, receipt=receipt_dict
            )
        except Exception:
            from rig_relay.core.logger import logger

            logger.warning("Receipt capture failed for %s", tool_name, exc_info=True)

    # ── Context observation adapter ─────────────────────────

    def _context_observe(
        self,
        status: str,
        tool_name: str,
        args_dict: dict,
        blocked_by_policy: bool = False,
    ) -> None:
        loop = self._loop
        if not loop.config.enable_local_observability:
            return
        try:
            import hashlib

            from rig_relay.evidence.model_observations import observe_tool_call

            observe_tool_call(
                session_id=loop.session_id,
                task_kind="tool_execution",
                task_fingerprint=hashlib.sha256(
                    str(args_dict).encode("utf-8")
                ).hexdigest(),
                provider_kind=loop.config.get_active_provider().name,
                provider_name=loop.config.get_active_provider().name,
                model_id=(
                    loop.config.active_model
                    if hasattr(loop.config, "active_model")
                    else ""
                ),
                tool_call_count=1,
                tool_success_count=1 if status == "succeeded" else 0,
                failure_count=1 if status == "failed" else 0,
            )
        except Exception:
            pass

    # ── Stats adapter ───────────────────────────────────────

    def _stats_delta(self, key: str, delta: int) -> None:
        loop = self._loop
        current = getattr(loop.stats, key, 0)
        setattr(loop.stats, key, current + delta)

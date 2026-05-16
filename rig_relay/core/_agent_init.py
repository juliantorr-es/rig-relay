"""Init helpers mixin for AgentLoop.

Extracted from agent_loop.py. Provides helper methods for constructing
the many subsystems that AgentLoop.__init__ wires together.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rig_relay.context.models import ContextRequest
from rig_relay.core.types import LLMMessage, Role

if TYPE_CHECKING:
    from rig_relay.core.config import VibeConfig


class InitHelpersMixin:
    """Mixin providing init-time setup helpers."""

    def _init_core_managers(
        self,
        config: VibeConfig,
        agent_name: str,
        is_subagent: bool,
        defer_heavy_init: bool,
    ) -> None:
        from rig_relay.core.agents.manager import AgentManager
        from rig_relay.core.llm.format import APIToolFormatHandler
        from rig_relay.core.middleware import MiddlewarePipeline
        from rig_relay.core.plan_session import PlanSession
        from rig_relay.core.scratchpad import init_scratchpad
        from rig_relay.core.session.session_id import generate_session_id
        from rig_relay.core.skills.manager import SkillManager
        from rig_relay.core.system_prompt import get_universal_system_prompt
        from rig_relay.core.tools.manager import ToolManager
        from rig_relay.core.tools.mcp import MCPRegistry
        from rig_relay.core.tools.mcp_sampling import MCPSamplingHandler

        self.mcp_registry = MCPRegistry()
        self.connector_registry = self._create_connector_registry()
        self.agent_manager = AgentManager(
            lambda: self._base_config,
            initial_agent=agent_name,
            allow_subagent=is_subagent,
        )
        self.tool_manager = ToolManager(
            lambda: self.config,
            mcp_registry=self.mcp_registry,
            connector_registry=self.connector_registry,
            defer_mcp=defer_heavy_init,
        )
        self.skill_manager = SkillManager(lambda: self.config)
        self._plan_session = PlanSession()

        self.format_handler = APIToolFormatHandler()

        self._sampling_handler = MCPSamplingHandler(
            backend_getter=lambda: self.backend,
            config_getter=lambda: self.config,
            metadata_getter=lambda: self._build_backend_metadata(
                call_type="secondary_call"
            ).model_dump(exclude_none=True),
            extra_headers_getter=self._get_extra_headers,
        )

        self.middleware_pipeline = MiddlewarePipeline()
        self._setup_middleware()

        self.session_id = generate_session_id()
        self.parent_session_id = None
        self.scratchpad_dir = (
            init_scratchpad(self.session_id) if not is_subagent else None
        )

        system_prompt = get_universal_system_prompt(
            self.tool_manager,
            self.config,
            self.skill_manager,
            self.agent_manager,
            include_git_status=not defer_heavy_init,
            scratchpad_dir=self.scratchpad_dir,
            headless=self._headless,
        )
        system_message = LLMMessage(role=Role.system, content=system_prompt)
        self.messages = self._make_message_list(
            initial=[system_message], observer=self.message_observer
        )

    def _init_context_compiler(self, defer_heavy_init: bool) -> None:
        from rig_relay.context.repo_index import RepoContextIndex

        self._repo_index = None
        self._context_compiler = None

        if not defer_heavy_init:
            try:
                repo_index = RepoContextIndex(workspace_root=self._workspace_root)
                if repo_index.is_available:
                    repo_index.populate()
                    self._repo_index = repo_index
            except Exception:
                pass
            self._context_compiler = self._make_context_compiler(
                repo_index=self._repo_index, receipt_store=self._make_receipt_store()
            )

    def _init_telemetry_and_guard(
        self,
        config: VibeConfig,
        entrypoint_metadata: Any,
        is_subagent: bool,
        hook_config_result: Any,
    ) -> None:
        from rig_relay.core.guard import (
            DirtyGuardFailurePolicy,
            GuardCaptureReason,
            get_guard,
        )
        from rig_relay.core.hooks.manager import HooksManager
        from rig_relay.core.rewind import RewindManager
        from rig_relay.core.session.session_logger import SessionLogger
        from rig_relay.core.telemetry.send import TelemetryClient

        self.telemetry_client = TelemetryClient(
            config_getter=lambda: self.config,
            session_id_getter=lambda: self.session_id,
            parent_session_id_getter=lambda: self.parent_session_id,
            entrypoint_metadata_getter=lambda: self.entrypoint_metadata,
        )
        self.session_logger = SessionLogger(config.session_logging, self.session_id)

        try:
            policy = (
                DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION
                if is_subagent
                else DirtyGuardFailurePolicy.WARN_ALLOW
            )
            reason = (
                GuardCaptureReason.FORK_CHILD
                if is_subagent
                else GuardCaptureReason.AGENT_LOOP_INIT
            )
            get_guard().capture(reason=reason, failure_policy=policy)
        except Exception:
            pass

        self._hook_config_result = hook_config_result
        self._hooks_manager = (
            HooksManager(hook_config_result.hooks) if hook_config_result else None
        )
        self.hook_config_issues = (
            hook_config_result.issues if hook_config_result else []
        )
        self.rewind_manager = RewindManager(
            messages=self.messages,
            save_messages=self._save_messages,
            reset_session=self._reset_session,
        )

    def _init_ambient_context_packet(self) -> None:
        self._context_packet = None
        try:
            from rig_relay.context.compiler import execute as _ctx_build

            self._context_packet = _ctx_build(ContextRequest(mode="map"))
        except Exception:
            pass

    @staticmethod
    def _make_receipt_store() -> Any:
        from rig_relay.evidence.receipt_store import FilesystemReceiptStore

        return FilesystemReceiptStore(Path.cwd() / ".rig" / "relay" / "receipts")

    @staticmethod
    def _make_context_compiler(repo_index: Any, receipt_store: Any) -> Any:
        from rig_relay.context.compiler import ContextCompiler

        return ContextCompiler(
            session_id="",  # overwritten by caller
            workspace_root=Path.cwd(),
            receipt_store=receipt_store,
            repo_index=repo_index,
        )

    @staticmethod
    def _make_message_list(initial: list, observer: Any) -> Any:
        from rig_relay.core.types import MessageList

        return MessageList(initial=initial, observer=observer)

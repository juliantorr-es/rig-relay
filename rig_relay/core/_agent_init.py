"""AgentLoop init helpers.

Extracted from agent_loop.py. Provides helper methods for constructing
the many subsystems that AgentLoop.__init__ wires together. Now explicit
composition — methods receive the loop/facade rather than relying on
MRO-based attribute resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.context.models import ContextRequest
from rig_relay.core.types import LLMMessage, Role


class InitHelpers:
    """Composition-based init-time setup helpers for AgentLoop."""

    @staticmethod
    def init_core_managers(
        loop,
        config,
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

        loop.mcp_registry = MCPRegistry()
        loop.connector_registry = loop._create_connector_registry()
        loop.agent_manager = AgentManager(
            lambda: loop._base_config,
            initial_agent=agent_name,
            allow_subagent=is_subagent,
        )
        loop.tool_manager = ToolManager(
            lambda: loop.config,
            mcp_registry=loop.mcp_registry,
            connector_registry=loop.connector_registry,
            defer_mcp=defer_heavy_init,
        )
        loop.skill_manager = SkillManager(lambda: loop.config)
        loop._plan_session = PlanSession()

        loop.format_handler = APIToolFormatHandler()

        loop._sampling_handler = MCPSamplingHandler(
            backend_getter=lambda: loop.backend,
            config_getter=lambda: loop.config,
            metadata_getter=lambda: loop._build_backend_metadata(
                call_type="secondary_call"
            ).model_dump(exclude_none=True),
            extra_headers_getter=loop._get_extra_headers,
        )

        loop.middleware_pipeline = MiddlewarePipeline()

        loop.session_id = generate_session_id()
        loop.parent_session_id = None
        loop.scratchpad_dir = (
            init_scratchpad(loop.session_id) if not is_subagent else None
        )

        system_prompt = get_universal_system_prompt(
            loop.tool_manager,
            loop.config,
            loop.skill_manager,
            loop.agent_manager,
            include_git_status=not defer_heavy_init,
            scratchpad_dir=loop.scratchpad_dir,
            headless=loop._headless,
        )
        system_message = LLMMessage(role=Role.system, content=system_prompt)
        loop.messages = InitHelpers._make_message_list(
            initial=[system_message], observer=loop.message_observer
        )

    @staticmethod
    def init_context_compiler(loop, defer_heavy_init: bool) -> None:
        from rig_relay.context.repo_index import RepoContextIndex

        loop._repo_index = None
        loop._context_compiler = None

        if not defer_heavy_init:
            try:
                repo_index = RepoContextIndex(workspace_root=loop._workspace_root)
                if repo_index.is_available:
                    repo_index.populate()
                    loop._repo_index = repo_index
            except Exception:
                pass
            loop._context_compiler = InitHelpers._make_context_compiler(
                repo_index=loop._repo_index,
                receipt_store=InitHelpers._make_receipt_store(),
            )

    @staticmethod
    def init_telemetry_and_guard(
        loop,
        config,
        entrypoint_metadata,
        is_subagent: bool,
        hook_config_result,
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

        loop.telemetry_client = TelemetryClient(
            config_getter=lambda: loop.config,
            session_id_getter=lambda: loop.session_id,
            parent_session_id_getter=lambda: loop.parent_session_id,
            entrypoint_metadata_getter=lambda: loop.entrypoint_metadata,
            consent_record_getter=InitHelpers._load_consent_record,
        )
        loop.session_logger = SessionLogger(config.session_logging, loop.session_id)

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
            guard = get_guard()
            guard.capture(reason=reason, failure_policy=policy)
            if guard._capture_failed:
                guard.failure_policy = DirtyGuardFailurePolicy.FAIL_CLOSED_FOR_MUTATION
        except Exception:
            pass

        loop._hook_config_result = hook_config_result
        loop._hooks_manager = (
            HooksManager(hook_config_result.hooks) if hook_config_result else None
        )
        loop.hook_config_issues = (
            hook_config_result.issues if hook_config_result else []
        )
        loop.rewind_manager = RewindManager(
            messages=loop.messages,
            save_messages=loop._save_messages,
            reset_session=loop._reset_session,
        )

    @staticmethod
    def init_ambient_context_packet(loop) -> None:
        loop._context_packet = None
        try:
            from rig_relay.context.compiler import execute as _ctx_build
            from rig_relay.context.models import ContextMode

            loop._context_packet = _ctx_build(ContextRequest(mode=ContextMode.MAP))
        except Exception:
            pass

    @staticmethod
    def _load_consent_record() -> object | None:
        try:
            from pathlib import Path

            consent_path = Path.cwd() / ".rig" / "relay" / "telemetry_consent.json"
            if not consent_path.is_file():
                return None
            import json

            data = json.loads(consent_path.read_text(encoding="utf-8"))
            from rig_relay.identity.telemetry_consent import TelemetryConsentRecord

            return TelemetryConsentRecord.model_validate(data)
        except Exception:
            return None

    @staticmethod
    def _make_receipt_store() -> Any:
        from rig_relay.evidence.receipt_store import FilesystemReceiptStore

        return FilesystemReceiptStore(Path.cwd() / ".rig" / "relay" / "receipts")

    @staticmethod
    def _make_context_compiler(repo_index, receipt_store) -> Any:
        from rig_relay.context.compiler import ContextCompiler

        return ContextCompiler(
            session_id="",  # overwritten by caller
            workspace_root=Path.cwd(),
            receipt_store=receipt_store,
            repo_index=repo_index,
        )

    @staticmethod
    def _make_message_list(initial: list, observer) -> Any:
        from rig_relay.core.types import MessageList

        return MessageList(initial=initial, observer=observer)

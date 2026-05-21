from __future__ import annotations

import asyncio
from pathlib import Path
import signal
import sys
from typing import Any, cast, override

from acp import Agent as AcpAgent, run_agent
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    Implementation,
    ListSessionsResponse,
    SessionInfo,
    ToolCallUpdate,
)
from pydantic import BaseModel, ValidationError

from rig_relay import RIG_ROOT, __version__
from rig_relay.acp._commands import CommandsMixin
from rig_relay.acp._config import ConfigMixin
from rig_relay.acp._disabled_tools import NON_INTERACTIVE_DISABLED_TOOLS
from rig_relay.acp._prompt import PromptMixin
from rig_relay.acp._protocol import ProtocolMixin
from rig_relay.acp._session_lifecycle import SessionLifecycleMixin
from rig_relay.acp._usage import UsageMixin
from rig_relay.acp.acp_logger import acp_message_observer
from rig_relay.acp.exceptions import (
    ConfigurationError,
    InvalidRequestError,
    UnauthenticatedError,
)
from rig_relay.acp.session import AcpSessionLoop
from rig_relay.acp.utils import ToolOption, build_permission_options
from rig_relay.core.config import MissingAPIKeyError, SessionLoggingConfig, VibeConfig
from rig_relay.core.logger import logger
from rig_relay.core.session.session_loader import SessionLoader
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata
from rig_relay.core.telemetry.send import TelemetryClient
from rig_relay.core.telemetry.types import EntrypointMetadata
from rig_relay.core.tools.permissions import RequiredPermission
from rig_relay.core.types import ApprovalCallback, ApprovalResponse
from rig_relay.core.utils import CancellationReason, get_user_cancellation_message
from rig_relay.governance.service_state import get_capability_gate


class VibeAcpAgentLoop(
    SessionLifecycleMixin,
    CommandsMixin,
    ConfigMixin,
    UsageMixin,
    ProtocolMixin,
    PromptMixin,
    AcpAgent,
):
    def __init__(self) -> None:
        self.sessions: dict[str, AcpSessionLoop] = {}
        self.client_capabilities: ClientCapabilities | None = None
        self.client_info: Implementation | None = None
        self._mcp_servers: list | None = None

        gate = get_capability_gate()
        state = gate.state_summary()
        if state.get("service_state") in {"setup_required", "locked"}:
            logger.warning(
                "acp: profile is %s, mutation capabilities gated",
                state.get("profile_state"),
            )

    def _build_entrypoint_metadata(self) -> EntrypointMetadata:
        return build_entrypoint_metadata(
            agent_entrypoint="acp",
            agent_version=__version__,
            client_name=self.client_info.name if self.client_info else "",
            client_version=self.client_info.version if self.client_info else "",
        )

    def _load_config(self) -> VibeConfig:
        try:
            config = VibeConfig.load(disabled_tools=NON_INTERACTIVE_DISABLED_TOOLS)
            config.tool_paths.extend(self._get_acp_tool_overrides())
            return config
        except MissingAPIKeyError as e:
            raise UnauthenticatedError.from_missing_api_key(e) from e
        except Exception as e:
            raise ConfigurationError(str(e)) from e

    def _get_acp_tool_overrides(self) -> list[Path]:
        overrides = ["todo", "grep", "web_fetch", "web_search", "skill", "task"]

        if self.client_capabilities:
            if self.client_capabilities.terminal:
                overrides.append("bash")
            if self.client_capabilities.fs:
                fs = self.client_capabilities.fs
                if fs.read_text_file:
                    overrides.append("read_file")
                if fs.write_text_file:
                    overrides.extend(["write_file", "search_replace"])

        return [
            RIG_ROOT / "acp" / "tools" / "builtins" / f"{override}.py"
            for override in overrides
        ]

    def _create_approval_callback(self, session_id: str) -> ApprovalCallback:
        session = self._get_session(session_id)

        def _handle_permission_selection(
            option_id: str,
            tool_name: str,
            required_permissions: list[RequiredPermission] | None,
        ) -> tuple[ApprovalResponse, str | None]:
            match option_id:
                case ToolOption.ALLOW_ONCE:
                    return (ApprovalResponse.YES, None)
                case ToolOption.ALLOW_ALWAYS:
                    session.agent_loop.approve_always(tool_name, required_permissions)
                    return (ApprovalResponse.YES, None)
                case ToolOption.ALLOW_ALWAYS_PERMANENT:
                    session.agent_loop.approve_always(
                        tool_name, required_permissions, save_permanently=True
                    )
                    return (ApprovalResponse.YES, None)
                case ToolOption.REJECT_ONCE:
                    session.agent_loop.telemetry_client.send_user_cancelled_action(
                        "reject_approval"
                    )
                    return (
                        ApprovalResponse.NO,
                        "User rejected the tool call, provide an alternative plan",
                    )
                case _:
                    return (ApprovalResponse.NO, f"Unknown option: {option_id}")

        async def approval_callback(
            tool_name: str,
            args: BaseModel,
            tool_call_id: str,
            required_permissions: list | None = None,
        ) -> tuple[ApprovalResponse, str | None]:
            typed_permissions: list[RequiredPermission] | None = (
                [
                    rp
                    for rp in required_permissions
                    if isinstance(rp, RequiredPermission)
                ]
                if required_permissions
                else None
            )

            tool_call = ToolCallUpdate(tool_call_id=tool_call_id)
            options = build_permission_options(typed_permissions)

            response = await self.client.request_permission(
                session_id=session_id, tool_call=tool_call, options=options
            )

            if response.outcome.outcome == "selected":
                outcome = cast(AllowedOutcome, response.outcome)
                return _handle_permission_selection(
                    outcome.option_id, tool_name, typed_permissions
                )
            else:
                return (
                    ApprovalResponse.NO,
                    str(
                        get_user_cancellation_message(
                            CancellationReason.OPERATION_CANCELLED
                        )
                    ),
                )

        return approval_callback

    @override
    async def list_sessions(
        self, cursor: str | None = None, cwd: str | None = None, **kwargs: Any
    ) -> ListSessionsResponse:
        try:
            config = VibeConfig.load()
            session_logging_config = config.session_logging
        except MissingAPIKeyError:
            session_logging_config = SessionLoggingConfig()

        session_data = SessionLoader.list_sessions(session_logging_config, cwd=cwd)

        sessions = [
            SessionInfo(
                session_id=s["session_id"],
                cwd=s["cwd"],
                title=s.get("title"),
                updated_at=s.get("end_time"),
            )
            for s in sorted(
                session_data, key=lambda s: s.get("end_time") or "", reverse=True
            )
        ]

        return ListSessionsResponse(sessions=sessions)

    @override
    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self._get_session(session_id)
        session.agent_loop.telemetry_client.send_user_cancelled_action(
            "interrupt_agent"
        )
        await session.cancel_prompt()

    def _handle_telemetry_notification(self, params: dict[str, Any]) -> None:
        try:
            notification = TelemetrySendNotification.model_validate(params)
        except ValidationError as exc:
            raise InvalidRequestError(
                f"Invalid ACP telemetry notification: {exc}"
            ) from exc

        session = self.sessions.get(notification.session_id)
        if session is None:
            logger.warning(
                "Ignoring ACP telemetry notification because session could not be resolved: %s",
                notification.session_id,
            )
            return

        dispatcher = _EVENT_DISPATCHERS.get(notification.event)
        if dispatcher is None:
            logger.warning(
                "Ignoring unsupported ACP telemetry event: %s", notification.event
            )
            return

        dispatcher(session.agent_loop.telemetry_client, notification.properties)


SESSION_CLOSED_FLUSH_TIMEOUT_SECONDS = 1.0


class TelemetrySendNotification(BaseModel):
    session_id: str
    event: str
    properties: dict[str, Any] = {}

    model_config = {"extra": "allow"}


_EVENT_DISPATCHERS: dict[str, Any] = {}


def run_acp_server() -> None:
    agent = VibeAcpAgentLoop()
    install_sigterm_flush = TelemetryClient(config_getter=VibeConfig.load).is_active()
    received_sigterm = False
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def _handle_sigterm(_signum: int, _frame: Any) -> None:
        nonlocal received_sigterm
        received_sigterm = True
        raise KeyboardInterrupt

    if install_sigterm_flush:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        asyncio.run(
            run_agent(
                agent=agent,
                use_unstable_protocol=True,
                observers=[acp_message_observer],
            )
        )
    except KeyboardInterrupt:
        if received_sigterm:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
            try:
                asyncio.run(
                    asyncio.wait_for(
                        agent.emit_session_closed_for_active_sessions(),
                        timeout=SESSION_CLOSED_FLUSH_TIMEOUT_SECONDS,
                    )
                )
            except (TimeoutError, Exception):
                pass
        # This is expected when the server is terminated
        pass
    except Exception as e:
        # Log any unexpected errors
        print(f"ACP Agent Server error: {e}", file=sys.stderr)
        raise
    finally:
        if install_sigterm_flush:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)

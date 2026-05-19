"""ACP mixin — protocol."""

from __future__ import annotations

from typing import Any, override

from acp import Client
from acp.schema import AuthenticateResponse, SessionInfoUpdate
from pydantic import ValidationError

from rig_relay.acp._local_auth import build_acp_local_auth_state
from rig_relay.acp._refusal_adapter import build_acp_refusal, raise_acp_refusal
from rig_relay.acp.exceptions import (
    InternalError,
    InvalidRequestError,
    SessionNotFoundError,
)
from rig_relay.acp.session import AcpSessionLoop
from rig_relay.core.session.saved_sessions import (
    update_saved_session_title,
    update_saved_session_title_at_path,
)


class ProtocolMixin:
    """Mixin for VibeAcpAgentLoop."""

    @override
    async def authenticate(
        self, method_id: str, **kwargs: Any
    ) -> AuthenticateResponse | None:
        auth_state = build_acp_local_auth_state(
            auth_status="deferred",
            auth_method="unsupported",
            capability_id="acp.authenticate",
            trace_id=kwargs.get("trace_id", ""),
            deferred_reason="Live authentication is deferred in this alpha. "
            "Use the Rig Relay desktop cockpit to configure providers "
            "and API keys before connecting via ACP. Remediation: run "
            "'uv run rig-relay' and complete provider setup first.",
        )
        refusal = build_acp_refusal(
            refusal_code="acp.authenticate.deferred_or_unconfigured",
            reason="Live authentication is deferred in this alpha. "
            "Use the Rig Relay desktop cockpit to configure providers "
            "and API keys before connecting via ACP. Remediation: run "
            "'uv run rig-relay' and complete provider setup first.",
            method=method_id,
            trace_id=kwargs.get("trace_id", ""),
        )
        return AuthenticateResponse(
            field_meta={"auth_state": auth_state.to_dict(), "refusal": refusal}
        )

    async def _emit_session_info_update(
        self, session_id: str, *, title: str, updated_at: str | None
    ) -> None:
        update_kwargs: dict[str, Any] = {
            "session_update": "session_info_update",
            "title": title,
        }
        if updated_at is not None:
            update_kwargs["updated_at"] = updated_at

        await self.client.session_update(
            session_id=session_id, update=SessionInfoUpdate(**update_kwargs)
        )

    async def _persist_live_session_title(
        self, session: AcpSessionLoop, title: str
    ) -> dict[str, Any] | None:
        logger = session.agent_loop.session_logger
        if not logger.enabled or logger.session_dir is None:
            return None
        if not logger.metadata_filepath.exists():
            return None

        try:
            return await update_saved_session_title_at_path(logger.session_dir, title)
        except ValueError as exc:
            raise InternalError(
                f"Failed to persist title update for session {logger.session_id}: {exc}"
            ) from exc

    def _set_live_session_title(self, session: AcpSessionLoop, title: str) -> None:
        try:
            session.agent_loop.session_logger.set_title(title)
        except ValueError as exc:
            raise InvalidRequestError(
                f"Invalid ACP session title request: {exc}"
            ) from exc

    async def _handle_session_set_title(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            request = SessionSetTitleRequest.model_validate(params)
        except ValidationError as exc:
            raise InvalidRequestError(
                f"Invalid ACP session title request: {exc}"
            ) from exc

        live_session = self.sessions.get(
            request.session_id
        ) or self._find_acp_session_by_vibe_session_id(request.session_id)
        if live_session is None:
            try:
                metadata = await update_saved_session_title(
                    request.session_id,
                    request.title,
                    self._load_session_logging_config(),
                )
            except ValueError as exc:
                raise SessionNotFoundError(request.session_id) from exc

            await self._emit_session_info_update(
                request.session_id,
                title=request.title,
                updated_at=metadata.get("end_time"),
            )
            return {}

        persisted_metadata = await self._persist_live_session_title(
            live_session, request.title
        )
        self._set_live_session_title(live_session, request.title)
        updated_at = (
            persisted_metadata.get("end_time")
            if persisted_metadata is not None
            else (
                live_session.agent_loop.session_logger.session_metadata.end_time
                if live_session.agent_loop.session_logger.session_metadata is not None
                else None
            )
        )

        await self._emit_session_info_update(
            live_session.id, title=request.title, updated_at=updated_at
        )
        return {}

    @override
    async def ext_method(self, method: str, params: dict) -> dict:
        if method == "session/set_title":
            return await self._handle_session_set_title(params)

        raise_acp_refusal(
            refusal_code="not_implemented_deferred",
            reason=f"Extension method not implemented: {method}",
            method=method,
        )

    @override
    async def ext_notification(self, method: str, params: dict) -> None:
        # ACP strips the leading "_" before delegating extension notifications here.
        if method == "telemetry/send":
            self._handle_telemetry_notification(params)

    @override
    def on_connect(self, conn: Client) -> None:
        self.client = conn

    # -- Command handlers ------------------------------------------------------

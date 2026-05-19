"""Structured ACP error classes for the Vibe agent.

Error codes follow JSON-RPC 2.0 (https://www.jsonrpc.org/specification#error_object)
and ACP error handling (https://agentclientprotocol.com/protocol/overview#error-handling):

  -32700            Parse error (JSON-RPC standard)
  -32600            Invalid request (JSON-RPC standard)
  -32601            Method not found (JSON-RPC standard)
  -32602            Invalid params (JSON-RPC standard)
  -32603            Internal error (JSON-RPC standard)
  -32000 to -32099  Server errors (JSON-RPC implementation-defined)
  -31xxx            Application errors (Vibe-specific, outside reserved range)
"""

from __future__ import annotations

from typing import Any

from acp import RequestError

from rig_relay.core.config import MissingAPIKeyError
from rig_relay.core.types import (
    ContextTooLongError as CoreContextTooLongError,
    RateLimitError as CoreRateLimitError,
)

# JSON-RPC 2.0 standard codes
UNAUTHENTICATED = -32000
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Vibe application codes (outside JSON-RPC reserved range)
RATE_LIMITED = -31001
CONFIGURATION_ERROR = -31002
CONVERSATION_LIMIT = -31003
CONTEXT_TOO_LONG = -31004

# Rig-specific refusal codes (outside JSON-RPC reserved range)
REFUSAL_GENERAL = -31005
REFUSAL_SESSION_RESUME = -31006
REFUSAL_LIVE_AUTH = -31007
REFUSAL_CAPABILITY_DISABLED = -31008
REFUSAL_WORKSPACE_ISOLATION = -31009
REFUSAL_STALE_SESSION = -31010
REFUSAL_MUTATION_DENIED = -31011


class VibeRequestError(RequestError):
    code: int

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(self.code, message, data)


class UnauthenticatedError(VibeRequestError):
    code = UNAUTHENTICATED

    def __init__(self, detail: str) -> None:
        super().__init__(message=detail)

    @classmethod
    def from_missing_api_key(cls, exc: MissingAPIKeyError) -> UnauthenticatedError:
        return cls(f"Missing API key for {exc.provider_name} provider.")


class NotImplementedMethodError(VibeRequestError):
    code = METHOD_NOT_FOUND

    def __init__(self, method: str) -> None:
        super().__init__(
            message=f"Method not implemented: {method}", data={"method": method}
        )


class RefusalError(VibeRequestError):
    code = METHOD_NOT_FOUND

    def __init__(self, method: str, refusal_code: str, refusal: dict) -> None:
        super().__init__(
            message=f"Refused: {method} ({refusal_code})", data={"refusal": refusal}
        )


class InvalidRequestError(VibeRequestError):
    code = INVALID_PARAMS

    def __init__(self, detail: str) -> None:
        super().__init__(message=detail)


class SessionNotFoundError(VibeRequestError):
    code = INVALID_PARAMS

    def __init__(self, session_id: str) -> None:
        super().__init__(
            message=f"Session not found: {session_id}", data={"session_id": session_id}
        )


class SessionLoadError(VibeRequestError):
    code = INVALID_PARAMS

    def __init__(self, session_id: str, detail: str) -> None:
        super().__init__(
            message=f"Failed to load session {session_id}: {detail}",
            data={"session_id": session_id},
        )


class RateLimitError(VibeRequestError):
    code = RATE_LIMITED

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            message=f"Rate limit exceeded for {provider} (model: {model}).",
            data={"provider": provider, "model": model},
        )

    @classmethod
    def from_core(cls, exc: CoreRateLimitError) -> RateLimitError:
        return cls(exc.provider, exc.model)


class ContextTooLongError(VibeRequestError):
    code = CONTEXT_TOO_LONG

    def __init__(self, provider: str, model: str) -> None:
        super().__init__(
            message=f"Context too long for {provider} (model: {model}). "
            "Use /rewind to undo recent actions, then /compact to summarize.",
            data={"provider": provider, "model": model},
        )

    @classmethod
    def from_core(cls, exc: CoreContextTooLongError) -> ContextTooLongError:
        return cls(exc.provider, exc.model)


class ConfigurationError(VibeRequestError):
    code = CONFIGURATION_ERROR

    def __init__(self, detail: str) -> None:
        super().__init__(message=detail)


class ConversationLimitError(VibeRequestError):
    code = CONVERSATION_LIMIT

    def __init__(self, detail: str) -> None:
        super().__init__(message=detail)


class RigRefusalError(VibeRequestError):
    code = REFUSAL_GENERAL

    def __init__(self, refusal_code: str, detail: str, remediation: str = "") -> None:
        data: dict[str, Any] = {"refusal_code": refusal_code, "content_light": True}
        if remediation:
            data["remediation"] = remediation
        super().__init__(message=detail, data=data)


class SessionResumeRefusalError(VibeRequestError):
    code = REFUSAL_SESSION_RESUME

    def __init__(self, session_id: str, detail: str, remediation: str = "") -> None:
        data: dict[str, Any] = {
            "refusal_code": "resume_not_supported",
            "session_id": session_id,
            "content_light": True,
        }
        if remediation:
            data["remediation"] = remediation
        super().__init__(message=detail, data=data)


class LiveAuthRefusalError(VibeRequestError):
    code = REFUSAL_LIVE_AUTH

    def __init__(self, method_id: str, detail: str, remediation: str = "") -> None:
        data: dict[str, Any] = {
            "refusal_code": "live_auth_deferred",
            "method_id": method_id,
            "content_light": True,
        }
        if remediation:
            data["remediation"] = remediation
        super().__init__(message=detail, data=data)


class CapabilityDisabledError(VibeRequestError):
    code = REFUSAL_CAPABILITY_DISABLED

    def __init__(self, capability: str, detail: str) -> None:
        super().__init__(
            message=detail, data={"capability": capability, "content_light": True}
        )


class WorkspaceIsolationError(VibeRequestError):
    code = REFUSAL_WORKSPACE_ISOLATION

    def __init__(self, detail: str) -> None:
        super().__init__(
            message=detail,
            data={
                "refusal_code": "workspace_isolation_violation",
                "content_light": True,
            },
        )


class StaleSessionError(VibeRequestError):
    code = REFUSAL_STALE_SESSION

    def __init__(self, session_id: str, detail: str) -> None:
        super().__init__(
            message=detail, data={"session_id": session_id, "content_light": True}
        )


class MutationDeniedError(VibeRequestError):
    code = REFUSAL_MUTATION_DENIED

    def __init__(self, tool_name: str, detail: str) -> None:
        super().__init__(
            message=detail, data={"tool_name": tool_name, "content_light": True}
        )


class InternalError(VibeRequestError):
    code = INTERNAL_ERROR

    def __init__(self, detail: str) -> None:
        super().__init__(message=detail or "Internal error")

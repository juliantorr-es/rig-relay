"""AgentLoop error classes."""
from __future__ import annotations


class AgentLoopError(Exception):
    """Base exception for AgentLoop errors."""


class AgentLoopStateError(AgentLoopError):
    """Raised when agent loop is in an invalid state."""


class AgentLoopLLMResponseError(AgentLoopError):
    """Raised when LLM response is malformed or missing expected data."""


class TeleportError(AgentLoopError):
    """Raised when teleport to Vibe Code fails."""

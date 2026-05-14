"""Read-only action/intent types for the Rig Console DashboardScreen.

These models represent typed UI actions that the DashboardScreen can
route. They are content-light, read-only, and do not carry tool output,
file contents, or mutation capabilities.

Future slices will add a dispatcher/adapter that maps these intents
to backend/control-plane operations.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DashboardActionResult(BaseModel):
    """Outcome of a read-only dashboard action.

    Fields:
        action_name: Human-readable action name (e.g. "refresh", "help")
        status: One of "ok", "info", "error"
        message: Optional display message for the footer/status area
    """

    model_config = ConfigDict(extra="forbid")

    action_name: str
    status: str = "ok"
    message: str | None = None

    @classmethod
    def ok(cls, action_name: str, message: str | None = None) -> DashboardActionResult:
        """Convenience: create a successful action result."""
        return cls(action_name=action_name, status="ok", message=message)

    @classmethod
    def info(
        cls, action_name: str, message: str | None = None
    ) -> DashboardActionResult:
        """Convenience: create an informational action result."""
        return cls(action_name=action_name, status="info", message=message)

    @classmethod
    def error(
        cls, action_name: str, message: str | None = None
    ) -> DashboardActionResult:
        """Convenience: create an error action result."""
        return cls(action_name=action_name, status="error", message=message)


__all__ = ["DashboardActionResult"]

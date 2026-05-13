from __future__ import annotations

from dataclasses import dataclass
import importlib
import platform
import threading
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class LocalAuthResult:
    status: Literal["available", "unavailable", "authorized", "denied", "cancelled"]
    available: bool
    reason: str
    warnings: list[str]


def local_system_auth_available() -> bool:
    if platform.system() != "Darwin":
        return False
    try:
        importlib.import_module("LocalAuthentication")
    except Exception:
        return False
    return True


def authenticate_local_user(
    reason: str, timeout_seconds: int | None = None
) -> LocalAuthResult:
    """Evaluate macOS LocalAuthentication policy (Touch ID / Face ID / Passcode).

    This call is blocking and should be run in a separate thread if called
    from the pywebview UI thread (which the bridge already does).
    """
    if platform.system() != "Darwin":
        return LocalAuthResult(
            status="unavailable",
            available=False,
            reason="Local system auth is only available on macOS.",
            warnings=["LocalAuthentication unavailable"],
        )

    try:
        LocalAuthentication = importlib.import_module("LocalAuthentication")
        context = LocalAuthentication.LAContext.alloc().init()
        policy = LocalAuthentication.LAPolicyDeviceOwnerAuthentication

        can_eval, error = context.canEvaluatePolicy_error_(policy, None)
        if not can_eval:
            return LocalAuthResult(
                status="unavailable",
                available=False,
                reason=str(error) if error else "Policy evaluation not available.",
                warnings=["Local system auth hardware/config unavailable"],
            )

        finished = threading.Event()
        outcome: dict[str, Any] = {}

        def _reply(ok: bool, err: Any) -> None:
            outcome["ok"] = bool(ok)
            outcome["err"] = err
            finished.set()

        context.evaluatePolicy_localizedReason_reply_(policy, reason, _reply)

        wait_time = timeout_seconds or 60
        if not finished.wait(wait_time):
            return LocalAuthResult(
                status="cancelled",
                available=True,
                reason=f"Local system auth timed out after {wait_time}s.",
                warnings=["Local system auth timeout"],
            )

        if outcome.get("ok") is True:
            return LocalAuthResult(
                status="authorized",
                available=True,
                reason="Local system auth succeeded.",
                warnings=[],
            )

        error = outcome.get("err")
        return LocalAuthResult(
            status="denied",
            available=True,
            reason=str(error) if error else "Local system auth denied.",
            warnings=["Local system auth failed"],
        )
    except Exception as exc:
        status: Literal["unavailable", "denied"] = (
            "unavailable" if isinstance(exc, ImportError) else "denied"
        )
        return LocalAuthResult(
            status=status,
            available=False if status == "unavailable" else True,
            reason=f"Error during auth: {exc}",
            warnings=["Local system auth error"],
        )

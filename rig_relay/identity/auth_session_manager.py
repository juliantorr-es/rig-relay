"""AuthSessionManager — backend-owned OAuth loopback session lifecycle.

owns the loopback listener, session state, expiry, and cleanup.
the frontend never owns the listener. loopback runs in a daemon
thread using the synchronous http.server — no asyncio event-loop
requirements. no blocking main-thread i/o.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from rig_relay.core.logger import logger
from rig_relay.identity.models import IdentityProviderKind
from rig_relay.identity.oauth_loopback import (
    DEFAULT_LOOPBACK_HOST,
    build_loopback_redirect_uri,
    find_free_loopback_port,
)
from rig_relay.identity.providers import IdentityProvider
from rig_relay.identity.token_store import DevFileTokenStore

DEFAULT_AUTH_SESSION_TIMEOUT = 120.0
MAX_AUTH_SESSIONS = 10


class AuthSessionStatus(StrEnum):
    PENDING = auto()
    CALLBACK_RECEIVED = auto()
    EXCHANGED = auto()
    FAILED = auto()
    CANCELLED = auto()
    EXPIRED = auto()


class AuthSession:
    def __init__(
        self,
        session_id: str,
        provider: IdentityProviderKind,
        provider_impl: IdentityProvider,
        port: int,
        redirect_uri: str,
        state: str,
        state_hash: str,
        scopes: list[str],
        timeout: float = DEFAULT_AUTH_SESSION_TIMEOUT,
    ) -> None:
        self.session_id = session_id
        self.provider = provider
        self.provider_impl = provider_impl
        self.port = port
        self.redirect_uri = redirect_uri
        self.state = state
        self.state_hash = state_hash
        self.scopes = scopes
        self.auth_url = provider_impl.build_auth_url(
            redirect_uri=redirect_uri, state=state, scopes=scopes
        )
        self.status = AuthSessionStatus.PENDING
        self.started_at = time.time()
        self.timeout = timeout
        self.expires_at = self.started_at + timeout
        self.code: str | None = None
        self.callback_state: str | None = None
        self.error_code: str = ""
        self.error_message: str = ""
        self.display_name: str = ""
        self.account_id: str = ""
        self.email: str = ""
        self.started = threading.Event()
        self._stop = threading.Event()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def in_terminal_state(self) -> bool:
        return self.status in {
            AuthSessionStatus.EXCHANGED,
            AuthSessionStatus.FAILED,
            AuthSessionStatus.CANCELLED,
            AuthSessionStatus.EXPIRED,
        }

    @property
    def identity_summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider.value,
            "status": self.status.value,
            "display_name": self.display_name,
            "account_id_hash": _sha256(self.account_id) if self.account_id else "",
            "scopes": self.scopes,
            "started_at": datetime.fromtimestamp(self.started_at, tz=UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(self.expires_at, tz=UTC).isoformat(),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class AuthSessionManager:
    """Backend-owned auth session lifecycle.

    loopback listeners run in daemon threads using synchronous
    http.server — no asyncio event-loop dependencies.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AuthSession] = {}
        self._lock = threading.RLock()

    def _prune_if_needed(self) -> None:
        with self._lock:
            if len(self._sessions) >= MAX_AUTH_SESSIONS:
                expired = [
                    sid
                    for sid, s in self._sessions.items()
                    if s.status == AuthSessionStatus.EXPIRED
                ]
                for sid in expired:
                    self._sessions.pop(sid, None)
                if len(self._sessions) >= MAX_AUTH_SESSIONS:
                    pendings = sorted(
                        [
                            (sid, s)
                            for sid, s in self._sessions.items()
                            if s.status == AuthSessionStatus.PENDING
                        ],
                        key=lambda x: x[1].started_at,
                    )
                    for sid, s in pendings[MAX_AUTH_SESSIONS // 2 :]:
                        self._stop_server(s)
                        self._sessions.pop(sid, None)

    def start_session(
        self,
        provider_kind: IdentityProviderKind,
        provider_impl: IdentityProvider,
        scopes: list[str] | None = None,
        timeout: float = DEFAULT_AUTH_SESSION_TIMEOUT,
    ) -> tuple[AuthSession, str]:
        """Start an auth session with loopback listener.

        returns (session, auth_url). listener runs in a daemon thread,
        returns immediately. frontend opens auth_url; backend-owned
        thread captures the callback.
        """
        with self._lock:
            self._prune_if_needed()

            for sid, existing in list(self._sessions.items()):
                if (
                    existing.provider == provider_kind
                    and existing.status == AuthSessionStatus.PENDING
                ):
                    logger.warning(
                        "refusing double-listen for provider=%s existing_session_id=%s",
                        provider_kind.value,
                        sid,
                    )
                    raise RuntimeError(
                        f"Auth session already pending for {provider_kind.value}. "
                        f"Cancel or wait for existing session (id={sid[:8]}...)"
                    )

            port = find_free_loopback_port()
            redirect_uri = build_loopback_redirect_uri(port)
            state = secrets.token_hex(32)
            state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
            session_id = secrets.token_hex(16)
            effective_scopes = (
                scopes if scopes is not None else provider_impl.default_scopes()
            )

            session = AuthSession(
                session_id=session_id,
                provider=provider_kind,
                provider_impl=provider_impl,
                port=port,
                redirect_uri=redirect_uri,
                state=state,
                state_hash=state_hash,
                scopes=effective_scopes,
                timeout=timeout,
            )

            self._sessions[session_id] = session

            thread = threading.Thread(
                target=self._run_loopback,
                args=(session,),
                daemon=True,
                name=f"auth-loopback-{session_id[:8]}",
            )
            session._thread = thread
            thread.start()

        if not session.started.wait(timeout=5.0):
            logger.error("loopback server failed to start session_id=%s", session_id)
            session.status = AuthSessionStatus.FAILED
            session.error_code = "server_start_failed"
            raise RuntimeError(
                f"Loopback server failed to start for session {session_id}"
            )

        logger.info(
            "auth session started session_id=%s provider=%s port=%s",
            session_id,
            provider_kind.value,
            port,
        )
        return session, session.auth_url

    def _run_loopback(self, session: AuthSession) -> None:
        session_obj = session
        expected_state_hash = session_obj.state_hash

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                nonlocal session_obj
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                error = params.get("error", [None])[0]
                if error:
                    session_obj.status = AuthSessionStatus.FAILED
                    session_obj.error_code = "provider_denied"
                    session_obj.error_message = f"Provider error: {error}"
                    self._respond(400, _callback_html(False, f"Error: {error}"))
                    session_obj._stop.set()
                    return

                code = params.get("code", [None])[0]
                cb_state = params.get("state", [None])[0]

                if not code or not cb_state:
                    session_obj.status = AuthSessionStatus.FAILED
                    session_obj.error_code = "missing_params"
                    session_obj.error_message = "Missing code or state."
                    self._respond(400, _callback_html(False, "Missing code or state."))
                    session_obj._stop.set()
                    return

                state_hash = hashlib.sha256(cb_state.encode("utf-8")).hexdigest()
                if state_hash != expected_state_hash:
                    session_obj.status = AuthSessionStatus.FAILED
                    session_obj.error_code = "state_mismatch"
                    session_obj.error_message = "State mismatch — possible CSRF."
                    self._respond(400, _callback_html(False, "State mismatch."))
                    session_obj._stop.set()
                    return

                session_obj.status = AuthSessionStatus.CALLBACK_RECEIVED
                session_obj.code = code
                session_obj.callback_state = cb_state
                self._respond(
                    200,
                    _callback_html(
                        True, "Authorization received. You may close this tab."
                    ),
                )
                session_obj._stop.set()

            def _respond(self, status: int, body: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

        try:
            server = HTTPServer(
                (DEFAULT_LOOPBACK_HOST, session_obj.port), CallbackHandler
            )
            session_obj._server = server
            server.timeout = 1.0
            session_obj.started.set()

            deadline = time.time() + session_obj.timeout
            while not session_obj._stop.is_set():
                server.handle_request()
                if (
                    time.time() > deadline
                    and session_obj.status == AuthSessionStatus.PENDING
                ):
                    session_obj.status = AuthSessionStatus.EXPIRED
                    session_obj.error_code = "session_expired"
                    session_obj._stop.set()
                    break
        except Exception:
            pass
        finally:
            if session_obj._server:
                try:
                    session_obj._server.server_close()
                except Exception:
                    pass
                session_obj._server = None

    def get_session(self, session_id: str) -> AuthSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def check_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session is None:
            return {"error": "session_not_found"}
        if (
            session.status == AuthSessionStatus.PENDING
            and time.time() > session.expires_at
        ):
            session.status = AuthSessionStatus.EXPIRED
            session.error_code = "session_expired"
        return session.identity_summary

    def exchange_session(self, session_id: str) -> dict[str, Any]:  # noqa: PLR0911
        """Exchange captured code for token."""
        session = self.get_session(session_id)
        if session is None:
            return {"error": "session_not_found"}

        if (
            time.time() > session.expires_at
            and session.status == AuthSessionStatus.PENDING
        ):
            session.status = AuthSessionStatus.EXPIRED
            return {"error": "session_expired", "session_id": session_id}

        if session.status == AuthSessionStatus.EXCHANGED:
            return {
                "session_id": session_id,
                "status": "exchanged",
                "display_name": session.display_name,
                "provider": session.provider.value,
                "scopes": session.scopes,
            }

        # not ready or missing code → refuse
        if (
            session.status != AuthSessionStatus.CALLBACK_RECEIVED
            or session.code is None
        ):
            if (
                session.status == AuthSessionStatus.CALLBACK_RECEIVED
                and session.code is None
            ):
                session.status = AuthSessionStatus.FAILED
                session.error_code = "missing_code"
            return {
                "error": "session_not_ready",
                "session_id": session_id,
                "current_status": session.status.value,
            }

        # exchange code → token
        token_data: dict[str, Any] = {}
        try:
            token_data = session.provider_impl.exchange_code(
                session.code, session.redirect_uri
            )
        except Exception as e:
            session.status = AuthSessionStatus.FAILED
            session.error_code = "exchange_failed"
            session.error_message = str(e)
            return {
                "error": "exchange_failed",
                "session_id": session_id,
                "message": str(e),
            }

        if not token_data.get("access_token"):
            session.status = AuthSessionStatus.FAILED
            session.error_code = "no_access_token"
            session.error_message = f"Exchange returned no access token: {token_data.get('error', 'unknown')}"
            return {"error": "no_access_token", "session_id": session_id}

        self._complete_exchange(session, token_data)
        return {
            "session_id": session_id,
            "status": "exchanged",
            "provider": session.provider.value,
            "display_name": session.display_name,
            "scopes": session.scopes,
        }

    def _complete_exchange(
        self, session: AuthSession, token_data: dict[str, Any]
    ) -> None:
        session.status = AuthSessionStatus.EXCHANGED
        session.display_name = token_data.get("display_name", "")
        session.account_id = str(token_data.get("account_id", ""))
        session.email = token_data.get("email", "")
        store = DevFileTokenStore()
        store.put(
            provider=session.provider,
            token_bundle={
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", ""),
                "expires_in": token_data.get("expires_in", 3600),
                "account_id": token_data.get("account_id", ""),
                "display_name": token_data.get("display_name", ""),
                "email": token_data.get("email", ""),
            },
            scopes=token_data.get("scopes", session.scopes),
        )

    def exchange_manual_code(self, session_id: str, code: str) -> dict[str, Any]:
        """Exchange a manually provided code."""
        session = self.get_session(session_id)
        if session is None:
            return {"error": "session_not_found"}

        if (
            time.time() > session.expires_at
            and session.status == AuthSessionStatus.PENDING
        ):
            session.status = AuthSessionStatus.EXPIRED
            return {"error": "session_expired"}

        session.code = code
        session.callback_state = session.state
        session.status = AuthSessionStatus.CALLBACK_RECEIVED
        return self.exchange_session(session_id)

    def cancel_session(
        self, session_id: str, reason: str = "cancelled"
    ) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session is None:
            return {"error": "session_not_found"}

        session.status = AuthSessionStatus.CANCELLED
        session.error_code = reason
        self._stop_server(session)
        with self._lock:
            self._sessions.pop(session_id, None)

        logger.info(
            "auth session cancelled session_id=%s reason=%s", session_id, reason
        )
        return {"session_id": session_id, "status": "cancelled", "reason": reason}

    def _stop_server(self, session: AuthSession) -> None:
        session._stop.set()
        server = session._server
        if server is not None:
            try:
                server.server_close()
            except Exception:
                pass
            session._server = None

    def cleanup_sessions(self) -> list[str]:
        removed: list[str] = []
        with self._lock:
            for sid in list(self._sessions):
                session = self._sessions[sid]
                if (
                    session.status == AuthSessionStatus.PENDING
                    and time.time() > session.expires_at
                ):
                    session.status = AuthSessionStatus.EXPIRED
                if session.in_terminal_state():
                    self._stop_server(session)
                    self._sessions.pop(sid, None)
                    removed.append(sid)
        return removed

    def active_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.identity_summary for s in self._sessions.values()]

    def shutdown(self) -> None:
        with self._lock:
            for sid in list(self._sessions):
                session = self._sessions.pop(sid, None)
                if session:
                    session.status = AuthSessionStatus.CANCELLED
                    self._stop_server(session)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _callback_html(success: bool, message: str) -> str:
    color = "#22c55e" if success else "#ef4444"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Rig Relay Auth</title>"
        "<style>body{font-family:system-ui;display:flex;align-items:center;justify-content:center;"
        f"min-height:100vh;margin:0;background:#0d1117;color:#c9d1d9}}h1{{color:{color}}}"
        ".card{text-align:center;padding:32px;border:1px solid #30363d;border-radius:8px}"
        "</style></head><body><div class='card'>"
        f"<h1>{'&#10003;' if success else '&#10007;'}</h1>"
        f"<p>{message}</p></div></body></html>"
    )


_auth_manager: AuthSessionManager | None = None


def get_auth_session_manager() -> AuthSessionManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthSessionManager()
    return _auth_manager

#!/usr/bin/env python3
"""Rig Relay Desktop Shell — CLI wrapper.

The core implementation now lives in ``rig_relay.desktop.projection`` and
``rig_relay.desktop.websocket_server``. This script is the thin CLI wrapper.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import secrets
import threading
from typing import Any

from rig_relay import __version__
from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.config import VibeConfig
from rig_relay.core.config.harness_files import init_harness_files_manager
from rig_relay.core.hooks.config import load_hooks_from_fs
from rig_relay.core.logger import logger
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata
from rig_relay.desktop.chat_agent_adapter import ChatAgentAdapter
from rig_relay.desktop.chat_state import ChatMessage, ChatRole
from rig_relay.desktop.chat_store import ChatStore
from rig_relay.desktop.projection import build_projection
from rig_relay.desktop.websocket_server import (
    DEFAULT_PORT as DEFAULT_WS_PORT,
    ProjectionWebSocketServer,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"
FRONTEND_DIR = REPO_ROOT / "frontend" / "desktop"

MAX_MESSAGE_LENGTH = 4000


def _print_summary(projection: dict) -> None:
    """Print projection summary to stdout."""
    available = sum(1 for v in projection["source_status"].values() if v)
    total = len(projection["source_status"])
    print("Projection summary:")
    print(f"  App version: {projection['app_version']}")
    print(f"  Schema: {projection['schema_version']}")
    print(f"  Generated at: {projection['generated_at']}")
    print(f"  Data sources: {available}/{total} available")
    for name, avail in sorted(projection["source_status"].items()):
        status = "OK" if avail else "MISSING"
        print(f"    [{status}] {name}")
    print(f"  Warnings: {len(projection['warnings'])}")
    for w in projection["warnings"]:
        print(f"    ! {w}")
    print(f"  Available actions: {len(projection['read_only_actions'])}")
    print()


def load_data() -> dict:
    """Backward-compatible data loader — builds a projection dict."""
    return build_projection(build_root=BUILD_ROOT)


def _dry_run(ws_port: int = DEFAULT_WS_PORT) -> None:
    """Build and print projection summary without opening a window."""
    projection = build_projection(build_root=BUILD_ROOT)
    _print_summary(projection)
    print(f"WebSocket stream would listen on ws://127.0.0.1:{ws_port}")
    print("WebSocket auth/token gating: enabled (token auto-generated)")
    print()
    print(json.dumps(projection, indent=2))


def _run_ws_server(
    build_root: Path,
    host: str,
    port: int,
    token: str,
    chat_state_provider: Any | None = None,
    chat_message_handler: Any | None = None,
    loop_holder: list[asyncio.AbstractEventLoop] | None = None,
    server_holder: list[ProjectionWebSocketServer] | None = None,
) -> None:
    """Run the WebSocket projection stream in a background thread."""

    async def _start() -> None:
        loop = asyncio.get_running_loop()
        if loop_holder is not None:
            loop_holder[0] = loop

        server = ProjectionWebSocketServer(
            build_root=build_root,
            host=host,
            port=port,
            token=token,
            chat_state_provider=chat_state_provider,
            chat_message_handler=chat_message_handler,
        )
        if server_holder is not None:
            server_holder[0] = server

        await server.start()
        print(f"WebSocket projection stream on ws://{host}:{port}")
        print(f"Auth Token: {token}")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            await server.close()

    asyncio.run(_start())


def _generate_ws_token() -> str:
    """Generate a session token for the WebSocket projection stream."""
    return secrets.token_hex(32)


class CockpitAPI:
    """Read-only API exposed to JS bridge (fallback transport)."""

    def __init__(
        self,
        ws_token: str | None = None,
        ws_port: int | None = None,
        loop_holder: list[asyncio.AbstractEventLoop] | None = None,
        server_holder: list[ProjectionWebSocketServer] | None = None,
        mode: str = "runtime",
    ) -> None:
        self._store = ChatStore(chat_root=BUILD_ROOT / "desktop" / "chat")
        self._chat_state = self._store.load_state()
        self._ws_token = ws_token
        self._ws_port = ws_port
        self._loop_holder = loop_holder
        self._server_holder = server_holder
        self._mode = mode
        self._provider_windows: dict[str, Any] = {}

        if mode == "fixture":
            self._agent_loop = None
            self._adapter = None  # type: ignore
        else:
            # Initialize AgentLoop
            config = VibeConfig.load()
            hook_config_result = load_hooks_from_fs(config)
            entrypoint_metadata = build_entrypoint_metadata(
                agent_entrypoint="desktop",
                agent_version=__version__,
                client_name="rig_relay_desktop",
                client_version=__version__,
            )
            self._agent_loop = AgentLoop(
                config,
                agent_name=config.default_agent,
                enable_streaming=True,
                entrypoint_metadata=entrypoint_metadata,
                defer_heavy_init=True,
                hook_config_result=hook_config_result,
                workspace_root=Path.cwd(),
            )
            self._adapter = ChatAgentAdapter(
                agent_loop=self._agent_loop,
                store=self._store,
                on_update=self._notify_update,
            )

        # Log startup event
        self._store.append_event(
            "chat.backend.ready",
            note="Desktop API initialized with AgentLoop",
            backend_wired=True,
        )

        # Update state to reflect backend status
        self._chat_state.backend_wired = True
        self._store.save_state(self._chat_state)

    def _notify_update(self) -> None:
        """Trigger a WebSocket broadcast of the chat state update."""
        lh = self._loop_holder
        sh = self._server_holder
        if (
            lh is not None
            and lh[0] is not None
            and sh is not None
            and sh[0] is not None
        ):
            lh[0].call_soon_threadsafe(
                lambda: asyncio.create_task(sh[0].broadcast_chat_state_updated())
            )

    def get_projection(self) -> dict:
        projection = build_projection(build_root=BUILD_ROOT)
        try:
            from rig_relay.desktop.ralph_intents import build_ralph_projection
            projection["ralph"] = build_ralph_projection()
            from rig_relay.ralph.lifecycle_projection import build_lifecycle_projection
            projection["ralph_lifecycle"] = build_lifecycle_projection().model_dump(mode="json")
        except Exception:
            pass
        return projection

    def refresh_projection(self) -> dict:
        return build_projection(build_root=BUILD_ROOT)

    def get_available_actions(self) -> list[str]:
        from rig_relay.desktop.projection import READ_ONLY_ACTIONS

        return list(READ_ONLY_ACTIONS)

    def get_ws_config(self) -> dict:
        """Return WebSocket config (token, host, port) for frontend.

        Token is never printed in normal logs. Exposed only through
        the pywebview bridge to the frontend.
        """
        return {
            "token": self._ws_token or "",
            "host": "127.0.0.1",
            "port": self._ws_port or DEFAULT_WS_PORT,
        }

    def get_chat_state(self) -> dict:
        return self._chat_state.model_dump(mode="json")

    def open_provider_web(self, provider: str) -> dict:
        """Open a provider's web app in a pywebview companion window.

        pywebview IS a full browser (WebKit on macOS). It renders HTML,
        executes JavaScript, stores cookies. The companion window shares
        Safari's cookie jar on macOS — if the user is logged into the
        provider in Safari, the session carries over automatically.

        Provider keys: chatgpt, claude, gemini, deepseek, mistral, perplexity.
        Falls back to webbrowser.open() if pywebview window creation fails.
        """
        urls = {
            "chatgpt": "https://chatgpt.com",
            "claude": "https://claude.ai",
            "gemini": "https://gemini.google.com",
            "deepseek": "https://chat.deepseek.com",
            "mistral": "https://chat.mistral.ai",
            "perplexity": "https://perplexity.ai",
        }
        url = urls.get(provider)
        if not url:
            return {"status": "error", "message": f"Unknown provider: {provider}"}

        try:
            import webview  # type: ignore[import-untyped]
            webview.create_window(
                title=provider.title(),
                url=url,
                width=900,
                height=700,
                resizable=True,
                min_size=(400, 300),
            )
            return {"status": "opened", "provider": provider, "url": url}
        except Exception:
            import webbrowser
            webbrowser.open(url)
            return {"status": "opened", "provider": provider, "url": url, "fallback": "browser"}

    def send_to_provider(self, provider: str, text: str) -> dict:
        """Inject text into an open provider companion window's input."""
        import webview  # type: ignore[import-untyped]

        selectors = {
            "chatgpt": '#prompt-textarea',
            "claude": 'div[contenteditable="true"]',
            "gemini": 'div[contenteditable="true"]',
            "deepseek": '#chat-input, textarea',
            "mistral": 'textarea, div[contenteditable="true"]',
            "perplexity": 'textarea',
        }
        selector = selectors.get(provider, 'textarea, div[contenteditable="true"]')

        try:
            for w in webview.windows:
                wtitle = str(getattr(w, 'title', '')).lower()
                if provider in wtitle:
                    w.evaluate_js(f"""
                        (function() {{
                            const el = document.querySelector("{selector}");
                            if (!el) return "no_input";
                            if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {{
                                el.value = {json.dumps(text)};
                                el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                            }} else {{
                                el.innerText = {json.dumps(text)};
                                el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                            }}
                            return "ok";
                        }})()
                    """)
                    return {"status": "sent", "provider": provider}
            return {"status": "error", "message": f"No {provider} window found. Open with /provider {provider} first."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def read_from_provider(self, provider: str) -> dict:
        """Read the last assistant response from a provider companion window."""
        import webview  # type: ignore[import-untyped]

        selectors = {
            "chatgpt": '[data-message-author-role="assistant"]',
            "claude": '.font-claude-message, .prose',
            "gemini": '.model-response-text, .prose',
            "deepseek": '.ds-markdown, .markdown',
            "mistral": '.prose',
            "perplexity": '.prose, .markdown',
        }
        selector = selectors.get(provider, '.prose, .markdown')

        try:
            for w in webview.windows:
                wtitle = str(getattr(w, 'title', '')).lower()
                if provider in wtitle:
                    text = w.evaluate_js(f"""
                        (function() {{
                            const els = document.querySelectorAll("{selector}");
                            if (!els.length) return "";
                            const last = els[els.length - 1];
                            return last ? last.innerText : "";
                        }})()
                    """)
                    return {"status": "read", "provider": provider, "text": str(text or "")}
            return {"status": "error", "message": f"No {provider} window found"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_chat_message(
        self, text: str, client_message_id: str | None = None
    ) -> dict:
        if not text.strip():
            return {"error": "Empty message refused"}

        # Max length enforced
        if len(text) > MAX_MESSAGE_LENGTH:
            return {"error": "Message too long"}

        # Refuse if another response is active
        if self._adapter is not None and self._adapter.is_running:
            return {"error": "another_response_active"}

        # Idempotency check for client_message_id
        if client_message_id:
            for msg in self._chat_state.messages:
                if msg.metadata.get("client_message_id") == client_message_id:
                    return self.get_chat_state()

        # Generate a message ID if not provided
        msg_id = client_message_id or f"msg_{secrets.token_hex(8)}"

        # Immediate feedback: append user message synchronously
        user_msg = ChatMessage(
            role=ChatRole.USER,
            content=text,
            metadata={"client_message_id": client_message_id}
            if client_message_id
            else {"msg_id": msg_id},
        )
        self._chat_state.messages.append(user_msg)
        self._store.append_event("chat.message.created", message=user_msg)
        self._store.save_state(self._chat_state)

        # Schedule processing on the background loop (thread-safe)
        lh = self._loop_holder
        if lh is not None and lh[0] is not None and self._adapter is not None:
            asyncio.run_coroutine_threadsafe(
                self._adapter.process_message(text, msg_id), lh[0]
            )
        else:
            # If no loop, we just keep the user message but no assistant will respond
            logger.warning("No background loop for agent response")

        return self.get_chat_state()

    def clear_chat(self) -> dict:
        """JS-facing alias for clear_chat_view."""
        return self.clear_chat_view()

    def clear_chat_view(self) -> dict:
        self._chat_state.messages = []
        self._store.save_state(self._chat_state)
        self._store.append_event("chat.view.cleared")
        self._notify_update()
        return self.get_chat_state()

    def cancel_chat_response(self) -> dict:
        if self._adapter is None or not self._adapter.is_running:
            return {"error": "no_active_response"}

        if self._adapter.cancel():
            self._store.append_event("chat.response.cancelled")
            self._notify_update()
            return self.get_chat_state()

        return {"error": "cancel_failed"}

    def execute_intent(self, intent_request_json: str) -> dict:
        """JS-facing entry point for governed intents."""
        try:
            req = json.loads(intent_request_json)
        except json.JSONDecodeError:
            return {"error": "invalid_json"}
        return self.run_desktop_intent(req)

    def run_desktop_intent(self, intent_request: dict) -> dict:
        """Execute a governed desktop intent (read-only/dry-run only).

        Args:
            intent_request: Dict matching desktop_intent_request schema.

        Returns:
            Content-light intent result dict.
        """
        intent_name = intent_request.get("intent_name", "")

        if intent_name.startswith("ralph_"):
            from rig_relay.desktop.ralph_intents import execute_ralph_intent

            return execute_ralph_intent(
                intent_name=intent_name,
                params=intent_request.get("parameters", {}),
            )

        from rig_relay.desktop.intents import execute_desktop_intent

        result = execute_desktop_intent(
            request=intent_request, chat_state_provider=self.get_chat_state
        )

        # Route council/important intent results to chat adapter for visibility
        if result.get("status") == "completed" and self._adapter:
            intent_name = intent_request.get("intent_name", "")
            if intent_name == "council_consult":
                from rig_relay.core._receipt_events import CouncilFindingsEvent

                self._adapter.notify_council_findings(
                    CouncilFindingsEvent(
                        receipt_id=result.get("request_id", ""),
                        provider_count=len(result.get("providers", [])),
                        decision="proceed",
                    )
                )
            elif intent_name == "fleet_orchestrate":
                from rig_relay.core._receipt_events import DesktopIntentEvent

                self._adapter.notify_desktop_intent(
                    DesktopIntentEvent(
                        intent_id=result.get("intent_id", ""),
                        intent_kind=intent_name,
                        status=result.get("status", "unknown"),
                        summary=result.get("summary", "")[:120],
                    )
                )

        return result

    def mint_authorization_receipt_dev(
        self, action: str, ttl_seconds: int = 300, reason: str = ""
    ) -> dict:
        from rig_relay.desktop.authorization_receipts import mint_dev_receipt

        return mint_dev_receipt(action, ttl_seconds=ttl_seconds, reason=reason)

    def mint_authorization_receipt_local(
        self, action: str, ttl_seconds: int = 300, reason: str = ""
    ) -> dict:
        from rig_relay.desktop.authorization_receipts import mint_local_auth_receipt

        return mint_local_auth_receipt(action, ttl_seconds=ttl_seconds, reason=reason)

    def onboarding_required(self) -> dict:
        """Check if API key onboarding is needed.

        The frontend calls this on load. If True, the frontend
        shows the onboarding screen instead of the chat interface.
        """
        try:
            from rig_relay.core.config import VibeConfig

            VibeConfig.load()
            return {"onboarding_required": False}
        except Exception:
            return {"onboarding_required": True}

    def save_api_key(self, provider: str, api_key: str) -> dict:
        """Save a provider API key to the system keychain.

        Uses the macOS Keychain (via `keyring`). Falls back to `.env`
        file if keychain is unavailable.

        Args:
            provider: Provider name (e.g. "openai", "deepseek", "anthropic").
            api_key: The API key to store.

        Returns:
            Dict with success status, backend used, or error message.
        """
        if not provider or not api_key:
            return {"error": "Provider name and API key are required"}

        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }
        env_var = env_var_map.get(provider.lower())
        if not env_var:
            return {"error": f"Unknown provider: {provider}"}

        saved_to_keychain = False
        keychain_warning = ""
        try:
            import keyring

            keyring.set_password("rig-relay", env_var, api_key)
            saved_to_keychain = True
        except Exception as keyring_err:
            keychain_warning = str(keyring_err)

        import os as _os
        _os.environ[env_var] = api_key

        if saved_to_keychain:
            return {"status": "saved", "provider": provider, "backend": "keychain"}

        try:
            from rig_relay.core.paths import GLOBAL_ENV_FILE

            env_path = GLOBAL_ENV_FILE.path
            env_path.parent.mkdir(parents=True, exist_ok=True)

            existing = ""
            if env_path.is_file():
                existing = env_path.read_text(encoding="utf-8")

            lines = existing.splitlines()
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{env_var}="):
                    new_lines.append(f"{env_var}={api_key}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{env_var}={api_key}")

            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

            return {
                "status": "saved",
                "provider": provider,
                "backend": "env_file",
                "warning": (
                    f"OS keychain unavailable: {keychain_warning}. "
                    "Saved to .env file instead. "
                    "On Linux, install gnome-keyring or libsecret to enable keychain storage."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    _pending_oauth_window: dict[str, Any] | None = None

    def open_auth_window(self, auth_url: str, port: int, state_hash: str) -> dict:
        """Navigate the pywebview window to the OAuth provider's auth URL.

        The user authenticates in the app window. The provider redirects
        to the loopback server on localhost, which captures the callback.
        After the callback is received, the app navigates back to the
        main UI. This avoids leaving the app entirely.
        """
        if not auth_url:
            return {"error": "No auth URL provided"}

        # Start the loopback server in a background thread
        import threading

        callback_holder: list[dict] = []

        def _listen() -> None:
            from rig_relay.identity.oauth_loopback import start_loopback_server

            try:
                result = start_loopback_server(port, timeout=120.0)
                callback_holder.append(result)
            except Exception:
                callback_holder.append({"error": "server_error"})

        thread = threading.Thread(target=_listen, daemon=True)
        thread.start()

        self._pending_oauth_window = {
            "port": port,
            "state_hash": state_hash,
            "started_at": __import__("time").time(),
            "callback_thread": thread,
            "callback_holder": callback_holder,
        }

        return {"status": "navigating", "auth_url": auth_url}

    def poll_oauth_callback(self) -> dict:
        """Check if the OAuth callback has been received.

        The frontend calls this periodically after open_auth_window.
        Returns the captured code and state once available.
        """
        pending = self._pending_oauth_window
        if pending is None:
            return {"status": "no_pending_auth"}

        callback_holder = pending.get("callback_holder", [])
        expected_state_hash = pending.get("state_hash", "")

        if not callback_holder:
            return {"status": "waiting"}

        result = callback_holder[0]
        self._pending_oauth_window = None  # clear pending

        error = result.get("error")
        if error:
            return {"status": "error", "message": error}

        code = result.get("code", "")
        state = result.get("state", "")

        import hashlib

        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
        if expected_state_hash and state_hash != expected_state_hash:
            return {
                "status": "error",
                "message": "State mismatch (possible CSRF)",
            }

        return {"status": "completed", "code": code, "state": state}

    def close_auth_window(self) -> dict:
        """Cancel a pending OAuth flow and reset state."""
        self._pending_oauth_window = None
        return {"status": "cancelled"}


class _OnboardingAPI:
    """Minimal API for the onboarding flow when no API key is configured.

    The frontend calls these methods to check if onboarding is needed
    and to save the API key. Once saved, the user is prompted to restart.
    """

    def onboarding_required(self) -> dict:
        return {"onboarding_required": True}

    def save_api_key(self, provider: str, api_key: str) -> dict:
        """Save a provider API key to the OS-native credential store.

        Platform backends (via the `keyring` library):
          - macOS: Keychain
          - Windows: Credential Manager
          - Linux: Secret Service (libsecret/gnome-keyring)

        Falls back to `.env` file if no keyring backend is available.
        """
        if not provider or not api_key:
            return {"error": "Provider name and API key are required"}

        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }
        env_var = env_var_map.get(provider.lower())
        if not env_var:
            return {"error": f"Unknown provider: {provider}"}

        saved_to_keychain = False
        keychain_warning = ""
        try:
            import keyring
            keyring.set_password("rig-relay", env_var, api_key)
            saved_to_keychain = True
        except Exception as keyring_err:
            keychain_warning = str(keyring_err)

        import os as _os
        _os.environ[env_var] = api_key

        if saved_to_keychain:
            return {"status": "saved", "provider": provider, "backend": "keychain"}

        # Log warning to stderr so it shows in terminal
        import sys as _sys
        _sys.stderr.write(
            "\n"
            "[rig-relay] Warning: could not save API key to OS keychain.\n"
            f"[rig-relay] {keychain_warning}\n"
            "[rig-relay] Saved to ~/.rig/relay/.env instead.\n"
            "[rig-relay] Linux: install gnome-keyring or libsecret for keychain storage.\n"
            "[rig-relay] Windows/macOS: works out of the box.\n"
            "\n"
        )

        # Fallback: .env file
        try:
            from rig_relay.core.paths import GLOBAL_ENV_FILE

            env_path = GLOBAL_ENV_FILE.path
            env_path.parent.mkdir(parents=True, exist_ok=True)

            existing = ""
            if env_path.is_file():
                existing = env_path.read_text(encoding="utf-8")

            lines = existing.splitlines()
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{env_var}="):
                    new_lines.append(f"{env_var}={api_key}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{env_var}={api_key}")

            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

            return {
                "status": "saved",
                "provider": provider,
                "backend": "env_file",
                "warning": (
                    f"OS keychain unavailable: {keychain_warning}. "
                    "Saved to .env file instead. "
                    "On Linux, install gnome-keyring or libsecret to enable keychain storage."
                ),
            }
        except Exception as e:
            return {"error": str(e)}


def _open_window(
    ws_port: int | None, mode: str = "runtime", server_only: bool = False
) -> None:
    """Open pywebview window with optional WebSocket stream."""
    import time

    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        print(f"Frontend not found at {index_path}")
        return

    ws_token: str | None = None
    if ws_port is not None:
        ws_token = _generate_ws_token()

    loop_holder: list[asyncio.AbstractEventLoop] = [None]  # type: ignore[list-item]
    server_holder: list[ProjectionWebSocketServer] = [None]  # type: ignore[list-item]

    onboarding_mode = False
    try:
        api = CockpitAPI(
            ws_token=ws_token,
            ws_port=ws_port,
            loop_holder=loop_holder,
            server_holder=server_holder,
            mode=mode,
        )
    except Exception as exc:
        from rig_relay.core.config._settings import MissingAPIKeyError

        if isinstance(exc, MissingAPIKeyError):
            # Onboarding is deferred to the webview.
            onboarding_mode = True
            api = _OnboardingAPI()  # type: ignore[assignment]
        else:
            print(f"Failed to start desktop API: {exc}")
            print("Falling back to dry-run mode...")
            _dry_run(ws_port or DEFAULT_WS_PORT)
            return

    # WebSocket server runs in all modes — including onboarding —
    # so the frontend can call bridge methods (save_api_key, etc.)
    def _chat_dispatcher(action: str, **kwargs: Any) -> dict:
        if action == "send_chat_message":
            return api.send_chat_message(
                text=kwargs.get("text", ""),
                client_message_id=kwargs.get("client_message_id"),
            )
        if action == "clear_chat":
            return api.clear_chat_view()
        if action == "cancel_chat_response":
            return api.cancel_chat_response()
        return {"error": f"Unknown action: {action}"}

    if ws_port is not None:
        ws_thread = threading.Thread(
            target=_run_ws_server,
            args=(
                BUILD_ROOT,
                "127.0.0.1",
                ws_port,
                ws_token,
                api.get_chat_state if not onboarding_mode else (lambda: {"messages": []}),
                _chat_dispatcher,
                loop_holder,
                server_holder,
            ),
            daemon=True,
        )
        ws_thread.start()
        time.sleep(0.5)

    if server_only:
        print("Server-only mode. WebSocket is running.")
        print(f"URL: file://{index_path}")
        print(f"WebSocket Token: {ws_token}")
        print("Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            return

    try:
        import webview  # type: ignore[import-untyped]
    except ImportError:
        print("pywebview not available. Install with: uv add pywebview")
        print("Running dry-run instead...")
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return
    if not hasattr(webview, "__version__"):  # type: ignore[reportAttributeAccessIssue]
        webview.__version__ = "6.2.1"  # type: ignore[reportAttributeAccessIssue]

    # Read and inject WS config + onboarding flag.
    # We inject a <base> tag so relative CSS/JS paths resolve from
    # the frontend/desktop directory when loading via html= in pywebview.
    onboarding_flag = "true" if onboarding_mode else "false"
    config_script = (
        '<script>'
        f'window.__RIG_RELAY_WS_CONFIG__ = {{'
        f'host: "127.0.0.1", port: {ws_port or DEFAULT_WS_PORT}, '
        f'token: "{ws_token or ""}", onboarding: {onboarding_flag}'
        f'}};'
        '</script>'
    )
    base_tag = f'<base href="file://{FRONTEND_DIR}/">'
    index_html = index_path.read_text(encoding="utf-8")
    # Inject base tag after <head>, config before </body>
    index_html = index_html.replace('<head>', f'<head>{base_tag}')
    index_html = index_html.replace('</body>', f'{config_script}\n</body>')

    webview.create_window(
        title="Rig Relay",
        html=index_html,
        js_api=api,
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start(gui="cocoa")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rig Relay Desktop Shell")
    parser.add_argument(
        "--mode",
        choices=["runtime", "fixture"],
        default="runtime",
        help="Run in runtime mode (real agents) or fixture mode (sample data).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print projection, exit without opening a window.",
    )
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Start the WebSocket server and print the URL, but don't open a window.",
    )
    parser.add_argument(
        "--no-ws",
        action="store_true",
        help="Disable the WebSocket projection stream (use pywebview JS bridge only).",
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=DEFAULT_WS_PORT,
        help=f"Port for WebSocket projection stream (default: {DEFAULT_WS_PORT}).",
    )
    return parser.parse_args(argv)


def _load_keychain_keys() -> None:
    """Load API keys from the OS credential store into the environment.

    Platform backends:
      - macOS: Keychain
      - Windows: Credential Manager
      - Linux: Secret Service (libsecret/gnome-keyring)

    Runs before VibeConfig.load() so that configured providers
    are detected without the user needing a .env file.
    Best-effort: failures are silently ignored.
    """
    import os

    env_vars = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
    ]
    for env_var in env_vars:
        if env_var in os.environ:
            continue  # Already set, don't override
        try:
            import keyring

            value = keyring.get_password("rig-relay", env_var)
            if value:
                os.environ[env_var] = value
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    init_harness_files_manager("user", "project")

    # Load keys from system keychain before config
    _load_keychain_keys()

    ws_port: int | None = None if args.no_ws else args.ws_port

    if args.dry_run:
        _dry_run(ws_port or DEFAULT_WS_PORT)
        return 0

    _open_window(ws_port, mode=args.mode, server_only=args.server_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

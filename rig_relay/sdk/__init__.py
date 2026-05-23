"""rig_relay.sdk — Protocol & SDK spine v1 client."""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import Any
from uuid import uuid4

from rig_relay.sdk._models import (
    RigAuthCapabilityCheck,
    RigAuthReceiptRef,
    RigAuthRefusal,
    RigAuthStatus,
    RigCapabilityDecision,
    RigClient,
    RigProviderLiveAuthStatus,
    RigReceiptRef,
    RigRefusal,
    RigRunResult,
    RigStatus,
    RigTransportBudgets,
    RigVerdict,
    compute_sha256,
)

__all__ = [
    "RigAuthCapabilityCheck",
    "RigAuthReceiptRef",
    "RigAuthRefusal",
    "RigAuthStatus",
    "RigCapabilityDecision",
    "RigClient",
    "RigReceiptRef",
    "RigRefusal",
    "RigRunResult",
    "RigStatus",
    "RigTransportBudgets",
    "RigVerdict",
    "check_auth_capability",
    "check_github_provider_status",
    "check_google_workspace_status",
    "compute_sha256",
    "detect_refresh_needed",
    "evaluate_github_capability",
    "evaluate_google_workspace_capability",
    "evaluate_sdk_capability",
    "get_auth_receipt_ref",
    "get_auth_refusal",
    "get_auth_status",
    "get_credential_store_ref_hash",
    "get_sdk_status",
    "invoke_tool",
    "list_tools",
    "run_github_live_read",
    "run_google_workspace_live_read",
    "run_mcp_read_only",
    "send_a2a_local_task",
    "send_acp_message",
    "start_acp_session",
    "start_agent_chat",
]


def _uuid() -> str:
    return str(uuid4())


def get_sdk_status() -> RigStatus:
    return RigClient().status()


def evaluate_sdk_capability(capability_id: str) -> RigCapabilityDecision:
    return RigClient().evaluate_capability(capability_id)


def run_mcp_read_only(tool_name: str, trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).run_mcp_read_only(tool_name, trace_id)


def start_acp_session(trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).start_acp_session(trace_id)


def send_a2a_local_task(task_id: str, agent_id: str, trace_id: str) -> RigRunResult:
    return RigClient(trace_id=trace_id).send_a2a_local_task(task_id, agent_id, trace_id)


# ── Auth API ──


_SUPPORTED_AUTH_SURFACES = frozenset({
    "github",
    "google_workspace",
    "mcp",
    "acp",
    "a2a",
    "sdk",
})

_CAPABILITY_CREDENTIAL_MAP: dict[str, str] = {
    "github": "github",
    "google_workspace": "google",
    "mcp.mutation": "mcp",
    "acp.mutation": "acp",
}

_REFRESH_THRESHOLD_SECONDS = 300


def _get_credential_store() -> Any:
    """Lazy-load the credential store to avoid breaking SDK import hygiene."""
    mod = import_module("rig_relay.identity._credential_store")
    return mod.get_credential_store()


def _is_credential_store_available(store: Any) -> bool:
    mod = import_module("rig_relay.identity._credential_store")
    KeychainBackedCredentialStore = mod.KeychainBackedCredentialStore

    if isinstance(store, KeychainBackedCredentialStore):
        return store._available
    import sys

    if sys.platform == "darwin":
        return False
    return False


def get_auth_status(provider_id: str) -> RigAuthStatus:
    trace_id = _uuid()
    store = _get_credential_store()
    store_ref_hash = store.compute_credential_store_ref_hash(provider_id)

    metadatas = store.list_metadata(provider_id)
    active = [m for m in metadatas if m.status == "active"]

    if not active:
        return RigAuthStatus(
            provider_id=provider_id,
            auth_capable=False,
            auth_status="unauthenticated",
            refresh_needed=False,
            credential_store_ref_hash=store_ref_hash,
            capability_id=provider_id,
            trace_id=trace_id,
        )

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    expired = False
    refresh = False
    for m in active:
        if m.expires_at:
            try:
                exp = datetime.fromisoformat(m.expires_at)
                if exp <= now:
                    expired = True
                elif (exp - now).total_seconds() < _REFRESH_THRESHOLD_SECONDS:
                    refresh = True
            except (ValueError, TypeError):
                pass

    if expired or refresh:
        status = "expired"
        refresh_needed = True
    else:
        status = "authenticated"
        refresh_needed = False

    return RigAuthStatus(
        provider_id=provider_id,
        auth_capable=True,
        auth_status=status,
        refresh_needed=refresh_needed,
        credential_store_ref_hash=store_ref_hash,
        capability_id=provider_id,
        trace_id=trace_id,
    )


def check_auth_capability(capability_id: str) -> RigAuthCapabilityCheck:
    trace_id = _uuid()
    store = _get_credential_store()
    store_available = _is_credential_store_available(store)

    supported = (
        capability_id in _CAPABILITY_CREDENTIAL_MAP
        or capability_id in _SUPPORTED_AUTH_SURFACES
    )
    requires_credentials = capability_id in _CAPABILITY_CREDENTIAL_MAP

    if requires_credentials and not store_available:
        verdict = "DEFERRED"
    elif not supported:
        verdict = "REFUSED"
    elif requires_credentials:
        metas = store.list_metadata(
            _CAPABILITY_CREDENTIAL_MAP.get(capability_id, capability_id)
        )
        if metas:
            verdict = "ALLOWED"
        else:
            verdict = "DEFERRED"
    else:
        verdict = "ALLOWED"

    return RigAuthCapabilityCheck(
        capability_id=capability_id,
        supported=supported,
        requires_credentials=requires_credentials,
        credential_store_available=store_available,
        verdict=verdict,
        trace_id=trace_id,
    )


def detect_refresh_needed(provider_id: str) -> bool:
    status = get_auth_status(provider_id)
    return status.refresh_needed


def get_auth_refusal(capability_id: str) -> RigAuthRefusal:
    trace_id = _uuid()
    receipt_id = _uuid()
    return RigAuthRefusal(
        refusal_code="auth_required",
        reason=f"Authentication required for capability '{capability_id}'",
        capability_id=capability_id,
        trace_id=trace_id,
        receipt_id=receipt_id,
    )


def get_auth_receipt_ref(receipt_id: str) -> RigAuthReceiptRef:
    trace_id = _uuid()
    status = get_auth_status("sdk")
    return RigAuthReceiptRef(
        receipt_id=receipt_id,
        surface="sdk",
        trace_id=trace_id,
        auth_state_hash=compute_sha256(f"{status.provider_id}:{status.auth_status}"),
        credential_store_ref_hash=status.credential_store_ref_hash,
        verdict=status.auth_status,
    )


def get_credential_store_ref_hash(provider_id: str) -> str:
    store = _get_credential_store()
    return store.compute_credential_store_ref_hash(provider_id)


def check_github_provider_status(trace_id: str = "") -> RigRunResult:
    return asyncio.run(RigClient().check_github_provider_status(trace_id))


def run_github_live_read(
    capability_id: str,
    token: str = "",
    repository_owner: str = "",
    repository_name: str = "",
    trace_id: str = "",
) -> RigRunResult:
    return asyncio.run(
        RigClient().run_github_live_read(
            capability_id, token, repository_owner, repository_name, trace_id
        )
    )


def evaluate_github_capability(
    capability_id: str, trace_id: str = ""
) -> RigCapabilityDecision:
    return asyncio.run(RigClient().evaluate_github_capability(capability_id, trace_id))


def check_google_workspace_status(trace_id: str = "") -> RigRunResult:
    return asyncio.run(RigClient().check_google_workspace_status(trace_id))


def run_google_workspace_live_read(
    capability_id: str, token: str = "", subject_hash: str = "", trace_id: str = ""
) -> RigRunResult:
    return asyncio.run(
        RigClient().run_google_workspace_live_read(
            capability_id, token, subject_hash, trace_id
        )
    )


def evaluate_google_workspace_capability(
    capability_id: str, trace_id: str = ""
) -> RigCapabilityDecision:
    return asyncio.run(
        RigClient().evaluate_google_workspace_capability(capability_id, trace_id)
    )


# ── Live-Auth Provider Status ──


_REFRESH_THRESHOLD_SECONDS_LIVE = 300


def get_provider_live_auth_status(provider_id: str) -> RigProviderLiveAuthStatus:
    trace_id = _uuid()
    receipt_id = _uuid()
    capability_id = f"provider.{provider_id}.live_auth"

    if provider_id == "github":
        return _get_github_live_auth_status(trace_id, receipt_id, capability_id)
    if provider_id == "google_workspace":
        return _get_google_live_auth_status(trace_id, receipt_id, capability_id)

    store = _get_credential_store()
    store_available = _is_credential_store_available(store)
    store_ref_hash = store.compute_credential_store_ref_hash(provider_id)

    return RigProviderLiveAuthStatus(
        provider_id=provider_id,
        configured=False,
        auth_status="unconfigured",
        refusal_code="unknown_provider",
        credential_store_available=store_available,
        credential_store_ref_hash=store_ref_hash,
        capability_id=capability_id,
        trace_id=trace_id,
        receipt_id=receipt_id,
    )


def _get_github_live_auth_status(
    trace_id: str, receipt_id: str, capability_id: str
) -> RigProviderLiveAuthStatus:
    provider_id = "github"
    store = _get_credential_store()
    store_available = _is_credential_store_available(store)
    store_ref_hash = store.compute_credential_store_ref_hash(provider_id)

    configured = False
    auth_mode = "none"
    auth_status = "unconfigured"
    scopes_or_permissions: list[str] = []
    token_expires_at: str | None = None
    refresh_needed = False
    refusal_code: str | None = "live_auth_not_configured"

    try:
        live_mod = import_module("rig_relay.integrations.github_provider._live_auth")
        live_config = live_mod.GitHubLiveAuthConfig.from_environment()
        configured = live_config.is_configured()
    except (ImportError, AttributeError):
        pass

    if not configured:
        try:
            auth_mod = import_module(
                "rig_relay.integrations.github_provider._auth_state_store"
            )
            auth_state = auth_mod.read_auth_state()
            if str(auth_state.auth_mode) not in {"", "none"}:
                configured = True
                auth_mode = str(auth_state.auth_mode)
                auth_status = str(auth_state.auth_status).lower()
                scopes_or_permissions = list(auth_state.scopes_or_permissions)
                token_expires_at = auth_state.expires_at or None
                refusal_code = None
        except (ImportError, AttributeError, FileNotFoundError, ValueError):
            pass
    else:
        auth_status = "unauthenticated"
        refusal_code = None

    if not configured:
        return RigProviderLiveAuthStatus(
            provider_id=provider_id,
            configured=False,
            auth_status="unconfigured",
            refusal_code=refusal_code,
            credential_store_available=store_available,
            credential_store_ref_hash=store_ref_hash,
            capability_id=capability_id,
            trace_id=trace_id,
            receipt_id=receipt_id,
        )

    if token_expires_at:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        try:
            exp = datetime.fromisoformat(token_expires_at)
            if exp <= now:
                auth_status = "expired"
                refresh_needed = True
            elif (exp - now).total_seconds() < _REFRESH_THRESHOLD_SECONDS_LIVE:
                refresh_needed = True
        except (ValueError, TypeError):
            pass

    return RigProviderLiveAuthStatus(
        provider_id=provider_id,
        configured=True,
        auth_mode=auth_mode,
        auth_status=auth_status,
        credential_store_available=store_available,
        credential_store_ref_hash=store_ref_hash,
        token_expires_at=token_expires_at,
        refresh_needed=refresh_needed,
        scopes_or_permissions=scopes_or_permissions,
        capability_id=capability_id,
        trace_id=trace_id,
        receipt_id=receipt_id,
    )


def _get_google_live_auth_status(
    trace_id: str, receipt_id: str, capability_id: str
) -> RigProviderLiveAuthStatus:
    provider_id = "google_workspace"
    store = _get_credential_store()
    store_available = _is_credential_store_available(store)
    store_ref_hash = store.compute_credential_store_ref_hash(provider_id)

    configured = False
    auth_mode = "none"
    auth_status = "unconfigured"
    scopes_or_permissions: list[str] = []
    refusal_code: str | None = "live_auth_not_configured"

    try:
        live_mod = import_module("rig_relay.integrations.google_workspace._live_auth")
        live_config = live_mod.GoogleLiveAuthConfig()
        configured = live_config.is_configured()
    except (ImportError, AttributeError):
        pass

    if not configured:
        try:
            auth_mod = import_module(
                "rig_relay.integrations.google_workspace._auth_state_store"
            )
            auth_state = auth_mod.read_workspace_auth_state()
            if str(auth_state.auth_mode) not in {"", "none"}:
                configured = True
                auth_mode = str(auth_state.auth_mode)
                auth_status = str(auth_state.auth_status).lower()
                scopes_or_permissions = [g.scope_id for g in auth_state.scope_grants]
                refusal_code = None
        except (ImportError, AttributeError, FileNotFoundError, ValueError):
            pass
    else:
        auth_status = "unauthenticated"
        refusal_code = None

    if not configured:
        return RigProviderLiveAuthStatus(
            provider_id=provider_id,
            configured=False,
            auth_status="unconfigured",
            refusal_code=refusal_code,
            credential_store_available=store_available,
            credential_store_ref_hash=store_ref_hash,
            capability_id=capability_id,
            trace_id=trace_id,
            receipt_id=receipt_id,
        )

    return RigProviderLiveAuthStatus(
        provider_id=provider_id,
        configured=True,
        auth_mode=auth_mode,
        auth_status=auth_status,
        credential_store_available=store_available,
        credential_store_ref_hash=store_ref_hash,
        scopes_or_permissions=scopes_or_permissions,
        capability_id=capability_id,
        trace_id=trace_id,
        receipt_id=receipt_id,
    )


def validate_live_auth_setup(provider_id: str) -> dict[str, object]:
    issues: list[str] = []
    if provider_id == "github":
        return _validate_github_live_auth_setup(issues)
    if provider_id == "google_workspace":
        return _validate_google_live_auth_setup(issues)
    return {
        "ready": False,
        "issues": [f"Unknown provider: {provider_id}"],
        "recommendation": "Supported providers: github, google_workspace",
    }


def _validate_github_live_auth_setup(issues: list[str]) -> dict[str, object]:
    from pathlib import Path

    app_id: int | None = None
    installation_id: int | None = None
    private_key_path: str | None = None

    try:
        live_mod = import_module("rig_relay.integrations.github_provider._live_auth")
        live_config = live_mod.GitHubLiveAuthConfig.from_environment()
        app_id = live_config.app_id
        installation_id = live_config.installation_id
        private_key_path = live_config.private_key_path
    except (ImportError, AttributeError):
        pass

    if app_id is None:
        issues.append("Missing app_id (set RIG_GITHUB_APP_ID)")
    if installation_id is None:
        issues.append("Missing installation_id (set RIG_GITHUB_INSTALLATION_ID)")
    if private_key_path is None:
        issues.append("Missing private_key_path (set RIG_GITHUB_PRIVATE_KEY_PATH)")
    elif not Path(private_key_path).exists():
        issues.append(f"private_key_path does not exist: {private_key_path}")

    ready = len(issues) == 0
    recommendation = (
        "All required fields configured"
        if ready
        else "Set the required environment variables for GitHub App auth"
    )
    return {"ready": ready, "issues": issues, "recommendation": recommendation}


def _validate_google_live_auth_setup(issues: list[str]) -> dict[str, object]:
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None

    try:
        live_mod = import_module("rig_relay.integrations.google_workspace._live_auth")
        live_config = live_mod.GoogleLiveAuthConfig()
        client_id = live_config.client_id or None
        client_secret = live_config.client_secret or None
        redirect_uri = live_config.redirect_uri or None
    except (ImportError, AttributeError):
        pass

    if not client_id:
        issues.append("Missing client_id (set RIG_GOOGLE_CLIENT_ID)")
    if not client_secret:
        issues.append("Missing client_secret (set RIG_GOOGLE_CLIENT_SECRET)")
    if not redirect_uri:
        issues.append("Missing redirect_uri (set RIG_GOOGLE_REDIRECT_URI)")

    ready = len(issues) == 0
    recommendation = (
        "All required fields configured"
        if ready
        else "Set the required environment variables for Google OAuth"
    )
    return {"ready": ready, "issues": issues, "recommendation": recommendation}


# ── Wired SDK operations (AgentLoop, ToolManager, ACP, A2A) ──


def start_agent_chat(prompt: str, trace_id: str = "") -> RigRunResult:
    """Run a one-shot agent chat through the real AgentLoop."""
    return asyncio.run(RigClient().async_start_agent_chat(prompt, trace_id))


def list_tools(trace_id: str = "") -> RigRunResult:
    """List all tools from the real tool manager."""
    return asyncio.run(RigClient().async_list_tools(trace_id))


def invoke_tool(
    tool_name: str, args: dict[str, Any] | None = None, trace_id: str = ""
) -> RigRunResult:
    """Invoke a tool through the real tool manager."""
    return asyncio.run(RigClient().async_invoke_tool(tool_name, args, trace_id))


def send_acp_message(session_id: str, message: str, trace_id: str = "") -> RigRunResult:
    """Send a message to an ACP session backed by a real AgentLoop."""
    return asyncio.run(
        RigClient().async_send_acp_message(session_id, message, trace_id)
    )

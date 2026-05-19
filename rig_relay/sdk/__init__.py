"""rig_relay.sdk — Protocol & SDK spine v1 client."""

from __future__ import annotations

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
    "compute_sha256",
    "detect_refresh_needed",
    "evaluate_sdk_capability",
    "get_auth_receipt_ref",
    "get_auth_refusal",
    "get_auth_status",
    "get_credential_store_ref_hash",
    "get_sdk_status",
    "run_mcp_read_only",
    "send_a2a_local_task",
    "start_acp_session",
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

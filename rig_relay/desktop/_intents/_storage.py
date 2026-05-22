from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any
import uuid

import jsonschema

from rig_relay.governance.decisions import GovernanceDecisionKind


def execute_desktop_intent(
    request: dict[str, Any],
    chat_state_provider: Any | None = None,
    progress_emitter: Any | None = None,
    trace_id: str = "",
) -> dict[str, Any]:
    """Execute a desktop intent request and return a content-light result.

    Args:
        request: The validated intent request dict.
        chat_state_provider: Optional callable returning dict of chat state.
        progress_emitter: Optional callable accepting a dict to broadcast
            progress events over WebSocket. Content-light only.
        trace_id: Optional trace correlation ID carried from the inbound
            BridgeMessage.

    Returns:
        Intent result dict (schema-validated, content-light).
    """
    from rig_relay.desktop.bridge_refusals import build_accepted_intent_lifecycle_event
    from rig_relay.desktop.intent_audit import emit_received, emit_result
    from rig_relay.desktop.progress_events import (
        EVENT_OPERATION_COMPLETED,
        EVENT_OPERATION_FAILED,
        EVENT_OPERATION_REFUSED,
        EVENT_OPERATION_STARTED,
        build_progress_event,
    )

    intent_name = str(request.get("intent_name", ""))
    intent_id = str(request.get("intent_id", f"intent_{uuid.uuid4().hex[:12]}"))

    # Emit received event
    emit_received(request)

    # Helper to emit progress event if emitter is available
    _emit_seq = 0

    def _emit_progress(
        event_type: str, phase: str, status: str = "running", **extra: Any
    ) -> None:
        if progress_emitter is None:
            return
        nonlocal _emit_seq
        _emit_seq += 1
        event = build_progress_event(
            operation_id=intent_id or intent_name,
            event_type=event_type,
            phase=phase,
            status=status,
            source="intents",
            intent_id=intent_id,
            sequence=_emit_seq,
            message=extra.get("message", phase),
            result_kind=extra.get("result_kind", ""),
            projection_refresh_recommended=extra.get(
                "projection_refresh_recommended", False
            ),
            warnings=extra.get("warnings", []),
        )
        result = progress_emitter(event.model_dump(mode="json", exclude_none=True))
        if inspect.iscoroutine(result):
            asyncio.create_task(result)

    # Unified dispatch: classify intent and execute
    match _classify_intent(intent_name):
        case "phase1_protected":
            _emit_progress(
                EVENT_OPERATION_STARTED,
                phase="phase_1_protected",
                status="running",
                message=f"Starting Phase 1 protected intent '{intent_name}'",
                result_kind=PHASE_1_ENABLED.get(intent_name, ""),
            )
            result = _handle_phase_1_protected_intent(
                intent_name,
                intent_id,
                request.get("parameters", {}),
                request.get("authorization_receipt"),
                request.get("local_action_envelope"),
            )
            status = result.get("status", "failed")
            lifecycle_event_type = (
                "intent_completed" if status == "completed" else "intent_dispatched"
            )
            result["_bridge_lifecycle_event"] = build_accepted_intent_lifecycle_event(
                event_type=lifecycle_event_type,
                intent_name=intent_name,
                intent_id=intent_id,
                trace_id=trace_id or request.get("trace_id", ""),
                inbound_message_id=request.get("parent_message_id", ""),
                safe_summary_hash=hashlib.sha256(
                    result.get("summary", "").encode()
                ).hexdigest()[:16],
            )
            status = result.get("status", "failed")
            event = (
                EVENT_OPERATION_COMPLETED
                if status == "completed"
                else (
                    EVENT_OPERATION_REFUSED
                    if status == "refused"
                    else EVENT_OPERATION_FAILED
                )
            )
            _emit_progress(
                event,
                phase="phase_1_protected",
                status=status,
                message=result.get(
                    "summary", f"Protected intent '{intent_name}': {status}"
                ),
                result_kind=result.get("result_kind", ""),
                projection_refresh_recommended=result.get(
                    "projection_refresh_recommended", False
                ),
                warnings=result.get("warnings", []),
            )
            emit_result(result)
            return result

        case "protected":
            from rig_relay.governance.local_action_gate import require_signed_envelope

            params = request.get("parameters", {})
            gate_decision = require_signed_envelope(
                action=intent_name,
                payload=params,
                required_capability=intent_name,
                envelope=request.get("local_action_envelope"),
            )
            if not gate_decision.decision == GovernanceDecisionKind.ALLOWED:
                reason_msg = (
                    gate_decision.reasons[0].message
                    if gate_decision.reasons
                    else "blocked"
                )
                result = _build_result(
                    intent_name,
                    intent_id,
                    "refused",
                    authorization_required=True,
                    error_code="local_action_envelope_required",
                    summary=f"Protected intent '{intent_name}' requires signed envelope: {reason_msg}",
                )
            else:
                result = _build_result(
                    intent_name,
                    intent_id,
                    "refused",
                    authorization_required=True,
                    error_code=PROTECTED_INTENTS.get(intent_name, "unknown"),
                    summary=f"Protected intent '{intent_name}' refused. Not enabled for receipt-gated execution.",
                )
            _emit_progress(
                EVENT_OPERATION_REFUSED,
                phase="protected_check",
                status="refused",
                message=f"Protected intent '{intent_name}' refused",
            )
            emit_result(result)
            return result

        case "allowed":
            _emit_progress(
                EVENT_OPERATION_STARTED,
                phase=intent_name,
                status="running",
                message=f"Starting intent '{intent_name}'",
                result_kind=ALLOWED_INTENTS[intent_name]
                .get("description", "")
                .split(".")[0],
            )

            from rig_relay.governance.service_state import get_capability_gate

            gate = get_capability_gate()
            allowed, reason = gate.is_allowed(intent_name)
            if not allowed:
                result = _build_result(
                    intent_name,
                    intent_id,
                    "refused",
                    error_code="capability_gated",
                    summary=f"Capability gated: {reason}. Profile must be unlocked.",
                    extra_fields={"profile_required": True, "gating_reason": reason},
                )
                _emit_progress(
                    EVENT_OPERATION_REFUSED,
                    phase="capability_gate",
                    status="refused",
                    message=f"Capability gated: {intent_name}",
                )
                emit_result(result)
                return result

            result = _execute_allowed_intent(
                intent_name,
                intent_id,
                request.get("parameters", {}),
                chat_state_provider,
            )
            result_status = result.get("status", "failed")
            lifecycle_event_type = (
                "intent_completed"
                if result_status == "completed"
                else "intent_dispatched"
            )
            result["_bridge_lifecycle_event"] = build_accepted_intent_lifecycle_event(
                event_type=lifecycle_event_type,
                intent_name=intent_name,
                intent_id=intent_id,
                trace_id=trace_id or request.get("trace_id", ""),
                inbound_message_id=request.get("parent_message_id", ""),
                safe_summary_hash=hashlib.sha256(
                    result.get("summary", "").encode()
                ).hexdigest()[:16],
            )
            _emit_progress(
                EVENT_OPERATION_COMPLETED
                if result_status == "completed"
                else EVENT_OPERATION_FAILED,
                phase=intent_name,
                status=result_status,
                message=result.get(
                    "summary", f"Intent '{intent_name}': {result_status}"
                ),
                result_kind=result.get("result_kind", ""),
                projection_refresh_recommended=result.get(
                    "projection_refresh_recommended", False
                ),
                warnings=result.get("warnings", []),
            )
            emit_result(result)
            return result

        case _:  # unsupported
            result = _build_result(
                intent_name,
                intent_id,
                "refused",
                error_code="unsupported_intent",
                summary=f"Unknown intent '{intent_name}'.",
            )
            _emit_progress(
                EVENT_OPERATION_REFUSED,
                phase="intent_check",
                status="refused",
                message=f"Unknown intent '{intent_name}'",
            )
            emit_result(result)
            return result


def _handle_phase_1_protected_intent(
    intent_name: str,
    intent_id: str,
    params: dict[str, Any],
    receipt: dict[str, Any] | None,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle a Phase 1 protected intent with authorization gate."""
    valid, reason, receipt_meta = validate_protected_intent_authorization(
        intent_name, receipt
    )
    if not valid:
        result = _build_result(
            intent_name,
            intent_id,
            "refused",
            authorization_required=True,
            error_code="authorization_failed",
            summary=f"Protected intent '{intent_name}' refused: {reason}",
        )
        from rig_relay.desktop.intent_audit import emit_result

        emit_result(result)
        return result

    from rig_relay.governance.local_action_gate import require_signed_envelope

    gate_decision = require_signed_envelope(
        action=intent_name,
        payload=params,
        required_capability=intent_name,
        envelope=envelope,
    )
    if gate_decision.decision != GovernanceDecisionKind.ALLOWED:
        reason_msg = (
            gate_decision.reasons[0].message
            if gate_decision.reasons
            else "local action envelope required"
        )
        result = _build_result(
            intent_name,
            intent_id,
            "refused",
            authorization_required=True,
            error_code="local_action_envelope_required",
            summary=f"Protected intent '{intent_name}' refused: {reason_msg}",
        )
        from rig_relay.desktop.intent_audit import emit_result

        emit_result(result)
        return result

    # Merge receipt metadata (hashes/action) for audit trail
    if receipt_meta:
        params.update(receipt_meta)

    match intent_name:
        case "checkpoint.commit":
            result = _execute_checkpoint_commit(intent_id, params, receipt)
        case "lease_cleanup.archive":
            result = _execute_lease_cleanup_archive(intent_id, params)
        case _:
            result = _build_result(
                intent_name,
                intent_id,
                "refused",
                error_code="protected_intent_not_enabled",
                summary=f"Protected intent '{intent_name}' is not enabled in this phase.",
            )

    # Ensure receipt metadata is in the result for emit_result audit
    if receipt_meta:
        result.update(receipt_meta)

    from rig_relay.desktop.intent_audit import emit_result

    emit_result(result)
    return result


def _execute_mint_authorization_receipt_dev(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from rig_relay.desktop.authorization_receipts import mint_dev_receipt

        action = str(params.get("action", ""))
        ttl_seconds = int(params.get("ttl_seconds", 300))
        reason = str(params.get("reason", ""))
        result = mint_dev_receipt(action, ttl_seconds=ttl_seconds, reason=reason)
        status = "completed" if result.get("valid") else "refused"
        return _build_result(
            "mint_authorization_receipt_dev",
            intent_id,
            status,
            result_kind="authorization_receipt",
            summary=(
                f"Dev receipt mint {status}: {action or 'unknown'} "
                f"({str(result.get('receipt_sha256', ''))[:16]})"
            ),
            output_refs=[str(result["receipt_ref"])]
            if result.get("receipt_ref")
            else [],
            warnings=list(result.get("warnings", [])),
        )
    except Exception as e:
        return _build_result(
            "mint_authorization_receipt_dev",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Dev receipt mint failed: {e}",
        )


def _execute_mint_authorization_receipt_local(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from rig_relay.desktop.authorization_receipts import mint_local_auth_receipt

        action = str(params.get("action", ""))
        ttl_seconds = int(params.get("ttl_seconds", 300))
        reason = str(params.get("reason", ""))
        result = mint_local_auth_receipt(action, ttl_seconds=ttl_seconds, reason=reason)
        status = "completed" if result.get("valid") else "refused"
        return _build_result(
            "mint_authorization_receipt_local",
            intent_id,
            status,
            result_kind="authorization_receipt",
            summary=(
                f"Local auth receipt mint {status}: {action or 'unknown'} "
                f"({str(result.get('receipt_sha256', ''))[:16]})"
            ),
            output_refs=[str(result["receipt_ref"])]
            if result.get("receipt_ref")
            else [],
            warnings=list(result.get("warnings", [])),
        )
    except Exception as e:
        return _build_result(
            "mint_authorization_receipt_local",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Local auth receipt mint failed: {e}",
        )


def _execute_inspect_authorization_receipt(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    receipt = params.get("authorization_receipt")
    if not isinstance(receipt, dict):
        return _build_result(
            "inspect_authorization_receipt",
            intent_id,
            "refused",
            error_code="invalid_receipt",
            summary="Authorization receipt is required for inspection.",
        )

    from rig_relay.desktop.authorization_receipts import inspect_receipt

    inspected = inspect_receipt(receipt)
    status = "completed" if inspected["valid"] else "refused"
    return _build_result(
        "inspect_authorization_receipt",
        intent_id,
        status,
        result_kind="authorization_receipt",
        summary=(
            f"Receipt {inspected['status']}: {inspected['action'] or 'unknown'} "
            f"({str(inspected.get('receipt_sha256', ''))[:16]})"
        ),
        warnings=list(inspected.get("warnings", [])),
    )


def _execute_checkpoint_commit(
    intent_id: str, params: dict[str, Any], receipt: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute a checkpoint.commit intent.

    Delegates to the Checkpoint tool. The authorization receipt has already
    been validated by _handle_phase_1_protected_intent.
    Returns content-light result.
    """
    try:
        message = params.get("message", "Desktop intent checkpoint")
        include_paths = params.get("include_paths", [])
        session_id = params.get("session_id", "desktop")
        task_id = params.get("task_id", intent_id)
        allow_partial = params.get("allow_partial", False)

        if not include_paths:
            return _build_result(
                "checkpoint.commit",
                intent_id,
                "refused",
                error_code="missing_parameters",
                summary="Checkpoint refused: include_paths is required.",
            )

        from rig_relay.core.tools.base import BaseToolState, InvokeContext
        from rig_relay.core.tools.builtins.checkpoint import (
            Checkpoint,
            CheckpointArgs,
            CheckpointToolConfig,
        )

        config = CheckpointToolConfig(store_root=DEFAULT_BUILD_ROOT / "coordination")
        tool = Checkpoint(config_getter=lambda: config, state=BaseToolState())
        args = CheckpointArgs(
            session_id=session_id,
            task_id=task_id,
            message=message,
            include_paths=include_paths,
            allow_partial=allow_partial,
            authorization_receipt=json.dumps(receipt) if receipt else None,
        )
        ctx = InvokeContext(
            tool_call_id=f"intent-{intent_id}",
            session_dir=DEFAULT_BUILD_ROOT / "sessions" / "desktop",
        )

        import asyncio

        from rig_relay.core.tools.builtins.checkpoint import CheckpointResult

        async def _collect() -> CheckpointResult:
            async for event in tool.run(args, ctx):
                if isinstance(event, CheckpointResult):
                    return event
            raise RuntimeError("Checkpoint returned no result")

        result = asyncio.run(_collect())

        if result.ok and result.commit_sha:
            return _build_result(
                "checkpoint.commit",
                intent_id,
                "completed",
                result_kind="checkpoint",
                summary=(
                    f"Checkpoint committed: {result.commit_sha[:12]}. "
                    f"{len(result.files_committed)} files. "
                    f"sha256: {result.artifact_sha256}"
                ),
                output_refs=[result.artifact_sha256] if result.artifact_sha256 else [],
                warnings=result.warnings,
            )
        return _build_result(
            "checkpoint.commit",
            intent_id,
            "refused",
            error_code="checkpoint_refused",
            summary=f"Checkpoint refused: {result.refusal_reason or result.message}",
            warnings=result.warnings,
        )
    except Exception as e:
        return _build_result(
            "checkpoint.commit",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Checkpoint failed: {e}",
        )


def _execute_lease_cleanup_archive(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Execute a lease_cleanup.archive intent.

    Delegates to the cleanup_leases module's run_cleanup with archive=True.
    The authorization receipt has already been validated.
    Returns content-light result.
    """
    try:
        from rig_relay.coordination.cleanup_leases import run_cleanup

        coordination_root = params.get(
            "coordination_root", DEFAULT_BUILD_ROOT / "coordination"
        )
        if isinstance(coordination_root, str):
            coordination_root = Path(coordination_root)
        max_age_seconds = params.get("max_age_seconds", 86400)

        # Run cleanup with archive=True, confirm=True (authorized)
        result = run_cleanup(
            coordination_root=coordination_root,
            max_age_seconds=max_age_seconds,
            dry_run=False,
            archive=True,
            confirm=True,
        )

        stats = result.get("stats", {})
        errors = result.get("errors", [])
        total_cleanable = stats.get("total_cleanable", 0)
        action = result.get("action", "none")

        summary_parts = [
            f"Lease cleanup archive: {action}.",
            f"{total_cleanable} entries processed.",
        ]
        if errors:
            summary_parts.append(f"{len(errors)} errors.")

        return _build_result(
            "lease_cleanup.archive",
            intent_id,
            "completed" if not errors else "partial",
            result_kind="lease_cleanup",
            summary=" ".join(summary_parts),
            output_refs=[],
            projection_refresh_recommended=True,
            warnings=errors,
        )
    except Exception as e:
        return _build_result(
            "lease_cleanup.archive",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Lease cleanup archive failed: {e}",
        )


def _execute_identity_status(intent_id: str) -> dict[str, Any]:
    """Return identity provider statuses. Content-light — no raw tokens."""
    try:
        from rig_relay.identity.token_store import DevFileTokenStore

        store = DevFileTokenStore()
        statuses = store.all_statuses()
        any_signed_in = any(s.get("status") == "signed_in" for s in statuses.values())

        providers_summary = ", ".join(
            f"{k}={v.get('status', 'unknown')}" for k, v in statuses.items()
        )

        return _build_result(
            "identity_status",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"Identity: {providers_summary}.",
            extra_fields={"providers": statuses, "any_signed_in": any_signed_in},
        )
    except Exception as e:
        return _build_result(
            "identity_status",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Identity status failed: {e}",
        )


def _execute_sign_in_start(
    intent_id: str, provider_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Start OAuth sign-in flow for a provider.

    Backend creates an auth session with a non-blocking async loopback
    listener. Returns auth_url and auth_session_id to frontend.
    The frontend opens auth_url in browser; backend-owned loopback
    listener captures the callback independently.
    """
    try:
        from rig_relay.identity.auth_session_manager import get_auth_session_manager
        from rig_relay.identity.models import IdentityProviderKind

        if provider_name == "github":
            from rig_relay.identity.github import GitHubIdentityProvider

            provider = GitHubIdentityProvider()
            provider_kind = IdentityProviderKind.GITHUB
        elif provider_name == "google":
            from rig_relay.identity.google import GoogleIdentityProvider

            provider = GoogleIdentityProvider()
            provider_kind = IdentityProviderKind.GOOGLE
        else:
            return _build_result(
                f"sign_in_{provider_name}_start",
                intent_id,
                "failed",
                error_code="invalid_provider",
                summary=f"Unknown provider: {provider_name}",
            )

        if not provider.is_configured():
            return _build_result(
                f"sign_in_{provider_name}_start",
                intent_id,
                "completed",
                result_kind="identity_status",
                summary=f"Sign in with {provider_name}: not configured. "
                f"Set credentials and retry.",
                extra_fields={
                    "auth_url": "",
                    "auth_session_id": "",
                    "provider": provider_name,
                    "status": "pending",
                    "configured": False,
                    "warning": f"{provider_name} credentials not configured",
                },
            )

        mgr = get_auth_session_manager()
        session, auth_url = mgr.start_session(
            provider_kind=provider_kind, provider_impl=provider
        )

        return _build_result(
            f"sign_in_{provider_name}_start",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"Sign in with {provider_name}: auth URL generated. "
            f"Scopes: {', '.join(session.scopes)}.",
            extra_fields={
                "auth_url": auth_url,
                "auth_session_id": session.session_id,
                "redirect_uri": session.redirect_uri,
                "provider": provider_name,
                "status": "pending",
                "configured": True,
                "scopes": session.scopes,
            },
        )
    except Exception as e:
        return _build_result(
            f"sign_in_{provider_name}_start",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Sign in with {provider_name} failed: {e}",
        )


def _execute_sign_out_provider(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Sign out of an identity provider. Removes local metadata/token."""
    try:
        from rig_relay.identity.models import IdentityProviderKind
        from rig_relay.identity.token_store import DevFileTokenStore

        provider_name = str(params.get("provider", ""))
        if not provider_name:
            return _build_result(
                "sign_out_provider",
                intent_id,
                "failed",
                error_code="missing_parameter",
                summary="sign_out_provider requires 'provider' parameter (github or google).",
            )

        provider_kind = IdentityProviderKind(provider_name)
        store = DevFileTokenStore()
        existed = store.delete(provider_kind)

        if existed:
            return _build_result(
                "sign_out_provider",
                intent_id,
                "completed",
                result_kind="identity_status",
                summary=f"Signed out of {provider_name}. Local metadata removed.",
                extra_fields={"provider": provider_name, "signed_out": True},
            )
        return _build_result(
            "sign_out_provider",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"Already signed out of {provider_name}.",
            extra_fields={"provider": provider_name, "signed_out": False},
        )
    except Exception as e:
        return _build_result(
            "sign_out_provider",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Sign out failed: {e}",
        )


def _execute_sign_in_poll(
    intent_id: str, provider_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Check auth session status and exchange code if callback received.

    Does NOT start a second loopback listener. The backend auth session
    already owns the listener. This intent checks status and exchanges
    a captured code for tokens.
    """
    try:
        from rig_relay.identity.auth_session_manager import get_auth_session_manager

        auth_session_id = str(params.get("auth_session_id", ""))
        if not auth_session_id:
            return _build_result(
                f"sign_in_{provider_name}_poll",
                intent_id,
                "failed",
                error_code="missing_parameters",
                summary=f"auth_session_id is required. Call sign_in_{provider_name}_start first.",
            )

        mgr = get_auth_session_manager()
        session = mgr.get_session(auth_session_id)
        if session is None:
            return _build_result(
                f"sign_in_{provider_name}_poll",
                intent_id,
                "failed",
                error_code="session_not_found",
                summary=f"Auth session {auth_session_id} not found.",
            )

        if session.provider.value != provider_name:
            return _build_result(
                f"sign_in_{provider_name}_poll",
                intent_id,
                "failed",
                error_code="provider_mismatch",
                summary=f"Session provider {session.provider.value} "
                f"does not match {provider_name}.",
            )

        match session.status:
            case "pending" if _is_expired(session):
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "failed",
                    error_code="session_expired",
                    summary=f"{provider_name} sign-in timed out. Start a new session.",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "status": "expired",
                        "provider": provider_name,
                    },
                )

            case "pending":
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "completed",
                    result_kind="identity_status",
                    summary=f"Waiting for {provider_name} callback...",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "status": "pending",
                        "provider": provider_name,
                    },
                )

            case "callback_received":
                result = mgr.exchange_session(auth_session_id)
                if result.get("error"):
                    return _build_result(
                        f"sign_in_{provider_name}_poll",
                        intent_id,
                        "failed",
                        error_code=result.get("error", "exchange_failed"),
                        summary=f"{provider_name} token exchange failed: "
                        f"{result.get('message', result.get('error', ''))}",
                        extra_fields={
                            "auth_session_id": auth_session_id,
                            "status": "failed",
                            "provider": provider_name,
                        },
                    )
                from rig_relay.identity.token_store import DevFileTokenStore

                store = DevFileTokenStore()
                statuses = store.all_statuses()
                provider_status = statuses.get(provider_name, {})
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "completed",
                    result_kind="identity_status",
                    summary=f"Signed in to {provider_name} as "
                    f"{result.get('display_name', 'unknown')}.",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "provider": provider_name,
                        "status": provider_status.get("status", "signed_in"),
                        "display_name": result.get("display_name", ""),
                        "scopes": result.get("scopes", []),
                    },
                    projection_refresh_recommended=True,
                )

            case "exchanged":
                from rig_relay.identity.token_store import DevFileTokenStore

                store = DevFileTokenStore()
                statuses = store.all_statuses()
                provider_status = statuses.get(provider_name, {})
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "completed",
                    result_kind="identity_status",
                    summary=f"Already signed in to {provider_name}.",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "provider": provider_name,
                        "status": "signed_in",
                        "display_name": session.display_name,
                        "scopes": session.scopes,
                    },
                    projection_refresh_recommended=True,
                )

            case "failed":
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "failed",
                    error_code=session.error_code or "auth_failed",
                    summary=f"{provider_name} sign-in failed: "
                    f"{session.error_message or session.error_code}",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "status": "failed",
                        "provider": provider_name,
                        "error_code": session.error_code,
                    },
                )

            case "cancelled" | "expired":
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "failed",
                    error_code=session.status,
                    summary=f"{provider_name} sign-in {session.status}.",
                    extra_fields={
                        "auth_session_id": auth_session_id,
                        "status": session.status,
                        "provider": provider_name,
                    },
                )

            case _:
                return _build_result(
                    f"sign_in_{provider_name}_poll",
                    intent_id,
                    "failed",
                    error_code="unknown_status",
                    summary=f"{provider_name} sign-in unexpected status: {session.status}.",
                )

    except Exception as e:
        return _build_result(
            f"sign_in_{provider_name}_poll",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"{provider_name} sign-in poll failed: {e}",
        )


def _execute_sign_in_cancel(
    intent_id: str, provider_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Cancel a pending auth session. Cleans up loopback listener."""
    try:
        from rig_relay.identity.auth_session_manager import get_auth_session_manager

        auth_session_id = str(params.get("auth_session_id", ""))
        if not auth_session_id:
            return _build_result(
                f"sign_in_{provider_name}_cancel",
                intent_id,
                "failed",
                error_code="missing_parameters",
                summary="auth_session_id is required.",
            )

        mgr = get_auth_session_manager()
        result = mgr.cancel_session(auth_session_id, reason="user_cancelled")
        if result.get("error"):
            return _build_result(
                f"sign_in_{provider_name}_cancel",
                intent_id,
                "failed",
                error_code=result["error"],
                summary=f"Cancel failed: {result['error']}",
            )

        return _build_result(
            f"sign_in_{provider_name}_cancel",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"{provider_name} sign-in cancelled.",
            extra_fields={
                "auth_session_id": auth_session_id,
                "status": "cancelled",
                "provider": provider_name,
            },
        )
    except Exception as e:
        return _build_result(
            f"sign_in_{provider_name}_cancel",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Cancel failed: {e}",
        )


def _execute_sign_in_manual_code(
    intent_id: str, provider_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Exchange a manually provided authorization code."""
    try:
        from rig_relay.identity.auth_session_manager import get_auth_session_manager

        auth_session_id = str(params.get("auth_session_id", ""))
        manual_code = str(params.get("manual_code", ""))
        if not auth_session_id or not manual_code:
            return _build_result(
                f"sign_in_{provider_name}_manual_code",
                intent_id,
                "failed",
                error_code="missing_parameters",
                summary="Both auth_session_id and manual_code are required.",
            )

        mgr = get_auth_session_manager()
        result = mgr.exchange_manual_code(auth_session_id, manual_code)
        if result.get("error"):
            return _build_result(
                f"sign_in_{provider_name}_manual_code",
                intent_id,
                "failed",
                error_code=result.get("error", "exchange_failed"),
                summary=f"Manual code exchange failed: "
                f"{result.get('message', result.get('error', ''))}",
            )

        return _build_result(
            f"sign_in_{provider_name}_manual_code",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"Signed in to {provider_name} via manual code.",
            extra_fields={
                "auth_session_id": auth_session_id,
                "provider": provider_name,
                "status": "signed_in",
                "display_name": result.get("display_name", ""),
                "scopes": result.get("scopes", []),
            },
            projection_refresh_recommended=True,
        )
    except Exception as e:
        return _build_result(
            f"sign_in_{provider_name}_manual_code",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Manual code exchange failed: {e}",
        )


def _is_expired(session: Any) -> bool:
    import time

    return getattr(session, "is_expired", False) or (
        hasattr(session, "expires_at")
        and time.time() > getattr(session, "expires_at", 0)
    )


def _execute_telemetry_consent_status(
    intent_id: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return current telemetry consent status. Content-light."""
    try:
        from pathlib import Path

        from rig_relay.identity.consent_store import ConsentStore
        from rig_relay.identity.state_paths import consent_state_root

        _params = params or {}
        state_root_raw = _params.get("state_root", None)
        state_root = Path(state_root_raw) if state_root_raw else None
        consent_root = consent_state_root(root=state_root) if state_root else None
        store = ConsentStore(store_root=consent_root)
        summary = store.summary()
        consent_id = summary.get("consent_id", "")
        status = summary.get("status", "not_requested")
        scopes = summary.get("scopes", [])
        granted_at = summary.get("granted_at", "")
        revoked_at = summary.get("revoked_at", "")

        from rig_relay.identity.telemetry_consent import has_commercial_dataset_license

        record = store.get()
        has_commercial = has_commercial_dataset_license(record)

        return _build_result(
            "telemetry_consent_status",
            intent_id,
            "completed",
            result_kind="telemetry_consent",
            summary=f"Consent status: {status}. Scopes: {len(scopes)}.",
            extra_fields={
                "consent_id": consent_id,
                "status": status,
                "scopes": scopes,
                "granted_at": granted_at,
                "revoked_at": revoked_at,
                "has_commercial_license": has_commercial,
            },
        )
    except Exception as e:
        return _build_result(
            "telemetry_consent_status",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Consent status failed: {e}",
        )


def _execute_telemetry_consent_grant(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Grant telemetry consent for specified scopes.

    Records consent locally. Does not upload automatically.
    Content-light: no raw tokens, email, prompts, code, or output.
    """
    try:
        from pathlib import Path

        from rig_relay.identity.consent_store import ConsentStore
        from rig_relay.identity.state_paths import consent_state_root
        from rig_relay.identity.telemetry_consent import (
            TelemetryConsentScope,
            grant_consent,
        )

        raw_scopes: list[str] = params.get(
            "scopes",
            [
                "usage_metrics",
                "content_light_bundles",
                "crash_reports",
                "coordination_metrics",
                "tool_refinement_metrics",
            ],
        )
        scopes = [
            TelemetryConsentScope(s)
            for s in raw_scopes
            if s in {m.value for m in TelemetryConsentScope}
        ]
        subject_hash = str(params.get("subject_hash", ""))
        provider = str(params.get("provider", "local"))
        state_root_raw = params.get("state_root", None)
        state_root = Path(state_root_raw) if state_root_raw else None
        consent_root = consent_state_root(root=state_root) if state_root else None

        from rig_relay.identity.telemetry_consent import (
            TelemetryConsentScope,
            has_commercial_dataset_license,
        )

        record = grant_consent(
            subject_hash=subject_hash, provider=provider, scopes=scopes or None
        )
        if has_commercial_dataset_license(record):
            record.warnings = record.warnings or []
            record.warnings.append("commercial_dataset_license_granted")
        store = ConsentStore(store_root=consent_root)
        store.save(record)

        return _build_result(
            "telemetry_consent_grant",
            intent_id,
            "completed",
            result_kind="telemetry_consent",
            summary=f"Consent granted. Status: granted. Scopes: {len(record.scopes)}.",
            extra_fields={
                "consent_id": record.consent_id,
                "status": record.status.value,
                "scopes": [s.value for s in record.scopes],
                "granted_at": record.granted_at,
            },
        )
    except Exception as e:
        return _build_result(
            "telemetry_consent_grant",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Consent grant failed: {e}",
        )


def _execute_telemetry_consent_revoke(
    intent_id: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Revoke telemetry consent. Does not delete history."""
    try:
        from pathlib import Path

        from rig_relay.identity.consent_store import ConsentStore
        from rig_relay.identity.state_paths import consent_state_root
        from rig_relay.identity.telemetry_consent import revoke_consent

        _params = params or {}
        state_root_raw = _params.get("state_root", None)
        state_root = Path(state_root_raw) if state_root_raw else None
        consent_root = consent_state_root(root=state_root) if state_root else None
        store = ConsentStore(store_root=consent_root)
        existing = store.get()
        record = revoke_consent(existing)
        store.save(record)

        return _build_result(
            "telemetry_consent_revoke",
            intent_id,
            "completed",
            result_kind="telemetry_consent",
            summary=f"Consent revoked. Previous status was: {existing.status.value}.",
            extra_fields={
                "consent_id": record.consent_id,
                "status": record.status.value,
                "revoked_at": record.revoked_at,
            },
        )
    except Exception as e:
        return _build_result(
            "telemetry_consent_revoke",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Consent revoke failed: {e}",
        )


def _execute_provider_status(intent_id: str) -> dict[str, Any]:
    """Return content-light provider summaries."""
    try:
        from rig_relay.providers import provider_status as ps

        summary = ps()
        configured = summary.get("configured", 0)
        total = summary.get("total", 0)
        return _build_result(
            "provider_status",
            intent_id,
            "completed",
            result_kind="provider_status",
            summary=f"Providers: {configured}/{total} configured.",
            extra_fields={
                "total": total,
                "configured": configured,
                "providers": summary.get("providers", []),
            },
        )
    except Exception as e:
        return _build_result(
            "provider_status",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Provider status check failed: {e}",
        )


def _execute_telemetry_upload_google(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Upload a telemetry bundle to Google Drive.

    Requires Google sign-in with drive.file scope. Uploads to the
    configured telemetry folder first. Optionally also copies to
    the user's personal Drive root.
    """
    try:
        from pathlib import Path

        from rig_relay.evidence.google_drive_upload import upload_bundle

        bundle_path_str = str(params.get("bundle_path", ""))
        target_folder_id = str(params.get("target_folder_id", "")) or None
        copy_to_personal = bool(params.get("copy_to_personal", False))

        # Find the latest bundle if no path given
        if not bundle_path_str:
            repo_root = Path(__file__).resolve().parent.parent.parent
            bundle_dir = repo_root / ".build" / "rig-relay" / "telemetry-bundles"
            if not bundle_dir.is_dir():
                return _build_result(
                    "telemetry_upload_google",
                    intent_id,
                    "failed",
                    error_code="no_bundle_found",
                    summary="No telemetry bundles found. Create one first.",
                )
            bundles = sorted(
                bundle_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if not bundles:
                return _build_result(
                    "telemetry_upload_google",
                    intent_id,
                    "failed",
                    error_code="no_bundle_found",
                    summary="No telemetry bundles found. Create one first.",
                )
            latest_bundle = bundles[0]
            # Find the zip file inside the bundle directory
            zip_files = list(latest_bundle.rglob("*.zip"))
            if zip_files:
                bundle_path = zip_files[0]
            else:
                return _build_result(
                    "telemetry_upload_google",
                    intent_id,
                    "failed",
                    error_code="no_zip_in_bundle",
                    summary=f"No zip found in latest bundle: {latest_bundle.name}",
                )
        else:
            bundle_path = Path(bundle_path_str)
            if not bundle_path.is_file():
                return _build_result(
                    "telemetry_upload_google",
                    intent_id,
                    "failed",
                    error_code="bundle_not_found",
                    summary=f"Bundle not found: {bundle_path}",
                )

        # Upload to the predefined telemetry folder
        import asyncio

        result = asyncio.run(upload_bundle(bundle_path, target_folder_id))

        warnings: list[str] = []
        uploads = [result]

        # Copy to personal Drive if requested
        if copy_to_personal:
            try:
                personal_result = asyncio.run(
                    upload_bundle(bundle_path, target_folder_id="root")
                )
                uploads.append(personal_result)
                warnings.append(
                    f"Personal copy uploaded: {personal_result.get('file_id', '')[:16]}..."
                )
            except Exception as e:
                warnings.append(f"Personal copy failed: {e}")

        file_id = result.get("file_id", "")
        web_link = result.get("web_view_link", "")

        return _build_result(
            "telemetry_upload_google",
            intent_id,
            "completed",
            result_kind="drive_upload",
            summary=(
                f"Uploaded {bundle_path.name} to Google Drive. "
                f"{'Personal copy also uploaded. ' if copy_to_personal else ''}"
                f"File ID: {file_id[:16] if file_id else 'unknown'}..."
            ),
            extra_fields={
                "file_id": file_id,
                "file_name": result.get("name", bundle_path.name),
                "size_bytes": result.get("size_bytes", 0),
                "web_view_link": web_link,
                "uploads": uploads,
            },
            warnings=warnings,
        )
    except Exception as e:
        return _build_result(
            "telemetry_upload_google",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Google Drive upload failed: {e}",
        )


def _execute_provider_onboarding_save_key(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Save a provider API key locally. Returns fingerprint only — never raw key."""
    try:
        provider_name = str(params.get("provider", ""))
        api_key = str(params.get("api_key", ""))

        if not provider_name or not api_key:
            return _build_result(
                "provider_onboarding_save_key",
                intent_id,
                "refused",
                error_code="missing_parameter",
                summary="Both 'provider' and 'api_key' are required.",
            )

        from rig_relay.providers import provider_onboarding_save_key as save_key

        result = save_key(provider_name, api_key)
        status = result.get("status", "failed")
        if status == "completed":
            return _build_result(
                "provider_onboarding_save_key",
                intent_id,
                "completed",
                result_kind="provider_onboarding",
                summary=f"API key saved for {provider_name.title()}.",
                extra_fields={
                    "provider": provider_name,
                    "key_source": result.get("key_source", ""),
                    "key_fingerprint": result.get("key_fingerprint", ""),
                },
            )
        return _build_result(
            "provider_onboarding_save_key",
            intent_id,
            "failed",
            error_code="save_failed",
            summary=result.get("summary", "Save failed."),
            warnings=result.get("warnings", []),
        )
    except Exception as e:
        return _build_result(
            "provider_onboarding_save_key",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Save key failed: {e}",
        )


def _execute_provider_onboarding_remove_key(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Remove a locally stored provider API key."""
    try:
        provider_name = str(params.get("provider", ""))
        if not provider_name:
            return _build_result(
                "provider_onboarding_remove_key",
                intent_id,
                "refused",
                error_code="missing_parameter",
                summary="'provider' is required.",
            )

        from rig_relay.providers import provider_onboarding_remove_key as remove_key

        result = remove_key(provider_name)
        return _build_result(
            "provider_onboarding_remove_key",
            intent_id,
            "completed",
            result_kind="provider_onboarding",
            summary=result.get("summary", f"Key removed for {provider_name.title()}."),
            extra_fields={"provider": provider_name, "key_source": "missing"},
        )
    except Exception as e:
        return _build_result(
            "provider_onboarding_remove_key",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Remove key failed: {e}",
        )


def _execute_provider_health_check(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Check provider health — content-light, no network by default."""
    try:
        provider_name = str(params.get("provider", "")) or None
        network_allowed = bool(params.get("network_allowed", False))

        from rig_relay.providers import provider_health_check as health_check

        result = health_check(
            provider_name=provider_name, network_allowed=network_allowed
        )
        providers = result.get("providers", [])
        configured_count = sum(1 for p in providers if p.get("configured", False))
        total = len(providers)

        return _build_result(
            "provider_health_check",
            intent_id,
            "completed",
            result_kind="provider_status",
            summary=f"Health check: {configured_count}/{total} providers configured.",
            extra_fields={
                "total": total,
                "configured": configured_count,
                "providers": providers,
                "network_allowed": network_allowed,
            },
        )
    except Exception as e:
        return _build_result(
            "provider_health_check",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Health check failed: {e}",
        )


def _execute_worktree_list(intent_id: str) -> dict[str, Any]:
    try:
        from rig_relay.coordination.worktree_manager import WorktreeManager

        repo_root = Path.cwd()
        mgr = WorktreeManager(repo_root)
        records = mgr.list_worktrees()

        if not records:
            return _build_result(
                "worktree_list",
                intent_id,
                "completed",
                result_kind="summary",
                summary="No worktrees found.",
            )

        lines = [f"{r.workspace_id}: {r.status} @ {r.path}" for r in records]
        return _build_result(
            "worktree_list",
            intent_id,
            "completed",
            result_kind="summary",
            summary="\n".join(lines),
        )
    except Exception as e:
        return _build_result(
            "worktree_list",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Worktree list failed: {e}",
        )


def _execute_worktree_create(
    intent_id: str, workspace_id: str = "", branch_name: str = ""
) -> dict[str, Any]:
    if not workspace_id or not branch_name:
        return _build_result(
            "worktree_create",
            intent_id,
            "refused",
            error_code="missing_parameters",
            summary="workspace_id and branch_name are required.",
        )
    try:
        import subprocess

        repo_root = Path.cwd()

        # Pre-flight check: refuse if working tree is dirty
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if status.stdout.strip():
            dirty_count = len(status.stdout.strip().split("\n"))
            return _build_result(
                "worktree_create",
                intent_id,
                "refused",
                error_code="dirty_working_tree",
                summary=f"Working tree has {dirty_count} dirty files. Commit or stash before creating a worktree.",
            )

        from rig_relay.coordination.worktree_manager import WorktreeManager

        mgr = WorktreeManager(repo_root)
        result = mgr.create(workspace_id=workspace_id, branch_name=branch_name)

        if result.status == "created":
            return _build_result(
                "worktree_create",
                intent_id,
                "completed",
                result_kind="summary",
                summary=f"Created worktree '{workspace_id}' at {result.record.path if result.record else '—'}.",
            )
        return _build_result(
            "worktree_create",
            intent_id,
            "failed",
            error_code="creation_failed",
            summary=f"Failed to create worktree: {result.refusal_reason or result.status}.",
        )
    except Exception as e:
        return _build_result(
            "worktree_create",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Worktree create failed: {e}",
        )


def _execute_worktree_remove(
    intent_id: str, workspace_id: str = "", force: bool = False
) -> dict[str, Any]:
    if not workspace_id:
        return _build_result(
            "worktree_remove",
            intent_id,
            "refused",
            error_code="missing_parameters",
            summary="workspace_id is required.",
        )
    try:
        from rig_relay.coordination.worktree_manager import WorktreeManager

        repo_root = Path.cwd()
        mgr = WorktreeManager(repo_root)
        result = mgr.remove(workspace_id=workspace_id, force=force)

        if result.status == "removed":
            return _build_result(
                "worktree_remove",
                intent_id,
                "completed",
                summary=f"Removed worktree '{workspace_id}'.",
            )
        return _build_result(
            "worktree_remove",
            intent_id,
            "failed",
            error_code="removal_failed",
            summary=f"Failed to remove worktree: {result.refusal_reason or result.status}.",
        )
    except Exception as e:
        return _build_result(
            "worktree_remove",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Worktree remove failed: {e}",
        )


def _execute_fleet_queue_snapshot(intent_id: str) -> dict[str, Any]:
    try:
        from rig_relay.coordination.fleet_queue import FleetQueue

        coord_root = DEFAULT_BUILD_ROOT / "coordination"
        queue_path = coord_root / "queue" / "events.jsonl"

        if not queue_path.exists():
            return _build_result(
                "fleet_queue_snapshot",
                intent_id,
                "completed",
                result_kind="summary",
                summary="No fleet queue events file found. Queue is empty.",
            )

        queue = FleetQueue(queue_path)
        snapshot = queue.list_items()
        status_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(snapshot.status_counts.items())
        )
        return _build_result(
            "fleet_queue_snapshot",
            intent_id,
            "completed",
            result_kind="summary",
            summary=f"Fleet queue: {snapshot.total_count} items ({status_str}).",
        )
    except Exception as e:
        return _build_result(
            "fleet_queue_snapshot",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Fleet queue snapshot failed: {e}",
        )


def _execute_workspace_init(intent_id: str, workspace_id: str = "") -> dict[str, Any]:
    """Bootstrap an uninitialized workspace.

    Checks git repo state, suggests a unique workspace_id, and validates
    that the repo is in a workable state for creating a new worktree.
    """
    try:
        import subprocess

        cwd = Path.cwd()

        # Check we're in a git repo
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(cwd),
            )
        except subprocess.CalledProcessError:
            return _build_result(
                "workspace_init",
                intent_id,
                "failed",
                error_code="not_a_git_repo",
                summary="Current directory is not a git repository.",
            )

        # Check for uncommitted changes
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
        dirty_files = status.stdout.strip()

        # Suggest a workspace_id if none provided
        if not workspace_id:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(cwd),
            ).stdout.strip()
            workspace_id = f"workspace-{branch or 'main'}"

        # Check if worktree already exists
        werk_root = cwd / ".rig" / "relay" / "worktrees"
        existing = werk_root / workspace_id

        lines = [f"Repo root: {cwd}"]
        if dirty_files:
            dirty_count = len(dirty_files.split("\n"))
            lines.append(
                f"Dirty files: {dirty_count} (commit or stash before creating worktrees)"
            )
        else:
            lines.append("Working tree: clean")
        lines.append(f"Suggested workspace ID: {workspace_id}")
        if existing.exists():
            lines.append(f"Warning: worktree '{workspace_id}' already exists.")
        else:
            lines.append(f"Worktree '{workspace_id}' does not exist — ready to create.")
        lines.append(f"Next: /worktree create {workspace_id}")

        return _build_result(
            "workspace_init",
            intent_id,
            "completed",
            result_kind="summary",
            summary="\n".join(lines),
        )
    except Exception as e:
        return _build_result(
            "workspace_init",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Workspace init failed: {e}",
        )


def _execute_council_consult(intent_id: str, params: dict) -> dict[str, Any]:
    """Execute a Council consultation across specified providers."""
    question = str(params.get("question", ""))
    providers = list(params.get("providers", ["claude", "chatgpt"]))

    if not question:
        return _build_result(
            "council_consult",
            intent_id,
            "failed",
            error_code="missing_parameter",
            summary="Parameter 'question' is required",
        )

    try:
        from rig_relay.coordination.council import Council

        council = Council(provider_bridge=None)
        request = council.create_request(
            mission_id="desktop-session",
            packet_sha256="placeholder",
            question=question,
            providers=providers,
        )

        return _build_result(
            "council_consult",
            intent_id,
            "completed",
            summary=f"Council request created: {request.request_id} for {len(providers)} providers",
            request_id=request.request_id,
            providers=providers,
        )
    except Exception as e:
        return _build_result(
            "council_consult",
            intent_id,
            "failed",
            summary=f"Council consultation failed: {e}",
        )


def _execute_fleet_orchestrate(intent_id: str) -> dict[str, Any]:
    """Run one fleet orchestrator cycle."""
    try:
        from rig_relay.coordination.fleet_coordinator import FleetCoordinator
        from rig_relay.runtime.tool_invocation_execution import (
            RuntimeToolExecutionRunner,
        )

        coord_root = DEFAULT_BUILD_ROOT / "coordination"

        executor = RuntimeToolExecutionRunner()
        coordinator = FleetCoordinator(coord_root, executor)
        result = asyncio.run(coordinator.run_once())

        snap = coordinator.snapshot()
        status_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(snap["status_counts"].items())
        )

        lines = [
            f"Decision: {result.decision}",
            f"Queue item: {result.queue_item_id or 'none'}",
            f"Queue status: {snap['total_count']} items ({status_str})",
        ]
        if result.error_kind:
            lines.append(f"Error: {result.error_kind}")
        if result.reason:
            lines.append(f"Reason: {result.reason}")
        if result.tool_name:
            lines.append(f"Tool: {result.tool_name}")

        return _build_result(
            "fleet_orchestrate",
            intent_id,
            "completed",
            result_kind="summary",
            summary="\n".join(lines),
        )
    except Exception as e:
        return _build_result(
            "fleet_orchestrate",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Fleet orchestration failed: {e}",
        )


def _execute_site_editor_save(intent_id: str, params: dict) -> dict[str, Any]:
    """Execute site editor save: validate, write, re-render. Gated by RIG_RELAY_ALLOW_SITE_EDITS=1."""
    import json as json_mod
    import os
    import subprocess
    import tempfile

    page_data = params.get("page_data", {})
    artifact_rel = params.get("artifact_path", "docs/json/site_home.v1.json")
    schema_rel = params.get(
        "schema_path", "docs/schemas/rig.documentation.home.v1.schema.json"
    )
    artifact_path = REPO_ROOT / artifact_rel
    schema_path = REPO_ROOT / schema_rel

    # Safety gate
    if os.environ.get("RIG_RELAY_ALLOW_SITE_EDITS", "0") != "1":
        return _build_result(
            intent_name="site_editor_save",
            intent_id=intent_id,
            status="refused",
            error_code="authorization_required",
            summary="Site editing is disabled. Set RIG_RELAY_ALLOW_SITE_EDITS=1 to enable.",
        )

    # Validate against schema
    if schema_path.exists():
        try:
            schema = json_mod.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=page_data, schema=schema)
        except jsonschema.ValidationError as e:
            return _build_result(
                intent_name="site_editor_save",
                intent_id=intent_id,
                status="failed",
                error_code="schema_validation_failed",
                summary=f"Page data failed schema validation: {e.message}",
            )

    # Atomic write via temp file + rename
    try:
        fd, tmp_path_str = tempfile.mkstemp(suffix=".json", dir=artifact_path.parent)
        tmp_path = Path(tmp_path_str)
        existing = (
            json_mod.loads(artifact_path.read_text(encoding="utf-8"))
            if artifact_path.exists()
            else {}
        )
        for k in ("schema_version", "document_id", "provenance"):
            if k in existing and k not in page_data:
                page_data[k] = existing[k]
        tmp_path.write_text(
            json_mod.dumps(page_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp_path.rename(artifact_path)
    except Exception as e:
        return _build_result(
            intent_name="site_editor_save",
            intent_id=intent_id,
            status="failed",
            error_code="atomic_write_failed",
            summary=f"Failed to write page data: {e}",
        )

    # Trigger render with minimal safe environment
    safe_env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    try:
        result = subprocess.run(
            ["uv", "run", "python", "scripts/render_static_docs.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            env=safe_env,
        )
        render_ok = result.returncode == 0
        stdout_tail = result.stdout[-500:] if result.stdout else ""
        stderr_tail = result.stderr[-200:] if result.stderr else ""
    except Exception as e:
        return _build_result(
            intent_name="site_editor_save",
            intent_id=intent_id,
            status="completed",
            summary=f"Saved but render failed: {e}",
            render_succeeded=False,
        )

    return _build_result(
        intent_name="site_editor_save",
        intent_id=intent_id,
        status="completed" if render_ok else "completed_with_errors",
        summary=f"Saved {len(page_data)} fields. Render {'succeeded' if render_ok else 'completed with errors'}.",
        render_succeeded=render_ok,
        render_stdout=stdout_tail,
        render_stderr=stderr_tail,
    )


def _execute_run_storage_audit(intent_id: str) -> dict[str, Any]:
    try:
        from scripts.rig_relay_storage_audit import audit_storage

        result = audit_storage(root=DEFAULT_BUILD_ROOT)
        budget_status = result.get("budget", {}).get("status", "unknown")
        total_mb = result.get("total_size_mb", 0)
        stale = result.get("stale_lease_count", 0)
        rollup = len(result.get("rollup_candidates", []))
        prune = result.get("prune_candidates_count", 0)
        recommendations = result.get("recommendations", [])

        return _build_result(
            "run_storage_audit",
            intent_id,
            "completed",
            result_kind="storage_audit",
            summary=(
                f"Storage audit: {total_mb:.1f} MB, budget={budget_status}, "
                f"stale_leases={stale}, rollup_candidates={rollup}, "
                f"prune_candidates={prune}, {len(recommendations)} recommendations."
            ),
            warnings=recommendations,
        )
    except Exception as e:
        return _build_result(
            "run_storage_audit",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Storage audit failed: {e}",
        )

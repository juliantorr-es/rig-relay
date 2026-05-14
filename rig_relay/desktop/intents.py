"""Rig Relay Desktop Intent API — Relay-native intent module.

Governed, schema-validated intent execution for the desktop WebSocket/pywebview
shell. This is the first Intent API slice: all intents are read-only or dry-run.
Protected mutation intents are explicitly refused with error codes and
authorization_required=True for future receipt-gated execution.

Allowed first-slice intents:
    refresh_projection, get_chat_state, generate_refinement_report,
    create_refinement_packets, run_storage_audit,
    create_chatgpt_dev_bundle_dry_run, create_telemetry_bundle_dry_run,
    validate_telemetry_bundle, run_queue_plan_dry_run, run_spawn_plan_dry_run,
    run_validation_suite

Provider intents (safe/control-plane — no protected action authority):
    provider_status, provider_onboarding_save_key,
    provider_onboarding_remove_key, provider_health_check

Phase 1 protected intents (receipt-gated, Phase 1):
    checkpoint.commit, lease_cleanup.archive

Refused intents (still receipt-gated, not yet enabled):
    bash, shell, write_file, search_replace,
    remote_upload.confirm, lease_cleanup.remove,
    spawn.execute, fleet.execute, delegate.execute
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
import json
from pathlib import Path
from typing import Any
import uuid

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_REPORTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "reports"
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"

REQUEST_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_request.v1.schema.json"
RESULT_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.desktop_intent_result.v1.schema.json"


# ── Intent Registry ────────────────────────────────────────────────────

ALLOWED_INTENTS: dict[str, dict[str, Any]] = {
    "refresh_projection": {
        "description": "Rebuild the content-light projection from available artifacts.",
        "affects_projection": True,
        "parameters": {},
    },
    "get_chat_state": {
        "description": "Return current chat session state.",
        "affects_projection": False,
        "parameters": {},
    },
    "generate_refinement_report": {
        "description": "Generate built-in tool refinement report from derived datasets.",
        "affects_projection": True,
        "parameters": {},
    },
    "create_refinement_packets": {
        "description": "Create refinement mission packets from the backlog.",
        "affects_projection": False,
        "parameters": {
            "limit": {"type": "integer", "default": 5},
            "priority": {"type": "string", "default": ""},
        },
    },
    "run_storage_audit": {
        "description": "Run storage audit and return budget status.",
        "affects_projection": False,
        "parameters": {},
    },
    "create_chatgpt_dev_bundle_dry_run": {
        "description": "Dry-run ChatGPT dev bundle creation (no zip written).",
        "affects_projection": False,
        "parameters": {"profile": {"type": "string", "default": "lite"}},
    },
    "create_telemetry_bundle_dry_run": {
        "description": "Dry-run telemetry bundle creation (no zip written).",
        "affects_projection": False,
        "parameters": {},
    },
    "validate_telemetry_bundle": {
        "description": "Validate a telemetry bundle for content-light compliance.",
        "affects_projection": False,
        "parameters": {},
    },
    "run_queue_plan_dry_run": {
        "description": "Dry-run queue planner (no state mutation).",
        "affects_projection": False,
        "parameters": {},
    },
    "run_spawn_plan_dry_run": {
        "description": "Dry-run spawn session planner (no subprocess spawning).",
        "affects_projection": False,
        "parameters": {},
    },
    "run_validation_suite": {
        "description": "Run the validation suite: ruff check, format check, pyright, schema validation, storage audit, desktop cockpit dry run.",
        "affects_projection": False,
        "parameters": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "default": [
                    "ruff_check",
                    "ruff_format_check",
                    "pyright",
                    "schema_validation",
                    "storage_audit",
                    "desktop_cockpit_dry_run",
                ],
                "description": "Steps to run. Default is a safe, mutation-free suite.",
            },
            "paths": {"type": "array", "items": {"type": "string"}, "default": []},
        },
    },
    "mint_authorization_receipt_dev": {
        "description": "Mint a local/dev authorization receipt for a Phase 1 protected intent.",
        "affects_projection": False,
        "parameters": {
            "action": {
                "type": "string",
                "enum": ["checkpoint.commit", "lease_cleanup.archive"],
            },
            "ttl_seconds": {"type": "integer", "default": 300},
            "reason": {"type": "string", "default": ""},
        },
    },
    "mint_authorization_receipt_local": {
        "description": "Mint a local system auth authorization receipt for a Phase 1 protected intent.",
        "affects_projection": False,
        "parameters": {
            "action": {
                "type": "string",
                "enum": ["checkpoint.commit", "lease_cleanup.archive"],
            },
            "ttl_seconds": {"type": "integer", "default": 300},
            "reason": {"type": "string", "default": ""},
        },
    },
    "inspect_authorization_receipt": {
        "description": "Inspect a local authorization receipt without exposing raw body in audit.",
        "affects_projection": False,
        "parameters": {"authorization_receipt": {"type": "object", "default": {}}},
    },
    # ── Identity Intents ──
    "identity_status": {
        "description": "Return identity provider statuses. Content-light — no raw tokens or secrets.",
        "affects_projection": False,
        "parameters": {},
    },
    "sign_in_github_start": {
        "description": "Start GitHub OAuth sign-in flow. Returns auth_url, loopback_port, state_hash. Does not exchange code unless credentials are configured.",
        "affects_projection": False,
        "parameters": {},
    },
    "sign_in_google_start": {
        "description": "Start Google OAuth sign-in flow. Returns auth_url, loopback_port, state_hash. Does not exchange code unless credentials are configured.",
        "affects_projection": False,
        "parameters": {},
    },
    "sign_out_provider": {
        "description": "Sign out of an identity provider. Removes local provider metadata/token if present.",
        "affects_projection": False,
        "parameters": {
            "provider": {
                "type": "string",
                "enum": ["github", "google"],
                "description": "Provider to sign out of.",
            }
        },
    },
    # ── Telemetry Consent Intents ──
    "telemetry_consent_status": {
        "description": "Return current telemetry consent status. Content-light — no raw tokens, email, prompts, code, or output.",
        "affects_projection": False,
        "parameters": {},
    },
    "telemetry_consent_grant": {
        "description": "Grant telemetry consent for specified scopes. Records consent locally. Does not upload automatically.",
        "affects_projection": False,
        "parameters": {
            "scopes": {
                "type": "array",
                "items": {"type": "string"},
                "default": [
                    "usage_metrics",
                    "content_light_bundles",
                    "crash_reports",
                    "coordination_metrics",
                    "tool_refinement_metrics",
                ],
                "description": "Scopes to grant consent for.",
            },
            "subject_hash": {"type": "string", "default": ""},
            "provider": {"type": "string", "default": "local"},
        },
    },
    "telemetry_consent_revoke": {
        "description": "Revoke telemetry consent. Sets status to revoked. Does not delete history.",
        "affects_projection": False,
        "parameters": {},
    },
    # ── Provider Onboarding Intents ──
    "provider_status": {
        "description": "Return content-light provider summaries for all registered providers.",
        "affects_projection": False,
        "parameters": {},
    },
    "provider_onboarding_save_key": {
        "description": "Save a provider API key locally. Returns fingerprint only — never raw key.",
        "affects_projection": False,
        "parameters": {
            "provider": {
                "type": "string",
                "enum": ["openai", "anthropic", "google", "openrouter", "deepseek"],
            },
            "api_key": {"type": "string", "description": "The API key to store."},
        },
    },
    "provider_onboarding_remove_key": {
        "description": "Remove a locally stored provider API key.",
        "affects_projection": False,
        "parameters": {
            "provider": {
                "type": "string",
                "enum": ["openai", "anthropic", "google", "openrouter", "deepseek"],
            }
        },
    },
    "provider_health_check": {
        "description": "Check provider health. network_allowed=False by default — no network calls in safe mode.",
        "affects_projection": False,
        "parameters": {
            "provider": {
                "type": "string",
                "default": "",
                "description": "Optional provider name. If empty, checks all.",
            },
            "network_allowed": {"type": "boolean", "default": False},
        },
    },
}

# Phase 1 protected intents — receipt-gated execution enabled
PHASE_1_ENABLED: dict[str, str] = {
    "checkpoint.commit": "checkpoint.commit",
    "lease_cleanup.archive": "lease_cleanup.archive",
}

# Protected intents — always refused (even with valid receipt in Phase 1)
PROTECTED_INTENTS: dict[str, str] = {
    "bash": "protected_intent_not_enabled",
    "shell": "protected_intent_not_enabled",
    "write_file": "protected_intent_not_enabled",
    "search_replace": "protected_intent_not_enabled",
    "remote_upload.confirm": "protected_intent_not_enabled",
    "lease_cleanup.remove": "protected_intent_not_enabled",
    "spawn.execute": "protected_intent_not_enabled",
    "fleet.execute": "protected_intent_not_enabled",
    "delegate.execute": "protected_intent_not_enabled",
}

# ── Schema Loading ─────────────────────────────────────────────────────


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Validation ──────────────────────────────────────────────────────────


def validate_intent_request(raw: dict[str, Any]) -> list[str]:
    """Validate intent request against the request schema.
    Returns a list of validation error messages (empty if valid).
    """
    schema = _load_schema(REQUEST_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(raw)]


def _validate_result(result: dict[str, Any]) -> list[str]:
    schema = _load_schema(RESULT_SCHEMA_PATH)
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(result)]


# ── Intent Execution ────────────────────────────────────────────────────


def _build_result(
    intent_name: str,
    intent_id: str,
    status: str,
    *,
    dry_run: bool = True,
    summary: str = "",
    result_kind: str = "summary",
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "rig.relay.desktop_intent_result.v1",
        "intent_id": intent_id,
        "created_at": datetime.now(UTC).isoformat(),
        "intent_name": intent_name,
        "status": status,
        "dry_run": dry_run,
        "result_kind": result_kind,
        "summary": summary,
        "output_refs": extra.get("output_refs", []),
        "projection_refresh_recommended": extra.get(
            "projection_refresh_recommended", False
        ),
        "authorization_required": extra.get("authorization_required", False),
        "warnings": extra.get("warnings", []),
    }
    error_code = extra.get("error_code")
    if error_code:
        result["error_code"] = error_code
    authorization_receipt = extra.get("authorization_receipt")
    if authorization_receipt:
        result["authorization_receipt"] = authorization_receipt
    inspection = extra.get("inspection")
    if inspection:
        result["inspection"] = inspection
    extra_fields = extra.get("extra_fields")
    if extra_fields:
        result["extra_fields"] = extra_fields
    return result


def execute_desktop_intent(
    request: dict[str, Any],
    chat_state_provider: Any | None = None,
    progress_emitter: Any | None = None,
) -> dict[str, Any]:
    """Execute a desktop intent request and return a content-light result.

    Args:
        request: The validated intent request dict.
        chat_state_provider: Optional callable returning dict of chat state.
        progress_emitter: Optional callable accepting a dict to broadcast
            progress events over WebSocket. Content-light only.

    Returns:
        Intent result dict (schema-validated, content-light).
    """
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

    # Check Phase 1 protected intents (receipt-gated)
    if intent_name in PHASE_1_ENABLED:
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
        )
        status = result.get("status", "failed")
        if status == "refused":
            _emit_progress(
                EVENT_OPERATION_REFUSED,
                phase="phase_1_protected",
                status="refused",
                message=result.get(
                    "summary", f"Protected intent '{intent_name}' refused"
                ),
            )
        elif status == "completed":
            _emit_progress(
                EVENT_OPERATION_COMPLETED,
                phase="phase_1_protected",
                status="completed",
                message=result.get(
                    "summary", f"Protected intent '{intent_name}' completed"
                ),
                result_kind=result.get("result_kind", ""),
                projection_refresh_recommended=result.get(
                    "projection_refresh_recommended", False
                ),
                warnings=result.get("warnings", []),
            )
        else:
            _emit_progress(
                EVENT_OPERATION_FAILED,
                phase="phase_1_protected",
                status="failed",
                message=result.get(
                    "summary", f"Protected intent '{intent_name}' failed"
                ),
                warnings=result.get("warnings", []),
            )
        emit_result(result)
        return result

    # Check remaining protected intents (always refused)
    if intent_name in PROTECTED_INTENTS:
        result = _build_result(
            intent_name,
            intent_id,
            "refused",
            authorization_required=True,
            error_code=PROTECTED_INTENTS[intent_name],
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

    # Check allowed intents
    if intent_name not in ALLOWED_INTENTS:
        result = _build_result(
            intent_name,
            intent_id,
            "refused",
            error_code="unsupported_intent",
            summary=f"Unknown intent '{intent_name}'. Allowed: {', '.join(sorted(ALLOWED_INTENTS))}",
        )
        _emit_progress(
            EVENT_OPERATION_REFUSED,
            phase="intent_check",
            status="refused",
            message=f"Unknown intent '{intent_name}'",
        )
        emit_result(result)
        return result

    # Execute allowed intent
    _emit_progress(
        EVENT_OPERATION_STARTED,
        phase=intent_name,
        status="running",
        message=f"Starting intent '{intent_name}'",
        result_kind=ALLOWED_INTENTS[intent_name].get("description", "").split(".")[0],
    )

    result = _execute_allowed_intent(
        intent_name, intent_id, request.get("parameters", {}), chat_state_provider
    )

    result_status = result.get("status", "failed")
    result_event_type = (
        EVENT_OPERATION_COMPLETED
        if result_status == "completed"
        else EVENT_OPERATION_FAILED
    )
    _emit_progress(
        result_event_type,
        phase=intent_name,
        status=result_status,
        message=result.get("summary", f"Intent '{intent_name}': {result_status}"),
        result_kind=result.get("result_kind", ""),
        projection_refresh_recommended=result.get(
            "projection_refresh_recommended", False
        ),
        warnings=result.get("warnings", []),
    )

    emit_result(result)
    return result


# ── Phase 1 Protected Intent Gate ─────────────────────────────────────


def validate_protected_intent_authorization(
    intent_name: str, receipt: dict[str, Any] | None
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate authorization receipt for a Phase 1 protected intent.

    Args:
        intent_name: Name of the intent.
        receipt: Authorization receipt dict, or None.

    Returns:
        Tuple of (valid: bool, reason: str, receipt_metadata: dict | None).
        receipt_metadata contains content-light fields for audit.
    """
    if receipt is None:
        return False, "Authorization receipt required", None

    from rig_relay.governance.auth_receipts import validate_receipt

    valid, reason = validate_receipt(receipt, intent_name)
    if not valid:
        return False, reason, None

    receipt_meta = {
        "authorization_receipt_sha256": receipt.get("receipt_sha256", ""),
        "authorization_action": receipt.get("action", ""),
        "authorization_status": "valid",
        "expires_at": receipt.get("expires_at", ""),
        "method": receipt.get("method", ""),
    }
    return True, "", receipt_meta


def _handle_phase_1_protected_intent(
    intent_name: str,
    intent_id: str,
    params: dict[str, Any],
    receipt: dict[str, Any] | None,
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


# ── Intent Handlers ─────────────────────────────────────────────────────


def _execute_refresh_projection(intent_id: str) -> dict[str, Any]:
    try:
        from rig_relay.desktop.projection import build_projection

        projection = build_projection(build_root=DEFAULT_BUILD_ROOT)
        available = sum(1 for v in projection.get("source_status", {}).values() if v)
        total = len(projection.get("source_status", {}))
        return _build_result(
            "refresh_projection",
            intent_id,
            "completed",
            result_kind="projection",
            summary=f"Projection rebuilt: {available}/{total} sources available.",
            projection_refresh_recommended=False,
        )
    except Exception as e:
        return _build_result(
            "refresh_projection",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Projection refresh failed: {e}",
        )


def _execute_allowed_intent(
    intent_name: str,
    intent_id: str,
    params: dict[str, Any],
    chat_state_provider: Any | None,
) -> dict[str, Any]:
    handlers = {
        "refresh_projection": lambda: _execute_refresh_projection(intent_id),
        "get_chat_state": lambda: _execute_get_chat_state(
            intent_id, chat_state_provider
        ),
        "generate_refinement_report": lambda: _execute_generate_refinement_report(
            intent_id
        ),
        "create_refinement_packets": lambda: _execute_create_refinement_packets(
            intent_id, params
        ),
        "run_storage_audit": lambda: _execute_run_storage_audit(intent_id),
        "create_chatgpt_dev_bundle_dry_run": lambda: (
            _execute_create_chatgpt_dev_bundle_dry_run(intent_id, params)
        ),
        "create_telemetry_bundle_dry_run": lambda: (
            _execute_create_telemetry_bundle_dry_run(intent_id)
        ),
        "validate_telemetry_bundle": lambda: _execute_validate_telemetry_bundle(
            intent_id
        ),
        "run_queue_plan_dry_run": lambda: _execute_run_queue_plan_dry_run(intent_id),
        "run_spawn_plan_dry_run": lambda: _execute_run_spawn_plan_dry_run(intent_id),
        "run_validation_suite": lambda: _execute_run_validation_suite(
            intent_id, params
        ),
        "mint_authorization_receipt_dev": lambda: (
            _execute_mint_authorization_receipt_dev(intent_id, params)
        ),
        "mint_authorization_receipt_local": lambda: (
            _execute_mint_authorization_receipt_local(intent_id, params)
        ),
        "inspect_authorization_receipt": lambda: _execute_inspect_authorization_receipt(
            intent_id, params
        ),
        # ── Identity Handlers ──
        "identity_status": lambda: _execute_identity_status(intent_id),
        "sign_in_github_start": lambda: _execute_sign_in_start(
            intent_id, "github", params
        ),
        "sign_in_google_start": lambda: _execute_sign_in_start(
            intent_id, "google", params
        ),
        "sign_out_provider": lambda: _execute_sign_out_provider(intent_id, params),
        # ── Telemetry Consent Handlers ──
        "telemetry_consent_status": lambda: _execute_telemetry_consent_status(
            intent_id, params
        ),
        "telemetry_consent_grant": lambda: _execute_telemetry_consent_grant(
            intent_id, params
        ),
        "telemetry_consent_revoke": lambda: _execute_telemetry_consent_revoke(
            intent_id, params
        ),
        # ── Provider Onboarding Handlers ──
        "provider_status": lambda: _execute_provider_status(intent_id),
        "provider_onboarding_save_key": lambda: _execute_provider_onboarding_save_key(
            intent_id, params
        ),
        "provider_onboarding_remove_key": lambda: (
            _execute_provider_onboarding_remove_key(intent_id, params)
        ),
        "provider_health_check": lambda: _execute_provider_health_check(
            intent_id, params
        ),
    }
    handler = handlers.get(intent_name)
    if handler is None:
        return _build_result(
            intent_name, intent_id, "refused", error_code="unsupported_intent"
        )
    return handler()


def _execute_get_chat_state(
    intent_id: str, chat_state_provider: Any | None
) -> dict[str, Any]:
    if chat_state_provider is not None:
        try:
            state = chat_state_provider()
            msg_count = len(state.get("messages", []))
            return _build_result(
                "get_chat_state",
                intent_id,
                "completed",
                result_kind="chat_state",
                summary=f"Chat state: {msg_count} messages.",
            )
        except Exception as e:
            return _build_result(
                "get_chat_state",
                intent_id,
                "failed",
                error_code="execution_error",
                summary=f"Chat state read failed: {e}",
            )
    return _build_result(
        "get_chat_state",
        intent_id,
        "completed",
        summary="No chat state provider available.",
    )


def _execute_generate_refinement_report(intent_id: str) -> dict[str, Any]:
    try:
        from scripts.rig_relay_builtin_tool_refinement import run as run_refinement

        derived_dir = DEFAULT_DERIVED_DIR
        reports_dir = DEFAULT_REPORTS_DIR
        output = reports_dir / "built-in-tool-refinement.md"
        jsonl_output = DEFAULT_DERIVED_DIR / "builtin_tool_refinement_backlog.jsonl"

        reports_dir.mkdir(parents=True, exist_ok=True)
        run_refinement(derived_dir, reports_dir, output, jsonl_output, strict=False)

        warnings: list[str] = []
        if not output.is_file():
            return _build_result(
                "generate_refinement_report",
                intent_id,
                "failed",
                error_code="output_not_created",
                summary="Refinement report was not generated.",
            )

        # Count items
        item_count = 0
        if jsonl_output.is_file():
            with jsonl_output.open() as f:
                item_count = sum(1 for _ in f)

        return _build_result(
            "generate_refinement_report",
            intent_id,
            "completed",
            result_kind="report",
            summary=f"Refinement report generated: {item_count} backlog items.",
            output_refs=[
                str(output.relative_to(REPO_ROOT)),
                str(jsonl_output.relative_to(REPO_ROOT)),
            ]
            if output.is_relative_to(REPO_ROOT)
            else [],
            projection_refresh_recommended=True,
            warnings=warnings,
        )
    except Exception as e:
        return _build_result(
            "generate_refinement_report",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Refinement report generation failed: {e}",
        )


def _execute_create_refinement_packets(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from scripts.rig_relay_create_builtin_refinement_packets import generate_packets

        backlog = DEFAULT_DERIVED_DIR / "builtin_tool_refinement_backlog.jsonl"
        report = DEFAULT_REPORTS_DIR / "built-in-tool-refinement.md"
        output_dir = DEFAULT_BUILD_ROOT / "refinement-packets"
        limit = int(params.get("limit", 5))
        priority_raw = str(params.get("priority", ""))
        priority_filter = {
            p.strip() for p in priority_raw.split(",") if p.strip()
        } or None

        if not backlog.is_file():
            return _build_result(
                "create_refinement_packets",
                intent_id,
                "failed",
                error_code="missing_input",
                summary="No refinement backlog found. Run generate_refinement_report first.",
            )

        packet_paths, packet_warnings = generate_packets(
            backlog=backlog,
            report=report,
            output_dir=output_dir,
            limit=limit,
            priority_filter=priority_filter,
            dry_run=True,
        )

        return _build_result(
            "create_refinement_packets",
            intent_id,
            "completed",
            result_kind="packets",
            summary=f"Refinement packets: {len(packet_paths)} packets (dry-run).",
            output_refs=[
                str(p.relative_to(REPO_ROOT))
                for p in packet_paths
                if p.is_relative_to(REPO_ROOT)
            ],
            warnings=packet_warnings,
        )
    except Exception as e:
        return _build_result(
            "create_refinement_packets",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Refinement packet creation failed: {e}",
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


def _execute_create_chatgpt_dev_bundle_dry_run(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from pathlib import Path as _P
        import subprocess

        profile = str(params.get("profile", "lite"))
        script = (
            _P(__file__).resolve().parent.parent.parent
            / "scripts"
            / "rig_relay_create_chatgpt_dev_bundle.py"
        )
        result = subprocess.run(
            ["uv", "run", "python", str(script), "--profile", profile, "--dry-run"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        warnings: list[str] = []
        if result.returncode != 0:
            warnings.append(f"Script stderr: {result.stderr[:200]}")
        return _build_result(
            "create_chatgpt_dev_bundle_dry_run",
            intent_id,
            "completed",
            result_kind="bundle_dry_run",
            summary=f"Dev bundle dry-run completed (exit: {result.returncode}).",
            warnings=warnings,
        )
    except Exception as e:
        return _build_result(
            "create_chatgpt_dev_bundle_dry_run",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Dev bundle dry-run failed: {e}",
        )


def _execute_create_telemetry_bundle_dry_run(intent_id: str) -> dict[str, Any]:
    try:
        from pathlib import Path as _P
        import subprocess

        script = (
            _P(__file__).resolve().parent.parent.parent
            / "scripts"
            / "rig_relay_create_telemetry_bundle.py"
        )
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(script),
                "--participant-id",
                "intent_dry_run",
                "--share-level",
                "derived_only",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        warnings: list[str] = []
        if result.returncode != 0:
            warnings.append(f"Script stderr: {result.stderr[:200]}")
        return _build_result(
            "create_telemetry_bundle_dry_run",
            intent_id,
            "completed",
            result_kind="bundle_dry_run",
            summary=f"Telemetry bundle dry-run completed (exit: {result.returncode}).",
            warnings=warnings,
        )
    except Exception as e:
        return _build_result(
            "create_telemetry_bundle_dry_run",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Telemetry bundle dry-run failed: {e}",
        )


def _execute_validate_telemetry_bundle(intent_id: str) -> dict[str, Any]:
    try:
        from rig_relay.evidence.telemetry_bundle import validate_bundle

        bundle_dir = DEFAULT_BUILD_ROOT / "telemetry-bundles"
        if not bundle_dir.is_dir():
            return _build_result(
                "validate_telemetry_bundle",
                intent_id,
                "completed",
                summary="No telemetry bundles found to validate.",
            )

        warnings: list[str] = []
        found = 0
        for entry in sorted(bundle_dir.iterdir()):
            bundle_path = entry / "telemetry_bundle_manifest.json"
            if bundle_path.is_file():
                v_result = validate_bundle(bundle_path)
                found += 1
                if v_result[1]:
                    warnings.extend(v_result[1])

        return _build_result(
            "validate_telemetry_bundle",
            intent_id,
            "completed",
            result_kind="validation",
            summary=f"Validated {found} telemetry bundle manifest(s).",
            warnings=warnings,
        )
    except Exception as e:
        return _build_result(
            "validate_telemetry_bundle",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Telemetry bundle validation failed: {e}",
        )


def _execute_run_queue_plan_dry_run(intent_id: str) -> dict[str, Any]:
    try:
        from scripts.rig_relay_queue_plan import main as queue_main

        coord_root = DEFAULT_BUILD_ROOT / "coordination"
        queue_dir = DEFAULT_BUILD_ROOT / "queue"
        argv = [
            "--coordination-root",
            str(coord_root),
            "--max-items",
            "4",
            "--output",
            str(queue_dir / "ready_plan.json"),
        ]
        if coord_root.is_dir() and queue_dir.is_dir():
            rc = queue_main(argv)
            return _build_result(
                "run_queue_plan_dry_run",
                intent_id,
                "completed",
                summary=f"Queue plan dry-run completed (exit code: {rc}).",
            )
        return _build_result(
            "run_queue_plan_dry_run",
            intent_id,
            "completed",
            result_kind="plan_dry_run",
            summary="No coordination root or queue directory found. Nothing planned.",
        )
    except Exception as e:
        return _build_result(
            "run_queue_plan_dry_run",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Queue plan dry-run failed: {e}",
        )


def _execute_run_spawn_plan_dry_run(intent_id: str) -> dict[str, Any]:
    try:
        from scripts.rig_relay_spawn_session import main as spawn_main

        coord_root = DEFAULT_BUILD_ROOT / "coordination"
        argv = [
            "--mission-packet",
            "",
            "--dry-run",
            "--coordination-root",
            str(coord_root),
        ]
        if coord_root.is_dir():
            rc = spawn_main(argv)
            return _build_result(
                "run_spawn_plan_dry_run",
                intent_id,
                "completed",
                summary=f"Spawn plan dry-run completed (exit code: {rc}).",
            )
        return _build_result(
            "run_spawn_plan_dry_run",
            intent_id,
            "completed",
            result_kind="plan_dry_run",
            summary="No coordination root found. Nothing planned.",
        )
    except SystemExit:
        # spawn_main uses SystemExit; capture it cleanly
        return _build_result(
            "run_spawn_plan_dry_run",
            intent_id,
            "completed",
            summary="Spawn plan dry-run completed.",
        )
    except Exception as e:
        return _build_result(
            "run_spawn_plan_dry_run",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Spawn plan dry-run failed: {e}",
        )


def _execute_run_validation_suite(
    intent_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        steps = params.get(
            "steps",
            [
                "ruff_check",
                "ruff_format_check",
                "pyright",
                "schema_validation",
                "storage_audit",
                "desktop_cockpit_dry_run",
            ],
        )
        paths = params.get("paths", [])
        from rig_relay.core.tools.base import BaseToolState, InvokeContext
        from rig_relay.core.tools.builtins.validation_suite import (
            ValidationStepRequest,
            ValidationSuite,
            ValidationSuiteArgs,
            ValidationSuiteConfig,
            ValidationSuiteResult,
        )

        config = ValidationSuiteConfig(
            validation_root=DEFAULT_BUILD_ROOT / "validation"
        )
        tool = ValidationSuite(config_getter=lambda: config, state=BaseToolState())
        args = ValidationSuiteArgs(
            suite_name="desktop_validation_suite",
            steps=[
                ValidationStepRequest(kind=step, paths=paths or []) for step in steps
            ],
            default_paths=paths or [],
        )
        ctx = InvokeContext(
            tool_call_id=f"intent-{intent_id}",
            session_dir=DEFAULT_BUILD_ROOT / "sessions" / "desktop",
        )

        import asyncio

        async def _collect() -> ValidationSuiteResult:
            async for event in tool.run(args, ctx):
                if isinstance(event, ValidationSuiteResult):
                    return event
            raise RuntimeError("Validation suite returned no result")

        result = asyncio.run(_collect())

        step_summaries = "; ".join(f"{s.kind}:{s.status}" for s in result.steps)

        return _build_result(
            "run_validation_suite",
            intent_id,
            result.status,
            result_kind="validation_suite",
            summary=(
                f"Validation suite '{result.suite_name}': {result.status}. "
                f"{len(result.executed_steps)} executed, "
                f"{len(result.skipped_steps)} skipped. "
                f"Steps: [{step_summaries}]. "
                f"sha256: {result.validation_suite_sha256}"
            ),
            output_refs=result.artifact_refs,
            projection_refresh_recommended=True,
            warnings=result.warnings,
        )
    except Exception as e:
        return _build_result(
            "run_validation_suite",
            intent_id,
            "failed",
            error_code="execution_error",
            summary=f"Validation suite failed: {e}",
        )


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


# ── Phase 1 Protected Intent Handlers ──────────────────────────────


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


# ── Identity Intent Handlers ────────────────────────────────────────────


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

    Returns auth_url, loopback_port, state_hash. Does not exchange code
    unless credentials are configured. Returns pending result if not configured.
    """
    try:
        import hashlib
        import secrets

        from rig_relay.identity.oauth_loopback import (
            build_loopback_redirect_uri,
            find_free_loopback_port,
        )

        if provider_name == "github":
            from rig_relay.identity.github import GitHubIdentityProvider

            provider = GitHubIdentityProvider()
        elif provider_name == "google":
            from rig_relay.identity.google import GoogleIdentityProvider

            provider = GoogleIdentityProvider()
        else:
            return _build_result(
                f"sign_in_{provider_name}_start",
                intent_id,
                "failed",
                error_code="invalid_provider",
                summary=f"Unknown provider: {provider_name}",
            )

        port = find_free_loopback_port()
        redirect_uri = build_loopback_redirect_uri(port)
        state = secrets.token_hex(32)
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()

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
                    "loopback_port": port,
                    "state_hash": state_hash,
                    "provider": provider_name,
                    "status": "pending",
                    "configured": False,
                    "warning": f"{provider_name} credentials not configured",
                },
            )

        scopes = provider.default_scopes()
        auth_url = provider.build_auth_url(
            redirect_uri=redirect_uri, state=state, scopes=scopes
        )

        return _build_result(
            f"sign_in_{provider_name}_start",
            intent_id,
            "completed",
            result_kind="identity_status",
            summary=f"Sign in with {provider_name}: auth URL generated. "
            f"Scopes: {', '.join(scopes)}.",
            extra_fields={
                "auth_url": auth_url,
                "loopback_port": port,
                "redirect_uri": redirect_uri,
                "state_hash": state_hash,
                "provider": provider_name,
                "status": "pending",
                "configured": True,
                "scopes": scopes,
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


# ── Telemetry Consent Intent Handlers ────────────────────────────────


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


# ── Provider Onboarding Handlers ──────────────────────────────────────


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

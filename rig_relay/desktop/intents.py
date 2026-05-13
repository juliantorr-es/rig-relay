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

Phase 1 protected intents (receipt-gated, Phase 1):
    checkpoint.commit, lease_cleanup.archive

Refused intents (still receipt-gated, not yet enabled):
    bash, shell, write_file, search_replace,
    remote_upload.confirm, lease_cleanup.remove,
    spawn.execute, fleet.execute, delegate.execute
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    return result


def execute_desktop_intent(
    request: dict[str, Any], chat_state_provider: Any | None = None
) -> dict[str, Any]:
    """Execute a desktop intent request and return a content-light result.

    Args:
        request: The validated intent request dict.
        chat_state_provider: Optional callable returning dict of chat state.

    Returns:
        Intent result dict (schema-validated, content-light).
    """
    from rig_relay.desktop.intent_audit import emit_received, emit_result

    intent_name = str(request.get("intent_name", ""))
    intent_id = str(request.get("intent_id", f"intent_{uuid.uuid4().hex[:12]}"))

    # Emit received event
    emit_received(request)

    # Check Phase 1 protected intents (receipt-gated)
    if intent_name in PHASE_1_ENABLED:
        return _handle_phase_1_protected_intent(
            intent_name,
            intent_id,
            request.get("parameters", {}),
            request.get("authorization_receipt"),
        )

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
        emit_result(result)
        return result

    result = _execute_allowed_intent(
        intent_name, intent_id, request.get("parameters", {}), chat_state_provider
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
        from vibe.core.tools.base import BaseToolState, InvokeContext
        from vibe.core.tools.builtins.validation_suite import (
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

        from vibe.core.tools.base import BaseToolState, InvokeContext
        from vibe.core.tools.builtins.checkpoint import (
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

        from vibe.core.tools.builtins.checkpoint import CheckpointResult

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

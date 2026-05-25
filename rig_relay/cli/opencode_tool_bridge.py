"""OpenCode custom-tool transport bridge → Rig RuntimeToolExecutionRunner.

Stage A transport-only adapter. Reads a single JSON search_replace invocation
from stdin, delegates to the existing governed RuntimeToolExecutionRunner,
and emits a content-light JSON result to stdout.

This is explicitly temporary transport infrastructure. It is an OpenCode-specific
adapter that lives under `rig_relay/cli/` (not `rig_relay/runtime/`) because it
owns zero runtime authority. RuntimeToolExecutionRunner remains the single
authoritative governed execution spine.

Privacy boundary:
  Raw replacement content necessarily crosses this bridge as transient
  invocation input. The bridge must never persist, log, or emit raw content
  outside the governed Rig invocation path. Result output is content-light:
  receipt/envelope identifiers, status, and timing only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


def _build_search_replace_content(old_str: str, new_str: str) -> str:
    """Construct SEARCH/REPLACE block content for the SearchReplace tool."""
    return f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"


async def _invoke_tool(
    tool_name_str: str,
    args: dict[str, Any],
    *,
    session_id: str = "opencode-bridge",
    directory: str = "",
    worktree: str | None = None,
) -> dict[str, Any]:
    """Build intent, context, delegate to RuntimeToolExecutionRunner.

    Returns a content-light dict suitable for JSON serialization.
    """
    from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
    from rig_relay.runtime.tool_invocation_adapter import (
        RuntimeToolIntent,
        RuntimeToolName,
    )
    from rig_relay.runtime.tool_invocation_execution import RuntimeToolExecutionRunner

    repo_root = Path(directory) if directory else Path.cwd()
    worktree_path = Path(worktree) if worktree else None

    # Wrap the original tool name and args in runtime_exec payload format
    payload = {"tool_name": tool_name_str, **args}

    payload_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    intent_id = f"opencode-{tool_name_str}-{payload_digest[:16]}"

    intent = RuntimeToolIntent(
        intent_id=intent_id,
        tool_name=RuntimeToolName.RUNTIME_EXEC,
        payload=payload,
        allow_main_repo_mutation=worktree_path is None,
        agent_id="opencode-custom-tool",
    )

    task_id = f"bridge-{payload_digest[16:32]}"
    ctx = RuntimeContext(
        session_id=session_id,
        task_id=task_id,
        lane_id=None,
        workspace_id=None,
        worktree_path=str(worktree_path) if worktree_path else None,
        repo_root=str(repo_root),
        coordination_scope="opencode-bridge",
        coordination_enabled=False,
    )
    resolution = RuntimeContextResolution(status="resolved", context=ctx)

    from rig_relay.governance.dirty_guard import get_guard

    guard = get_guard()
    guard.capture(repo_root)
    if tool_name_str == "checkpoint":
        include_paths = args.get("include_paths", [])
        for p in include_paths:
            try:
                rel_p = Path(p).resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                rel_p = Path(p).as_posix()
            guard.dirty_snapshots.pop(rel_p, None)
            guard.touched_files.add(rel_p)

    runner = RuntimeToolExecutionRunner()
    result = await runner.execute_runtime_exec(intent, resolution)

    response: dict[str, Any] = {
        "schema_version": result.schema_version,
        "status": result.status.value,
        "intent_id": result.intent_id,
        "tool_name": result.tool_name,
        "receipt_sha256": result.receipt_sha256,
        "receipt_envelope_id": result.receipt_envelope_id,
        "audit_event_id": result.audit_event_id,
        "supervisor_result_envelope_id": result.supervisor_result_envelope_id,
        "supervisor_result_envelope_sha256": (result.supervisor_result_envelope_sha256),
        "changed_paths": result.changed_paths,
        "duration_ms": result.duration_ms,
        "error_kind": result.error_kind,
        "refusal_reason": result.refusal_reason,
        "warnings": result.warnings,
    }
    if result.git_summary is not None:
        response["git_summary"] = result.git_summary.model_dump(mode="json")

    return response


async def _invoke_search_replace(
    file_path: str,
    old_str: str,
    new_str: str,
    *,
    expected_before_sha256: str | None = None,
    session_id: str = "opencode-bridge",
    directory: str = "",
    worktree: str | None = None,
) -> dict[str, Any]:
    """Legacy entry point wrapper for backwards compatibility."""
    args: dict[str, Any] = {
        "file_path": file_path,
        "content": _build_search_replace_content(old_str, new_str),
    }
    if expected_before_sha256 is not None:
        args["expected_before_sha256"] = expected_before_sha256
    return await _invoke_tool(
        tool_name_str="search_replace",
        args=args,
        session_id=session_id,
        directory=directory,
        worktree=worktree,
    )


def main() -> None:
    """CLI entry point: read JSON from stdin, invoke, write JSON to stdout."""
    try:
        raw = sys.stdin.buffer.read()
        request = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        error_result = {
            "status": "failed",
            "error_kind": "bridge_parse_error",
            "refusal_reason": f"Failed to parse stdin JSON: {exc}",
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)

    tool_name_str = request.get("tool_name") or request.get("toolName")
    if tool_name_str:
        args = request.get("args") or {}
    else:
        # Legacy search_replace format
        file_path = request.get("filePath", "")
        old_str = request.get("oldStr", "")
        new_str = request.get("newStr", "")
        if not file_path:
            error_result = {
                "status": "failed",
                "error_kind": "invalid_payload",
                "refusal_reason": "Missing required field: filePath or tool_name",
            }
            sys.stdout.write(json.dumps(error_result) + "\n")
            sys.exit(1)
        if not old_str and not new_str:
            error_result = {
                "status": "failed",
                "error_kind": "invalid_payload",
                "refusal_reason": (
                    "At least one of oldStr or newStr must be non-empty"
                ),
            }
            sys.stdout.write(json.dumps(error_result) + "\n")
            sys.exit(1)
        tool_name_str = "search_replace"
        args = {
            "file_path": file_path,
            "content": _build_search_replace_content(old_str, new_str),
        }
        if "expectedBeforeSha256" in request:
            args["expected_before_sha256"] = request["expectedBeforeSha256"]

    try:
        result = asyncio.run(
            _invoke_tool(
                tool_name_str=tool_name_str,
                args=args,
                session_id=request.get("sessionId", "opencode-bridge"),
                directory=request.get("directory", ""),
                worktree=request.get("worktree"),
            )
        )
        sys.stdout.write(json.dumps(result) + "\n")
        if result.get("status") not in {"completed", "cached"}:
            sys.exit(1)
    except Exception as exc:
        error_result = {
            "status": "failed",
            "error_kind": "bridge_invocation_error",
            "refusal_reason": f"Bridge invocation failed: {exc}",
        }
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Private integration adapter for applying mutations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import uuid

from rig_relay.runtime.context import RuntimeContextResolution, RuntimeContext
from rig_relay.runtime.context_resolver import RuntimeContextResolver
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionResult,
    RuntimeToolExecutionStatus,
)

def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write(f"Failed to decode JSON from stdin: {e}\n")
        sys.exit(1)

    workspace_root = Path(input_data.get("workspace_root", Path.cwd())).resolve()
    args = input_data.get("args", {})
    ts_context = input_data.get("context", {})

    mutation_type = args.get("mutation_type")
    if not mutation_type:
        sys.stderr.write("Missing 'mutation_type' in args\n")
        sys.exit(1)

    # 1. Extract target path and arguments
    payload = {}
    target_path = ""
    
    if mutation_type == "write_file":
        target_path = args.get("path", "")
        payload = {
            "path": target_path,
            "content": args.get("content", ""),
            "overwrite": args.get("overwrite", False),
            "allow_overwrite_protected": args.get("allow_overwrite_protected", False),
            "expected_before_sha256": args.get("expected_before_sha256"),
        }
    elif mutation_type == "search_replace":
        target_path = args.get("file_path", "")
        payload = {
            "file_path": target_path,
            "content": args.get("content", ""),
            "expected_before_sha256": args.get("expected_before_sha256"),
            "expected_replacements": args.get("expected_replacements"),
            "allow_multiple": args.get("allow_multiple", False),
        }
    else:
        sys.stderr.write(f"Unsupported mutation_type: {mutation_type}\n")
        sys.exit(1)

    # 2. Normalize and check path safety/evidence folder block
    try:
        norm_path = Path(target_path).resolve().relative_to(workspace_root)
        rel_path_str = norm_path.as_posix()
    except ValueError:
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.BLOCKED,
            intent_id=str(uuid.uuid4()),
            tool_name=mutation_type,
            error_kind="unsafe_path",
            refusal_reason="Target path is outside workspace root"
        )
        print(result.model_dump_json())
        return

    # Block canonical evidence directories
    blocked_evidence_prefixes = (".rig/reports/", ".build/rig-relay/governance/", "docs/findings/")
    if any(rel_path_str.startswith(prefix) for prefix in blocked_evidence_prefixes):
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.BLOCKED,
            intent_id=str(uuid.uuid4()),
            tool_name=mutation_type,
            error_kind="evidence_protection",
            refusal_reason="Direct mutation of canonical evidence store is prohibited"
        )
        print(result.model_dump_json())
        return

    # 3. Resolve context
    session_id = ts_context.get("session_id")
    task_id = ts_context.get("task_id")
    lane_id = ts_context.get("lane_id")
    workspace_id = ts_context.get("workspace_id")

    resolver = RuntimeContextResolver(
        sessions_dir=workspace_root / ".rig" / "sessions",
        repo_root=workspace_root,
    )
    
    resolution = resolver.resolve_for_intent(
        intent_kind=mutation_type,
        session_id=session_id,
        task_id=task_id,
        lane_id=lane_id,
        workspace_id=workspace_id,
        paths=[target_path],
        require_worktree=True,
    )

    if resolution.status != "resolved":
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.BLOCKED,
            intent_id=str(uuid.uuid4()),
            tool_name=mutation_type,
            error_kind=resolution.error_kind or "context_unresolved",
            refusal_reason=resolution.refusal_reason or "Context resolution failed"
        )
        print(result.model_dump_json())
        return

    # 4. Build Intent and Run via governed execution runner
    tool_name = RuntimeToolName.WRITE_FILE if mutation_type == "write_file" else RuntimeToolName.SEARCH_REPLACE
    intent = RuntimeToolIntent(
        intent_id=str(uuid.uuid4()),
        tool_name=tool_name,
        payload=payload,
        requested_paths=[target_path],
    )

    runner = RuntimeToolExecutionRunner()
    import asyncio
    
    async def run_exec():
        if mutation_type == "write_file":
            return await runner.execute_write_file(intent, resolution)
        else:
            return await runner.execute_search_replace(intent, resolution)

    try:
        res_result = asyncio.run(run_exec())
        print(res_result.model_dump_json())
    except Exception as e:
        sys.stderr.write(f"Execution failed: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()

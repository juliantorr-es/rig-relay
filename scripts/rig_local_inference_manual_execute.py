"""Manual local inference execution CLI.

Evaluates and optionally executes a manual local inference request.
Never auto-starts servers, downloads models, or persists raw prompts/completions.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
import sys

from rig_relay.providers.local_inference.airlock import (
    LocalInferenceAirlock,
    get_airlock,
)
from rig_relay.providers.local_inference.execution_gate import (
    build_approval,
    build_executed_receipt,
    evaluate_execution_gate,
)
from rig_relay.providers.local_inference.models import (
    ExecutionStatusKind,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    RequestClass,
)
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual local inference execution.")
    parser.add_argument("--config-root", type=Path, default=None)
    parser.add_argument(
        "--prompt-file", type=Path, default=None, help="Read prompt text from file"
    )
    parser.add_argument("--prompt", type=str, default=None, help="Prompt text")
    parser.add_argument("--task-profile", type=str, default="chat_light")
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--execute", action="store_true", help="Execute request")
    parser.add_argument("--print-output", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".build/rig-relay/derived")
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return args.prompt_file.read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    return "Hello, this is a manual test prompt."


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    prompt_text = _read_prompt(args)
    prompt_bytes = prompt_text.encode("utf-8")
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()
    prompt_line_count = prompt_text.count("\n") + 1

    airlock = (
        get_airlock()
        if args.config_root is None
        else LocalInferenceAirlock(args.config_root)
    )
    configured = airlock.is_configured
    config = airlock.get_config() if configured else None
    endpoint_hash = config.endpoint_sha256 if config else ""

    if not configured:
        receipt = ManualExecutionResponseReceipt(
            execution_id=f"exec_cli_{secrets.token_hex(4)}",
            request_id="",
            generated_at=datetime.now(UTC).isoformat(),
            status=ExecutionStatusKind.BLOCKED,
            blocked_reasons=["endpoint_not_configured"],
        )
        _write_output(receipt, args)
        return 0

    request = ManualExecutionRequest(
        request_id=f"req_{secrets.token_hex(8)}",
        task_profile=args.task_profile,
        request_class=RequestClass.CHAT,
        endpoint_hash=endpoint_hash,
        prompt_sha256=prompt_sha,
        prompt_byte_count=len(prompt_bytes),
        prompt_line_count=prompt_line_count,
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        created_at=datetime.now(UTC).isoformat(),
    )

    selection = evaluate_selection_policy(
        endpoint_configured=True, endpoint_sha256=endpoint_hash
    )

    approval = None
    if args.execute:
        approval = build_approval(
            scope_endpoint_hash=endpoint_hash,
            scope_task_profile=args.task_profile,
            scope_max_prompt_bytes=max(4096, len(prompt_bytes) + 1),
            scope_max_output_tokens=args.max_output_tokens,
            ttl_seconds=300,
        )
        request.approval_id = approval.approval_id

    gate_result = evaluate_execution_gate(
        endpoint_configured=True,
        endpoint_hash=endpoint_hash,
        selection_policy_result=selection,
        approval=approval,
        request=request,
    )

    if gate_result.status == ExecutionStatusKind.EXECUTED and args.execute:
        assert config is not None
        from rig_relay.providers.local_inference.execution_client import (
            execute_chat_completion,
        )

        result = asyncio.run(
            execute_chat_completion(
                endpoint_url=config.endpoint_url,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=args.max_output_tokens,
                temperature=args.temperature,
            )
        )
        gate_result = build_executed_receipt(
            request=request,
            status=(
                ExecutionStatusKind(result["status"])
                if result["status"]
                in {"executed", "failed", "timed_out", "malformed_response"}
                else ExecutionStatusKind.FAILED
            ),
            completion_sha256=result["completion_sha256"],
            completion_byte_count=result["completion_byte_count"],
            output_token_count=result["output_token_count"],
            input_token_count=result["input_token_count"],
            latency_ms=result["latency_ms"],
            error_class=result.get("error_class", ""),
            model_safe_id=result.get("model_safe_id", ""),
            selection_policy_status=selection.get("result_kind", ""),
        )
        gate_result.approval_id = request.approval_id
        if args.print_output and result.get("content"):
            print(f"COMPLETION: {result['content']}")

    _write_output(gate_result, args)
    return 0


def _write_output(
    receipt: ManualExecutionResponseReceipt, args: argparse.Namespace
) -> None:
    receipt_data = json.loads(receipt.model_dump_json())
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out = args.output_dir / "local_inference_manual_execution_receipt.v1.json"
        out.write_text(
            json.dumps(receipt_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        msg = f"Receipt written to {out}"
        if args.json:
            print(msg, file=sys.stderr)
        else:
            print(msg)

    if args.json:
        print(json.dumps(receipt_data, indent=2, sort_keys=True))
    else:
        print(f"Status: {receipt_data['status']}")
        if receipt_data.get("blocked_reasons"):
            for r in receipt_data["blocked_reasons"]:
                print(f"  Blocked: {r}")
        print(f"  Prompt SHA256: {receipt_data['prompt_sha256'][:16]}...")
        print(f"  Raw prompt persisted: {receipt_data['raw_prompt_persisted']}")
        print(f"  Raw completion persisted: {receipt_data['raw_completion_persisted']}")
        print(f"  Auto execution: {receipt_data['automatic_agent_execution']}")


if __name__ == "__main__":
    sys.exit(main())

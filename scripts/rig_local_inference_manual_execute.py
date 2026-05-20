"""Manual local inference execution CLI — hardened.

--execute alone is not sufficient. Execution requires --approval-file.
Fixture approval is a separate explicit action (--create-fixture-approval).
Selection evidence is required (--probe-receipt or explicit fixture).
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
    ApprovedByMode,
    ExecutionStatusKind,
    ManualExecutionApproval,
    ManualExecutionRequest,
    ManualExecutionResponseReceipt,
    RequestClass,
)
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manual local inference execution")
    p.add_argument("--config-root", type=Path, default=None)
    p.add_argument("--prompt-file", type=Path, default=None)
    p.add_argument("--prompt", type=str, default=None)
    p.add_argument("--task-profile", type=str, default="chat_light")
    p.add_argument("--max-output-tokens", type=int, default=512)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approval-file", type=Path, default=None)
    p.add_argument("--create-fixture-approval", action="store_true")
    p.add_argument("--fixture-approval-output", type=Path, default=None)
    p.add_argument("--probe-receipt", type=Path, default=None)
    p.add_argument("--selection-policy-receipt", type=Path, default=None)
    p.add_argument("--print-output", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(".build/rig-relay/derived"))
    p.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def _read_prompt(args: argparse.Namespace) -> str:
    return (
        args.prompt_file.read_text(encoding="utf-8")
        if args.prompt_file
        else args.prompt
        if args.prompt
        else "Hello, this is a manual test prompt."
    )


def _load_approval(path: Path) -> ManualExecutionApproval | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ManualExecutionApproval(**data)
    except Exception:
        return None


def _build_blocked_stdout(
    receipt: ManualExecutionResponseReceipt, args: argparse.Namespace
) -> int:
    receipt_data = json.loads(receipt.model_dump_json())
    _write(receipt_data, args)
    return 0


def _write(data: dict, args: argparse.Namespace) -> None:
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out = args.output_dir / "local_inference_manual_execution_receipt.v1.json"
        out.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        msg = f"Receipt written to {out}"
        print(msg, file=sys.stderr if args.json else sys.stdout)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"Status: {data['status']}")
        if data.get("blocked_reasons"):
            for r in data["blocked_reasons"]:
                print(f"  Blocked: {r}")
        print(f"  Raw prompt persisted: {data['raw_prompt_persisted']}")
        print(f"  Raw completion persisted: {data['raw_completion_persisted']}")
        print(f"  Auto execution: {data['automatic_agent_execution']}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    prompt_text = _read_prompt(args)
    prompt_bytes = prompt_text.encode("utf-8")
    prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()

    airlock = (
        get_airlock()
        if args.config_root is None
        else LocalInferenceAirlock(args.config_root)
    )
    configured = airlock.is_configured
    config = airlock.get_config() if configured else None
    endpoint_hash = config.endpoint_sha256 if config else ""

    if args.create_fixture_approval:
        approval = build_approval(
            approved_by=ApprovedByMode.FIXTURE,
            scope_endpoint_hash=endpoint_hash,
            scope_task_profile=args.task_profile,
            scope_max_prompt_bytes=max(4096, len(prompt_bytes) + 1),
            scope_max_output_tokens=args.max_output_tokens,
            ttl_seconds=300,
        )
        out_path = args.fixture_approval_output or Path(
            ".build/rig-relay/derived/local_inference_manual_execution_approval.v1.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(approval.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"Fixture approval written to {out_path}")
        if not args.execute:
            return 0

    if not configured:
        receipt = ManualExecutionResponseReceipt(
            execution_id=f"exec_{secrets.token_hex(4)}",
            request_id="",
            generated_at=datetime.now(UTC).isoformat(),
            status=ExecutionStatusKind.BLOCKED,
            blocked_reasons=["endpoint_not_configured"],
        )
        return _build_blocked_stdout(receipt, args)

    selection_result = None
    if args.selection_policy_receipt:
        try:
            selection_result = json.loads(
                args.selection_policy_receipt.read_text(encoding="utf-8")
            )
        except Exception:
            pass
    elif args.probe_receipt:
        selection_result = evaluate_selection_policy(
            endpoint_configured=True, endpoint_sha256=endpoint_hash, probe_result=None
        )
    else:
        selection_result = evaluate_selection_policy(
            endpoint_configured=True, endpoint_sha256=endpoint_hash
        )

    approval = None
    if args.approval_file:
        approval = _load_approval(args.approval_file)

    if args.execute and approval is None:
        receipt = ManualExecutionResponseReceipt(
            execution_id=f"exec_{secrets.token_hex(4)}",
            request_id="",
            generated_at=datetime.now(UTC).isoformat(),
            status=ExecutionStatusKind.BLOCKED,
            blocked_reasons=["approval_missing"],
        )
        return _build_blocked_stdout(receipt, args)

    request = ManualExecutionRequest(
        request_id=f"req_{secrets.token_hex(8)}",
        task_profile=args.task_profile,
        request_class=RequestClass.CHAT,
        endpoint_hash=endpoint_hash,
        prompt_sha256=prompt_sha,
        prompt_byte_count=len(prompt_bytes),
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        created_at=datetime.now(UTC).isoformat(),
    )

    gate_result = evaluate_execution_gate(
        endpoint_configured=True,
        endpoint_hash=endpoint_hash,
        selection_policy_result=selection_result,
        approval=approval,
        request=request,
    )

    if gate_result.status != ExecutionStatusKind.EXECUTED:
        return _build_blocked_stdout(gate_result, args)

    if args.execute and config and approval:
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
        status = (
            ExecutionStatusKind(result["status"])
            if result["status"]
            in {"executed", "failed", "timed_out", "malformed_response"}
            else ExecutionStatusKind.FAILED
        )
        gate_result = build_executed_receipt(
            request=request,
            status=status,
            completion_sha256=result["completion_sha256"],
            completion_byte_count=result["completion_byte_count"],
            output_token_count=result["output_token_count"],
            input_token_count=result["input_token_count"],
            latency_ms=result["latency_ms"],
            error_class=result.get("error_class", ""),
            model_safe_id=result.get("model_safe_id", ""),
            selection_policy_status=selection_result.get("result_kind", "")
            if selection_result
            else "",
        )
        gate_result.approval_id = approval.approval_id if approval else ""
        if args.print_output and result.get("ephemeral_content"):
            print(f"COMPLETION: {result['ephemeral_content']}")

    receipt_data = json.loads(gate_result.model_dump_json())
    _write(receipt_data, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich import print as rprint

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.tool_contract import (
    ToolDeterminismSummary,
    ToolDogfoodContract,
)
from vibe.core.telemetry.validation import (
    EvidenceValidationResult,
    validate_evidence_session,
)


def validation_result_to_dict(result: EvidenceValidationResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "evidence_root": str(result.evidence_root),
        "session_id": result.session_id,
        "root_mode": result.root_mode,
        "root_source": result.root_source,
        "passed_check_count": result.passed_check_count,
        "failed_checks": result.failed_checks,
        "warnings": result.warnings,
        "event_count": result.event_count,
        "referenced_file_count": result.referenced_file_count,
        "unreferenced_evidence_file_count": result.unreferenced_evidence_file_count,
        "malformed_event_count": result.malformed_event_count,
        "receipt_count": result.receipt_count,
        "receipt_chain_status": result.receipt_chain_status,
        "final_receipt_sha256": result.final_receipt_sha256,
    }


def print_validation_result(
    result: EvidenceValidationResult, *, json_output: bool = False
) -> None:
    if json_output:
        print(dump_canonical_json(validation_result_to_dict(result)))
        return

    rprint(f"[bold]status:[/] {result.status}")
    rprint(f"[bold]evidence root:[/] {result.evidence_root}")
    rprint(f"[bold]session id:[/] {result.session_id}")
    if result.root_mode is not None:
        rprint(f"[bold]root mode:[/] {result.root_mode}")
    if result.root_source is not None:
        rprint(f"[bold]root source:[/] {result.root_source}")
    rprint(f"[bold]passed checks:[/] {result.passed_check_count}")
    rprint(f"[bold]events:[/] {result.event_count}")
    rprint(f"[bold]referenced files:[/] {result.referenced_file_count}")
    rprint(
        "[bold]unreferenced evidence files:[/] "
        f"{result.unreferenced_evidence_file_count}"
    )
    rprint(f"[bold]malformed events:[/] {result.malformed_event_count}")
    rprint(f"[bold]receipts:[/] {result.receipt_count}")
    rprint(f"[bold]receipt chain status:[/] {result.receipt_chain_status}")
    if result.final_receipt_sha256:
        rprint(f"[bold]final receipt hash:[/] {result.final_receipt_sha256}")
    if result.warnings:
        rprint("[bold yellow]warnings:[/]")
        for warning in result.warnings:
            rprint(f"  - {warning}")
    if result.failed_checks:
        rprint("[bold red]failures:[/]")
        for failure in result.failed_checks:
            rprint(f"  - {failure}")


def run_evidence_validation(
    evidence_root: Path, session_id: str, *, json_output: bool = False
) -> int:
    result = validate_evidence_session(evidence_root, session_id)
    print_validation_result(result, json_output=json_output)
    return 1 if result.status == "fail" else 0


def summarize_tool_determinism(
    evidence_root: Path, session_id: str
) -> ToolDeterminismSummary:
    session_dir = evidence_root / "sessions" / session_id
    obs_path = session_dir / "observability.jsonl"

    tool_calls: list[ToolDogfoodContract] = []
    warnings: list[str] = []

    if not obs_path.exists():
        warnings.append(f"Observability log missing: {obs_path}")
        return ToolDeterminismSummary(
            session_id=session_id, tool_calls=[], warnings=warnings
        )

    with obs_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("event_name") == EventName.TOOL_CALL_COMPLETED:
                    payload = event.get("payload", {})
                    tool_calls.append(
                        ToolDogfoodContract(
                            tool_name=payload.get("tool_name", "unknown"),
                            status=payload.get("status", "unknown"),
                            tool_call_id=payload.get("tool_call_id"),
                            session_id=session_id,
                            message_id=payload.get("message_id"),
                            input_sha256=payload.get("tool_input_sha256"),
                            output_sha256=payload.get("tool_output_sha256"),
                            output_kind=payload.get("tool_output_kind", "unknown"),
                            determinism_class=payload.get(
                                "tool_determinism_class", "unknown"
                            ),
                            mutation_class=payload.get(
                                "tool_mutation_class", "unknown"
                            ),
                            agent_profile_name=payload.get("agent_profile_name"),
                            model=payload.get("model"),
                        )
                    )
            except Exception as e:
                warnings.append(f"Error parsing event: {e}")

    return ToolDeterminismSummary(
        session_id=session_id, tool_calls=tool_calls, warnings=warnings
    )


def run_tool_determinism_report(
    evidence_root: Path, session_id: str, *, json_output: bool = False
) -> int:
    summary = summarize_tool_determinism(evidence_root, session_id)

    if json_output:
        print(dump_canonical_json(summary.model_dump()))
        return 0

    rprint(f"[bold]Session ID:[/] {summary.session_id}")
    rprint(f"[bold]Tool Calls Found:[/] {len(summary.tool_calls)}")

    for i, call in enumerate(summary.tool_calls):
        rprint(f"\n[bold cyan]Tool Call {i + 1}: {call.tool_name}[/]")
        rprint(f"  [bold]Status:[/] {call.status}")
        rprint(f"  [bold]Determinism:[/] {call.determinism_class}")
        rprint(f"  [bold]Mutation:[/] {call.mutation_class}")
        rprint(f"  [bold]Output Kind:[/] {call.output_kind}")
        rprint(f"  [bold]Input Hash:[/] {call.input_sha256 or 'N/A'}")
        rprint(f"  [bold]Output Hash:[/] {call.output_sha256 or 'N/A'}")

    if summary.warnings:
        rprint("\n[bold yellow]Warnings:[/]")
        for warning in summary.warnings:
            rprint(f"  - {warning}")

    return 0

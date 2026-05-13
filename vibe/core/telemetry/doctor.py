from __future__ import annotations

from pathlib import Path
from typing import Any

from rich import print as rprint

from vibe.core.telemetry.local import dump_canonical_json
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

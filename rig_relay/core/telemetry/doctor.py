from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich import print as rprint

from rig_relay.core.telemetry.constants import EventName
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.runtime import (
    check_runtime_provenance,
    format_provenance_report,
    provenance_to_dict,
)
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolDeterminismSummary,
    ToolDogfoodContract,
    ToolMutationClass,
)
from rig_relay.core.telemetry.validation import (
    EvidenceValidationResult,
    validate_evidence_session,
)

_LATENCY_CANDIDATE_THRESHOLD_MS = 1000


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

    coverage_stats = {
        "total_calls": len(tool_calls),
        "classified_calls": sum(
            1
            for c in tool_calls
            if c.determinism_class != ToolDeterminismClass.UNKNOWN
            and c.mutation_class != ToolMutationClass.UNKNOWN
        ),
        "determinism_breakdown": {},
        "mutation_breakdown": {},
        "unclassified_tools": sorted(
            list({
                c.tool_name
                for c in tool_calls
                if c.determinism_class == ToolDeterminismClass.UNKNOWN
                or c.mutation_class == ToolMutationClass.UNKNOWN
            })
        ),
        "missing_hashes": [
            f"{c.tool_name} ({c.tool_call_id})"
            for c in tool_calls
            if not c.input_sha256 or not c.output_sha256
        ],
    }

    for c in tool_calls:
        det_key = str(c.determinism_class)
        mut_key = str(c.mutation_class)
        coverage_stats["determinism_breakdown"][det_key] = (
            coverage_stats["determinism_breakdown"].get(det_key, 0) + 1
        )
        coverage_stats["mutation_breakdown"][mut_key] = (
            coverage_stats["mutation_breakdown"].get(mut_key, 0) + 1
        )

    return ToolDeterminismSummary(
        session_id=session_id,
        tool_calls=tool_calls,
        coverage_stats=coverage_stats,
        warnings=warnings,
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

    stats = summary.coverage_stats
    rprint(
        f"[bold]Classified Calls:[/] {stats.get('classified_calls', 0)}/{stats.get('total_calls', 0)}"
    )

    if summary.tool_calls:
        rprint("\n[bold]Determinism Breakdown:[/]")
        for cat, count in sorted(stats.get("determinism_breakdown", {}).items()):
            rprint(f"  - {cat}: {count}")

        rprint("\n[bold]Mutation Breakdown:[/]")
        for cat, count in sorted(stats.get("mutation_breakdown", {}).items()):
            rprint(f"  - {cat}: {count}")

    unclassified_tools = stats.get("unclassified_tools", [])
    if unclassified_tools:
        rprint("\n[bold yellow]Unclassified Tools Found in Session:[/]")
        for tool in unclassified_tools:
            rprint(f"  - {tool}")

    missing_hashes = stats.get("missing_hashes", [])
    if missing_hashes:
        rprint("\n[bold yellow]Calls Missing Hashes:[/]")
        for item in missing_hashes:
            rprint(f"  - {item}")

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


def summarize_tool_reasoning(evidence_root: Path, session_id: str) -> dict[str, Any]:
    """Read reasoning-trace events from the observability log and build latency/pressure stats."""
    session_dir = evidence_root / "sessions" / session_id
    obs_path = session_dir / "observability.jsonl"

    traces: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not obs_path.exists():
        warnings.append(f"Observability log missing: {obs_path}")
        return {"traces": [], "warnings": warnings}

    with obs_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("event_name") == EventName.TOOL_REASONING_TRACE:
                    traces.append(event.get("payload", {}))
            except Exception as e:
                warnings.append(f"Error parsing reasoning trace event: {e}")

    if not traces:
        return {
            "traces": [],
            "warnings": warnings + ["No reasoning trace events found"],
        }

    # Compute aggregate metrics
    total_latency = sum(t.get("latency_ms", 0) for t in traces)
    total_output_bytes = sum(t.get("output_bytes", 0) for t in traces)
    total_inline_bytes = sum(t.get("inline_output_bytes", 0) for t in traces)
    total_artifacted_bytes = sum(t.get("artifacted_output_bytes", 0) for t in traces)

    # Find slowest and largest calls
    sorted_by_latency = sorted(
        traces, key=lambda t: t.get("latency_ms", 0), reverse=True
    )
    sorted_by_inline = sorted(
        traces, key=lambda t: t.get("inline_output_bytes", 0), reverse=True
    )
    sorted_by_artifacted = sorted(
        traces, key=lambda t: t.get("artifacted_output_bytes", 0), reverse=True
    )

    calls_missing_rationale = [
        t
        for t in traces
        if not t.get("tool_selection_rationale_summary")
        and t.get("tool_output_kind") != "error"
    ]

    # Check for retry patterns
    retry_groups: dict[str, list[dict[str, Any]]] = {}
    for t in traces:
        retry_of = t.get("retry_of_tool_call_id")
        if retry_of:
            retry_groups.setdefault(retry_of, []).append(t)

    return {
        "traces": traces,
        "warnings": warnings,
        "total_traces": len(traces),
        "total_latency_ms": total_latency,
        "total_output_bytes": total_output_bytes,
        "total_inline_output_bytes": total_inline_bytes,
        "total_artifacted_output_bytes": total_artifacted_bytes,
        "slowest_tool_calls": sorted_by_latency[:5],
        "largest_inline_outputs": sorted_by_inline[:5],
        "largest_artifacted_outputs": sorted_by_artifacted[:5],
        "calls_missing_rationale": calls_missing_rationale[:10],
        "retry_groups": retry_groups,
    }


def _print_tool_reasoning_report(result: dict[str, Any], session_id: str) -> None:
    rprint(f"[bold]Session ID:[/] {session_id}")
    rprint(f"[bold]Reasoning Traces Found:[/] {result.get('total_traces', 0)}")

    for warning in result.get("warnings", []):
        rprint(f"  [bold yellow]- {warning}[/]")

    if not result.get("traces"):
        return

    rprint("\n[bold]Aggregate Metrics:[/]")
    rprint(f"  Total Latency: {result['total_latency_ms']:.1f} ms")
    rprint(f"  Total Output Bytes: {result['total_output_bytes']:,}")
    rprint(f"  Inline Output Bytes: {result['total_inline_output_bytes']:,}")
    rprint(f"  Artifacted Output Bytes: {result['total_artifacted_output_bytes']:,}")

    for title, key, fmt in (
        (
            "[bold red]Slowest Tool Calls:[/]",
            "slowest_tool_calls",
            lambda t: (
                f"  {t.get('tool_name', '?')} ({t.get('latency_ms', 0):.1f} ms, {t.get('output_bytes', 0):,} bytes)"
            ),
        ),
        (
            "[bold yellow]Largest Inline Outputs (token-pressure candidates):[/]",
            "largest_inline_outputs",
            lambda t: (
                f"  {t.get('tool_name', '?')} ({t.get('inline_output_bytes', 0):,} inline bytes, kind={t.get('tool_output_kind', '?')})"
            ),
        ),
        (
            "[bold yellow]Calls Missing Rationale Summary:[/]",
            "calls_missing_rationale",
            lambda t: f"  {t.get('tool_name', '?')} ({t.get('tool_call_id', '?')})",
        ),
    ):
        items = result.get(key, [])
        if not items:
            continue
        rprint(f"\n{title}")
        for item in items:
            rprint(fmt(item))

    retries = result.get("retry_groups", {})
    if retries:
        rprint("\n[bold yellow]Retried Tool Calls:[/]")
        for orig_id, retries_list in retries.items():
            rprint(f"  Original: {orig_id}")
            for rt in retries_list:
                rprint(
                    f"    Retry: {rt.get('tool_name', '?')} ({rt.get('tool_call_id', '?')})"
                )

    slow_candidates = [
        f"  {t.get('tool_name')}: {t.get('latency_ms', 0):.1f} ms"
        for t in result.get("slowest_tool_calls", [])
        if t.get("latency_ms", 0) > _LATENCY_CANDIDATE_THRESHOLD_MS
    ]
    rprint("\n[bold]Latency Optimization Candidates:[/]")
    if slow_candidates:
        for candidate in slow_candidates:
            rprint(f"  [cyan]Slow:[/] {candidate}")
    else:
        rprint("  None (all calls under 1s threshold)")


def run_tool_reasoning_report(
    evidence_root: Path, session_id: str, *, json_output: bool = False
) -> int:
    """Print a tool reasoning and latency report for the given session."""
    result = summarize_tool_reasoning(evidence_root, session_id)
    if json_output:
        print(dump_canonical_json(result))
        return 0
    _print_tool_reasoning_report(result, session_id)
    return 0


def run_runtime_provenance_check(*, json_output: bool = False) -> int:
    """Check and report runtime provenance for the current process.

    Read-only. Reports Python executable, command path, module paths,
    git HEAD, critical symbol presence, and coherence status.
    """
    result = check_runtime_provenance()

    if json_output:
        print(dump_canonical_json(provenance_to_dict(result)))
        return 0

    report = format_provenance_report(result)

    if report:
        parts = report.split("\n")
        for line in parts:
            if line.startswith("[") and line.endswith("[/]"):
                rprint(line)
            elif line.strip():
                rprint(line)

    return 0 if result.coherent else 1

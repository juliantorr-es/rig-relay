"""Ralph scanner v0.6 — approval-ready, projection-driven background scan.

Reads report projections (preferred) or canonical findings (fallback),
detects projection-integrity issues, ranks candidates deterministically,
and produces a run-state-aware, hash-backed UI panel with decision contract.

v0.6 adds run-state models, stable content hashes, separated scan/mission
action boundaries, and projection-integrity candidate detection.
No execution, no scheduling, no mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

from rig_relay.ralph.models import (
    KIND_WEIGHTS,
    MISSION_ALLOWED_ACTIONS_DEFAULT,
    RANKING_POLICY_VERSION,
    SCAN_ALLOWED_ACTIONS,
    SEVERITY_WEIGHTS,
    ApprovalState,
    AutonomyTier,
    CandidateKind,
    InputSnapshot,
    MissionCandidate,
    RalphPanel,
    RalphPanelAction,
    RalphPanelSummary,
    RalphRunState,
    RalphScanResult,
    RankedCandidate,
    RunStatus,
    ScanInput,
    ScanStopReason,
    ScoreComponents,
    SourceRef,
)

FINDINGS_PATH = Path("docs/findings/out-of-scope-findings.jsonl")
MAX_CANDIDATES = 20
MAX_DURATION_SECONDS = 30.0
_DEFAULT_PROJECTION_DIR = Path(".rig/reports/indexes")

MISSION_KIND_FROM_CANDIDATE: dict[str, str] = {
    CandidateKind.ARCHITECTURE_SEAM: "boundary_hygiene_scout",
    CandidateKind.IMPLEMENTATION_SEAM: "boundary_hygiene_scout",
    CandidateKind.VALIDATION_GAP: "validation_patrol",
    CandidateKind.SECURITY_CONCERN: "security_audit",
    CandidateKind.DATA_RACE: "race_condition_audit",
    CandidateKind.PROJECTION_CORRUPTION: "projection_repair",
    CandidateKind.PROJECTION_INTEGRITY: "projection_integrity_audit",
    CandidateKind.DIAGNOSTIC_WARNING: "projection_repair",
    CandidateKind.STALE_CANONICAL_FINDING: "finding_triage",
    CandidateKind.CANDIDATE_FINDING_WITH_EVIDENCE: "finding_promotion_review",
    CandidateKind.DUPLICATE_CLUSTER: "dedup_sweep",
    CandidateKind.LOW_RISK_DOCS: "docs_maintenance",
    CandidateKind.LOW_RISK_PROJECTION: "projection_refresh",
}

# Ralph direct bash kind detection for bash projection items
_BASH_KIND_MAP: dict[str, str] = {
    "bash_replacement_candidates": "bash_replacement_candidate",
    "bash_risk_patterns": "bash_risk_pattern",
    "bash_timeout_clusters": "bash_timeout_cluster",
    "bash_failure_clusters": "bash_failure_cluster",
}

SEVERITY_TO_KIND: dict[str, str] = {
    "architecture_seam": CandidateKind.ARCHITECTURE_SEAM,
    "architecture_debt": CandidateKind.ARCHITECTURE_SEAM,
    "implementation_seam": CandidateKind.IMPLEMENTATION_SEAM,
    "regression_risk": CandidateKind.VALIDATION_GAP,
    "security_concern": CandidateKind.SECURITY_CONCERN,
    "data_race": CandidateKind.DATA_RACE,
    "bug_report": CandidateKind.VALIDATION_GAP,
    "refactor_candidate": CandidateKind.LOW_RISK_PROJECTION,
}

STOP_CONDITIONS_SCAN = [
    "maximum one recommended mission per scan",
    "maximum 200 reports inspected",
    "maximum 30 seconds",
    "no recursive self-triggering",
    "no mutation in observe-only mode",
    "no external network calls",
    "stop on dirty-state ambiguity",
    "stop on missing projection metadata",
    "stop on malformed policy file",
]


def scan_projections(
    findings_path: Path | None = None,
    *,
    max_duration_seconds: float = MAX_DURATION_SECONDS,
    projection_dir: Path | None = None,
) -> RalphScanResult:
    start = time.perf_counter()
    path = findings_path or FINDINGS_PATH
    proj_dir = projection_dir or _DEFAULT_PROJECTION_DIR
    scan_input = ScanInput(findings_path=str(path))
    snapshot = InputSnapshot()

    projection_findings, snapshot = _load_projections_or_fallback(
        path, proj_dir, snapshot
    )
    scan_input = _fill_scan_input(scan_input, path, snapshot)

    if time.perf_counter() - start > max_duration_seconds:
        return RalphScanResult(
            stop_reason=ScanStopReason.MAX_TIME_EXCEEDED.value,
            inputs=scan_input,
            input_snapshot=snapshot,
            scan_duration_ms=(time.perf_counter() - start) * 1000,
        )

    if not projection_findings:
        return RalphScanResult(
            stop_reason=(
                ScanStopReason.NO_PROJECTIONS.value
                if snapshot.malformed_projection_count == 0
                else ScanStopReason.MALFORMED_INPUT.value
            ),
            inputs=scan_input,
            input_snapshot=snapshot,
            total_findings_inspected=snapshot.malformed_projection_count,
            scan_duration_ms=(time.perf_counter() - start) * 1000,
        )

    open_findings = [f for f in projection_findings if f.get("status") == "open"]
    candidates = _rank_candidates(open_findings)
    mission = _build_mission_candidate(candidates[0]) if candidates else None

    return RalphScanResult(
        stop_reason=ScanStopReason.COMPLETED.value
        if candidates
        else ScanStopReason.NO_CANDIDATES.value,
        inputs=scan_input,
        input_snapshot=snapshot,
        total_findings_inspected=len(projection_findings),
        candidates_considered=len(open_findings),
        ranked_candidates=candidates[:MAX_CANDIDATES],
        mission_candidate=mission,
        scan_duration_ms=(time.perf_counter() - start) * 1000,
    )


def build_ralph_panel(result: RalphScanResult) -> RalphPanel:
    mission_sha = ""
    if result.mission_candidate:
        mission_sha = _compute_content_hash(
            result.mission_candidate.model_dump(mode="json")
        )

    snapshot_sha = ""
    if result.input_snapshot:
        snapshot_sha = _compute_content_hash(
            result.input_snapshot.model_dump(mode="json")
        )

    panel = RalphPanel(
        status="ready" if result.ranked_candidates else "idle",
        summary=RalphPanelSummary(
            candidate_count=len(result.ranked_candidates),
            top_score=result.ranked_candidates[0].score
            if result.ranked_candidates
            else 0.0,
            top_severity=result.ranked_candidates[0].severity
            if result.ranked_candidates
            else "none",
            input_source=(
                result.input_snapshot.input_source
                if result.input_snapshot
                else "unknown"
            ),
            stop_reason=result.stop_reason,
            ranking_policy_version=result.ranking_policy_version,
        ),
        top_candidate=result.ranked_candidates[0] if result.ranked_candidates else None,
        ranked_candidates=result.ranked_candidates[:5],
        mission_candidate=result.mission_candidate,
        available_actions=[
            RalphPanelAction(
                action="approve_read_only_mission",
                label="Review safely",
                requires_confirmation=True,
            ),
            RalphPanelAction(
                action="decline", label="Decline", requires_confirmation=True
            ),
            RalphPanelAction(
                action="rescan", label="Rescan", requires_confirmation=False
            ),
        ],
        decision_required=bool(result.mission_candidate),
        approval_state=ApprovalState.PENDING.value
        if result.mission_candidate
        else ApprovalState.NOT_REQUESTED.value,
        mission_candidate_sha256=mission_sha,
        input_snapshot_sha256=snapshot_sha,
    )

    panel.panel_sha256 = _compute_content_hash(
        panel.model_dump(mode="json", exclude={"panel_sha256", "generated_at"})
    )
    return panel


def build_run_state(panel: RalphPanel) -> RalphRunState:
    has_mission = panel.decision_required and panel.top_candidate is not None
    return RalphRunState(
        status=(
            RunStatus.AWAITING_USER_DECISION.value
            if has_mission
            else RunStatus.IDLE.value
        ),
        phase="mission_candidate_review" if has_mission else "scan",
        scan_id=panel.summary.stop_reason,
        panel_sha256=panel.panel_sha256,
        mission_candidate_sha256=panel.mission_candidate_sha256,
        selected_candidate_id=panel.top_candidate.candidate_id
        if panel.top_candidate
        else "",
        approval_state=panel.approval_state,
    )


def compute_decision_request(panel: RalphPanel) -> Any:
    if not panel.top_candidate or not panel.mission_candidate:
        return None
    from rig_relay.ralph.models import RalphDecisionRequest

    return RalphDecisionRequest(
        scan_id=panel.summary.stop_reason,
        candidate_id=panel.top_candidate.candidate_id,
        panel_sha256=panel.panel_sha256,
        mission_candidate_sha256=panel.mission_candidate_sha256,
        approval_state=ApprovalState.PENDING.value,
        requested_actions=list(panel.mission_candidate.allowed_actions),
        forbidden_actions=list(panel.mission_candidate.forbidden_actions),
    )


def compute_decision_result(
    decision_id: str,
    scan_id: str,
    candidate_id: str,
    decision: str,
    rationale: str = "",
) -> Any:
    from rig_relay.ralph.models import RalphDecisionResult

    return RalphDecisionResult(
        decision_id=decision_id,
        scan_id=scan_id,
        candidate_id=candidate_id,
        decision=decision,
        rationale=rationale,
        next_phase="execution"
        if decision == ApprovalState.APPROVED.value
        else "closed",
    )


def _load_projections_or_fallback(
    findings_path: Path, proj_dir: Path, snapshot: InputSnapshot
) -> tuple[list[dict[str, Any]], InputSnapshot]:
    projections = _load_projection_findings(proj_dir, snapshot)
    if projections:
        return projections, snapshot

    fallback = _load_canonical_findings(findings_path)
    if fallback:
        snapshot.canonical_fallback_used = True
        snapshot.input_source = "canonical_findings_fallback"
        snapshot.input_hashes = {}
        try:
            raw = findings_path.read_bytes()
            snapshot.input_hashes = {
                str(findings_path): hashlib.sha256(raw).hexdigest()
            }
        except OSError:
            pass
        return fallback, snapshot

    snapshot.input_source = "none"
    return [], snapshot


def _load_projection_findings(
    proj_dir: Path, snapshot: InputSnapshot
) -> list[dict[str, Any]]:
    paths = [
        proj_dir / "candidate_findings.json",
        proj_dir / "report_diagnostics.json",
        proj_dir / "open_raw_reports.json",
        proj_dir / "report_summary.json",
    ]

    any_found = False
    all_findings: list[dict[str, Any]] = []

    for p in paths:
        if not p.is_file():
            continue
        any_found = True
        try:
            raw = p.read_bytes()
            snapshot.input_hashes[str(p)] = hashlib.sha256(raw).hexdigest()
            data = json.loads(raw)
            items = _extract_findings_from_projection(data, p.name)
            for item in items:
                item["_source_filename"] = p.name
            all_findings.extend(items)
        except (json.JSONDecodeError, OSError):
            snapshot.malformed_projection_count += 1

    if any_found:
        snapshot.input_source = "report_projections"
        snapshot.projection_paths = [str(p) for p in paths if p.is_file()]
    else:
        snapshot.input_source = "no_projections_found"

    if snapshot.malformed_projection_count > 0:
        all_findings.append({
            "finding_id": f"proj_integrity_{_ts()}",
            "status": "open",
            "severity": "high",
            "finding_kind": "projection_integrity",
            "title": "Malformed projection data detected — projection integrity audit recommended",
            "why_it_matters": (
                f"{snapshot.malformed_projection_count} projection file(s) "
                f"contain unparseable JSON. Projections may be incomplete."
            ),
            "related_files": [],
        })

    return all_findings


def _extract_findings_from_projection(data: Any, filename: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if isinstance(data, dict):
        candidates = (
            data.get("findings") or data.get("candidates") or data.get("items") or []
        )
        if isinstance(candidates, list):
            items.extend(candidates)
        if data.get("status") == "open" and data.get("finding_id"):
            items.append(data)

    elif isinstance(data, list):
        items.extend(data)

    return items


def _load_canonical_findings(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("finding_id"):
                    findings.append(obj)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return findings


def _fill_scan_input(
    scan_input: ScanInput, path: Path, snapshot: InputSnapshot
) -> ScanInput:
    scan_input.findings_path = str(path)
    for i, p in enumerate(snapshot.projection_paths):
        if i == 0:
            scan_input.report_summary_path = p
        elif "diagnostic" in p.lower():
            scan_input.report_diagnostics_path = p
        elif "candidate" in p.lower():
            scan_input.candidate_findings_path = p
        elif "open" in p.lower():
            scan_input.open_raw_reports_path = p
    return scan_input


def _rank_candidates(findings: list[dict[str, Any]]) -> list[RankedCandidate]:
    candidates: list[RankedCandidate] = []

    for f in findings:
        candidate = _to_candidate(f)
        if candidate is None:
            continue
        severity_w = SEVERITY_WEIGHTS.get(candidate.severity, 2.0)
        kind_w = KIND_WEIGHTS.get(candidate.source_kind, 1.0)
        evidence_b = 2.0 if candidate.reason else 0.0
        staleness_w = 0.0
        diagnostic_w = (
            KIND_WEIGHTS.get(CandidateKind.DIAGNOSTIC_WARNING, 10.0)
            if candidate.source_kind == CandidateKind.DIAGNOSTIC_WARNING
            else 0.0
        )
        integrity_w = (
            KIND_WEIGHTS.get(CandidateKind.PROJECTION_INTEGRITY, 20.0)
            if candidate.source_kind == CandidateKind.PROJECTION_INTEGRITY
            else 0.0
        )

        candidate.score_components = ScoreComponents(
            severity_weight=severity_w,
            kind_weight=kind_w,
            evidence_bonus=evidence_b,
            staleness_weight=staleness_w,
            diagnostic_weight=diagnostic_w,
            recurrence_weight=integrity_w,
            total_score=severity_w
            + kind_w
            + evidence_b
            + staleness_w
            + diagnostic_w
            + integrity_w,
        )
        candidate.score = candidate.score_components.total_score
        candidate.ranking_policy_version = RANKING_POLICY_VERSION
        candidates.append(candidate)

    candidates.sort(key=lambda c: -c.score)

    deduped: list[RankedCandidate] = []
    seen_titles: set[str] = set()
    for c in candidates:
        title_prefix = c.title[:40].lower()
        if title_prefix in seen_titles:
            continue
        seen_titles.add(title_prefix)
        deduped.append(c)

    return deduped


def _to_candidate(finding: dict[str, Any]) -> RankedCandidate | None:
    # Detect bash projection items by source_filename annotation
    source_filename = finding.pop("_source_filename", "")
    base = Path(source_filename).stem
    bash_kind = _BASH_KIND_MAP.get(base)

    if bash_kind:
        command_family = finding.get("command_family", "")
        command_text = finding.get("command_text", "")
        title = f"Bash {bash_kind.replace('bash_', '').replace('_', ' ')}: {command_family or command_text[:60] or 'unknown'}"
        candidate_id = f"ralph_bash_{hashlib.sha256(command_text.encode()).hexdigest()[:12] if command_text else base}"
        invocation_count = finding.get(
            "invocation_count",
            finding.get("failure_count", finding.get("timeout_count", 0)),
        )
        severity = (
            "medium" if invocation_count and int(invocation_count) >= 3 else "low"
        )
        replacement = finding.get("replacement_candidate", "")
        reason = (
            f"{replacement} replacement candidate"
            if replacement
            else f"{invocation_count} occurrences"
            if invocation_count
            else bash_kind
        )
        return RankedCandidate(
            candidate_id=candidate_id,
            source_kind=bash_kind,
            title=title,
            severity=severity,
            status="open",
            reason=reason[:200],
            recommended_mission_kind=MISSION_KIND_FROM_CANDIDATE.get(
                bash_kind, "bash_safety_audit"
            ),
            risk_tier=AutonomyTier.OBSERVE,
            requires_approval_for_execution=True,
            related_files=[],
        )

    finding_kind = finding.get("finding_kind", "")
    severity = finding.get("severity", "low")
    source_kind = SEVERITY_TO_KIND.get(finding_kind)
    if source_kind is None:
        if finding_kind == "projection_integrity":
            source_kind = CandidateKind.PROJECTION_INTEGRITY
        else:
            source_kind = CandidateKind.LOW_RISK_PROJECTION

    return RankedCandidate(
        candidate_id=f"ralph_{finding['finding_id']}",
        source_kind=source_kind,
        source_finding_id=finding["finding_id"],
        title=finding.get("title", "Unnamed finding"),
        severity=severity,
        status=finding.get("status", "open"),
        reason=finding.get("why_it_matters", "")[:200],
        recommended_mission_kind=MISSION_KIND_FROM_CANDIDATE.get(
            source_kind, "read_only_audit"
        ),
        risk_tier=AutonomyTier.OBSERVE,
        requires_approval_for_execution=True,
        related_files=finding.get("related_files", []),
        scan_allowed_actions=list(SCAN_ALLOWED_ACTIONS),
    )


def _build_mission_candidate(top: RankedCandidate) -> MissionCandidate:
    return MissionCandidate(
        candidate_id=top.candidate_id,
        title=top.title,
        mission_kind=top.recommended_mission_kind,
        source_refs=[SourceRef(kind="finding", id=top.source_finding_id or "")],
        allowed_actions=list(MISSION_ALLOWED_ACTIONS_DEFAULT),
        requires_approval=True,
        required_autonomy_tier=AutonomyTier.OBSERVE,
    )


def _compute_content_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ts() -> str:
    return str(int(time.time() * 1000))


__all__ = [
    "STOP_CONDITIONS_SCAN",
    "build_ralph_panel",
    "build_run_state",
    "compute_decision_request",
    "compute_decision_result",
    "scan_projections",
]

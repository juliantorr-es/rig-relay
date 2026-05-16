from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.ralph.models import (
    SCAN_ALLOWED_ACTIONS,
    ApprovalState,
    CandidateKind,
    RalphRunState,
    RunStatus,
    ScanStopReason,
)
from rig_relay.ralph.scanner import (
    build_ralph_panel,
    build_run_state,
    compute_decision_request,
    compute_decision_result,
    scan_projections,
)

pytestmark = [pytest.mark.integration]

def test_empty_projections_produces_no_candidate(tmp_path: Path):
    nonexistent = tmp_path / "nonexistent.jsonl"
    result = scan_projections(findings_path=nonexistent)

    assert result.stop_reason == ScanStopReason.NO_PROJECTIONS.value
    assert result.ranked_candidates == []
    assert result.mission_candidate is None
    assert result.total_findings_inspected == 0
    assert result.input_snapshot is not None


def test_canonical_fallback_works(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"high","finding_kind":"security_concern","title":"Hole","why_it_matters":"bad","related_files":["a.py"]}\n'
    )

    result = scan_projections(findings_path=findings_path)

    assert result.stop_reason == ScanStopReason.COMPLETED.value
    assert result.input_snapshot.canonical_fallback_used
    assert result.input_snapshot.input_source == "canonical_findings_fallback"
    assert len(result.ranked_candidates) >= 1


def test_projections_preferred_over_fallback(tmp_path: Path):
    proj_dir = tmp_path / ".rig" / "reports" / "indexes"
    proj_dir.mkdir(parents=True)

    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"fallback1","status":"open","severity":"critical","finding_kind":"security_concern","title":"Fallback","why_it_matters":"e"}\n'
    )

    candidate_json = proj_dir / "candidate_findings.json"
    candidate_json.write_text(json.dumps({
        "findings": [
            {"finding_id": "proj1", "status": "open", "severity": "medium",
             "finding_kind": "architecture_seam", "title": "Projection finding", "why_it_matters": "real"}
        ]
    }))

    result = scan_projections(findings_path=findings_path, projection_dir=proj_dir)

    assert not result.input_snapshot.canonical_fallback_used
    assert result.input_snapshot.input_source == "report_projections"
    assert result.ranked_candidates[0].source_finding_id == "proj1"


def test_malformed_projections_injected_as_candidate(tmp_path: Path):
    proj_dir = tmp_path / ".rig" / "reports" / "indexes"
    proj_dir.mkdir(parents=True)

    bad_json = proj_dir / "candidate_findings.json"
    bad_json.write_text("not json {{")

    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )

    result = scan_projections(findings_path=findings_path, projection_dir=proj_dir)

    assert result.input_snapshot.malformed_projection_count >= 1
    assert not result.input_snapshot.canonical_fallback_used
    assert result.input_snapshot.input_source == "report_projections"

    integrity = [c for c in result.ranked_candidates if c.source_kind == CandidateKind.PROJECTION_INTEGRITY]
    assert len(integrity) >= 0


def test_ranked_candidates_have_scan_allowed_actions(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"high","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"evidence"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    top = result.ranked_candidates[0]

    assert len(top.scan_allowed_actions) > 0
    assert "read projections" in top.scan_allowed_actions
    assert "compute deterministic ranking" in top.scan_allowed_actions
    for action in top.scan_allowed_actions:
        assert "source-code mutation" not in action


def test_mission_candidate_actions_distinct_from_scan(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"high","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    mission = result.mission_candidate

    assert mission is not None
    assert mission.allowed_actions != SCAN_ALLOWED_ACTIONS
    assert "read files" in mission.allowed_actions
    assert "compute deterministic ranking" not in mission.allowed_actions
    for a in SCAN_ALLOWED_ACTIONS:
        if "read" not in a:
            assert a not in mission.allowed_actions, f"scan action leaked into mission: {a}"


def test_panel_has_stable_hashes(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam A","why_it_matters":"evidence"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    panel = build_ralph_panel(result)

    assert len(panel.panel_sha256) == 64
    assert len(panel.mission_candidate_sha256) == 64
    assert panel.panel_sha256 != panel.mission_candidate_sha256

    panel2 = build_ralph_panel(result)
    assert panel.panel_sha256 == panel2.panel_sha256
    assert panel.mission_candidate_sha256 == panel2.mission_candidate_sha256


def test_panel_decision_required_when_mission_present(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    panel = build_ralph_panel(result)

    assert panel.decision_required is True
    assert panel.approval_state == ApprovalState.PENDING.value


def test_panel_idle_with_no_candidates(tmp_path: Path):
    nonexistent = tmp_path / "none.jsonl"
    result = scan_projections(findings_path=nonexistent)
    panel = build_ralph_panel(result)

    assert panel.status == "idle"
    assert panel.decision_required is False
    assert panel.approval_state == ApprovalState.NOT_REQUESTED.value
    assert len(panel.panel_sha256) > 0


def test_run_state_created_from_panel(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    panel = build_ralph_panel(result)
    state = build_run_state(panel)

    assert isinstance(state, RalphRunState)
    assert state.status == RunStatus.AWAITING_USER_DECISION.value
    assert state.phase == "mission_candidate_review"
    assert state.panel_sha256 == panel.panel_sha256
    assert state.mission_candidate_sha256 == panel.mission_candidate_sha256
    assert state.approval_state == ApprovalState.PENDING.value
    assert state.selected_candidate_id != ""


def test_run_state_idle_when_no_candidates(tmp_path: Path):
    nonexistent = tmp_path / "none.jsonl"
    result = scan_projections(findings_path=nonexistent)
    panel = build_ralph_panel(result)
    state = build_run_state(panel)

    assert state.status == RunStatus.IDLE.value
    assert state.phase == "scan"
    assert state.selected_candidate_id == ""


def test_decision_request_and_result_are_structured(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    panel = build_ralph_panel(result)

    req = compute_decision_request(panel)
    assert req is not None
    assert req.schema_version == "rig.ralph_decision_request.v1"
    assert req.approval_state == ApprovalState.PENDING.value
    assert len(req.requested_actions) > 0
    assert len(req.forbidden_actions) > 0
    assert req.candidate_id == panel.top_candidate.candidate_id

    res = compute_decision_result(
        decision_id=req.decision_id,
        scan_id=req.scan_id,
        candidate_id=req.candidate_id,
        decision=ApprovalState.APPROVED.value,
        rationale="Looks good",
    )
    assert res.decision == ApprovalState.APPROVED.value
    assert res.next_phase == "execution"

    declined = compute_decision_result(
        decision_id=req.decision_id,
        scan_id=req.scan_id,
        candidate_id=req.candidate_id,
        decision=ApprovalState.DECLINED.value,
    )
    assert declined.decision == ApprovalState.DECLINED.value
    assert declined.next_phase == "closed"


def test_decision_none_when_no_candidates(tmp_path: Path):
    nonexistent = tmp_path / "none.jsonl"
    result = scan_projections(findings_path=nonexistent)
    panel = build_ralph_panel(result)

    req = compute_decision_request(panel)
    assert req is None


def test_scanner_never_writes_to_disk(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"A seam"}\n'
    )

    mtime_before = findings_path.stat().st_mtime
    scan_projections(findings_path=findings_path)
    mtime_after = findings_path.stat().st_mtime

    assert mtime_before == mtime_after


def test_scanner_output_is_deterministic(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam A","why_it_matters":"evidence"}\n'
        '{"finding_id":"f2","status":"open","severity":"low","finding_kind":"bug_report","title":"Bug B","why_it_matters":"evidence"}\n'
    )

    r1 = scan_projections(findings_path=findings_path)
    r2 = scan_projections(findings_path=findings_path)

    assert len(r1.ranked_candidates) == len(r2.ranked_candidates)
    for c1, c2 in zip(r1.ranked_candidates, r2.ranked_candidates):
        assert c1.score == c2.score
        assert c1.source_finding_id == c2.source_finding_id


def test_duplicate_titles_are_deduped(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Dup","why_it_matters":"first"}\n'
        '{"finding_id":"f2","status":"open","severity":"high","finding_kind":"architecture_seam","title":"Dup","why_it_matters":"second"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    assert len(result.ranked_candidates) == 1
    assert result.ranked_candidates[0].source_finding_id == "f2"


def test_score_components_present(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"high","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"evidence"}\n'
    )

    result = scan_projections(findings_path=findings_path)
    top = result.ranked_candidates[0]

    assert top.ranking_policy_version == "ralph.ranking.v0"
    assert top.score_components.severity_weight > 0
    assert top.score_components.kind_weight > 0
    assert top.score_components.evidence_bonus > 0
    assert top.score_components.total_score == top.score


def test_malformed_input_handled_gracefully(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text("not valid json\n{\"garbage\": true}\n")

    result = scan_projections(findings_path=findings_path)
    assert result.total_findings_inspected == 0
    assert result.ranked_candidates == []

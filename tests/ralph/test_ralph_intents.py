from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

from rig_relay.desktop.ralph_intents import (
    _RALPH_STATE,
    build_ralph_projection,
    execute_ralph_intent,
)


def test_ralph_scan_returns_intent_envelope():
    result = execute_ralph_intent("ralph_scan")

    assert result["schema_version"] == "rig.desktop.intent_result.v1"
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["error_code"] is None
    assert "message" in result
    assert result["execution_enabled"] is False
    assert result["ralph"]["panel"] is not None


def test_idle_projection_when_no_scan():
    import rig_relay.desktop.ralph_intents as ri

    ri._RALPH_STATE.clear()

    proj = build_ralph_projection()

    assert proj["schema_version"] == "rig.ui.ralph_panel.v1"
    assert proj["status"] == "idle"
    assert proj["decision_required"] is False
    assert proj["top_candidate"] is None


def test_projection_after_scan():
    execute_ralph_intent("ralph_scan")
    proj = build_ralph_projection()

    assert proj["status"] == "ready"
    assert proj["run_id"] != ""
    assert proj["scan_id"] != ""
    assert len(proj["panel_sha256"]) == 64
    assert proj["execution_enabled"] is False


def test_approve_with_identity_binding():
    scan = execute_ralph_intent("ralph_scan")
    panel = scan["ralph"]["panel"]

    state = _RALPH_STATE
    run_id = state["run_id"]
    scan_id = state["scan_id"]

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "run_id": run_id,
            "scan_id": scan_id,
            "panel_sha256": panel["panel_sha256"],
            "mission_candidate_sha256": panel["mission_candidate_sha256"],
        },
    )

    assert result["ok"] is True
    assert result["status"] == "completed"


def test_approve_refuses_stale_run_id():
    execute_ralph_intent("ralph_scan")

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "run_id": "00000000-0000-0000-0000-000000000000",
            "panel_sha256": "a" * 64,
            "mission_candidate_sha256": "b" * 64,
        },
    )

    assert result["ok"] is False
    assert result["status"] == "refused"
    assert result["error_code"] == "stale_run_id"


def test_approve_refuses_stale_scan_id():
    execute_ralph_intent("ralph_scan")

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "scan_id": "wrong-scan-id",
            "panel_sha256": "a" * 64,
            "mission_candidate_sha256": "b" * 64,
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "stale_scan_id"


def test_scan_a_rescan_b_approve_a_refused():
    scan_a = execute_ralph_intent("ralph_scan")
    panel_a = scan_a["ralph"]["panel"]
    run_id_a = _RALPH_STATE["run_id"]

    execute_ralph_intent("ralph_rescan")

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "run_id": run_id_a,
            "scan_id": panel_a.get("scan_id", ""),
            "panel_sha256": panel_a["panel_sha256"],
            "mission_candidate_sha256": panel_a["mission_candidate_sha256"],
        },
    )

    assert result["ok"] is False
    assert result["error_code"] in ("stale_run_id", "stale_scan_id")


def test_rescan_invalidates_previous_decline():
    scan_a = execute_ralph_intent("ralph_scan")
    panel_a = scan_a["ralph"]["panel"]
    run_id_a = _RALPH_STATE["run_id"]

    execute_ralph_intent("ralph_rescan")

    result = execute_ralph_intent(
        "ralph_decline",
        params={
            "run_id": run_id_a,
            "panel_sha256": panel_a["panel_sha256"],
            "mission_candidate_sha256": panel_a["mission_candidate_sha256"],
        },
    )

    assert result["ok"] is False


def test_approve_fails_with_stale_panel_hash():
    scan = execute_ralph_intent("ralph_scan")
    panel = scan["ralph"]["panel"]

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "panel_sha256": "0" * 64,
            "mission_candidate_sha256": panel["mission_candidate_sha256"],
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "stale_panel_hash"


def test_approve_fails_with_stale_mission_hash():
    scan = execute_ralph_intent("ralph_scan")
    panel = scan["ralph"]["panel"]

    result = execute_ralph_intent(
        "ralph_approve",
        params={
            "panel_sha256": panel["panel_sha256"],
            "mission_candidate_sha256": "0" * 64,
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "stale_mission_hash"


def test_approve_fails_without_prior_scan():
    _RALPH_STATE.clear()

    result = execute_ralph_intent(
        "ralph_approve",
        params={"panel_sha256": "a" * 64, "mission_candidate_sha256": "b" * 64},
    )

    assert result["ok"] is False
    assert result["error_code"] == "no_scan_state"


def test_approve_fails_with_missing_hashes():
    result = execute_ralph_intent("ralph_approve", params={})

    assert result["ok"] is False
    assert result["error_code"] == "invalid_payload"


def test_decline_succeeds():
    scan = execute_ralph_intent("ralph_scan")
    panel = scan["ralph"]["panel"]

    result = execute_ralph_intent(
        "ralph_decline",
        params={
            "panel_sha256": panel["panel_sha256"],
            "mission_candidate_sha256": panel["mission_candidate_sha256"],
        },
    )

    assert result["ok"] is True
    assert result["next_phase"] == "closed"
    assert result["execution_enabled"] is False


def test_rescan_returns_fresh_panel():
    scan1 = execute_ralph_intent("ralph_scan")
    scan2 = execute_ralph_intent("ralph_rescan")

    assert scan1["ok"] is True
    assert scan2["ok"] is True
    assert scan2["ralph"]["panel"]["panel_sha256"] != ""


def test_unknown_intent_returns_refusal():
    result = execute_ralph_intent("ralph_nonexistent")
    assert result["ok"] is False
    assert result["error_code"] == "unsupported_action"


def test_execution_flag_never_true():
    _RALPH_STATE.clear()

    scan = execute_ralph_intent("ralph_scan")
    panel = scan["ralph"]["panel"]
    approve = execute_ralph_intent(
        "ralph_approve",
        params={
            "panel_sha256": panel["panel_sha256"],
            "mission_candidate_sha256": panel["mission_candidate_sha256"],
        },
    )

    scan2 = execute_ralph_intent("ralph_scan")
    panel2 = scan2["ralph"]["panel"]
    decline = execute_ralph_intent(
        "ralph_decline",
        params={
            "panel_sha256": panel2["panel_sha256"],
            "mission_candidate_sha256": panel2["mission_candidate_sha256"],
        },
    )

    assert scan["execution_enabled"] is False
    assert approve["execution_enabled"] is False
    assert decline["execution_enabled"] is False


def test_no_disk_writes(tmp_path: Path):
    findings_path = tmp_path / "findings.jsonl"
    findings_path.write_text(
        '{"finding_id":"f1","status":"open","severity":"medium","finding_kind":"architecture_seam","title":"Seam","why_it_matters":"e"}\n'
    )
    mtime_before = findings_path.stat().st_mtime

    _RALPH_STATE.clear()
    execute_ralph_intent("ralph_scan")
    execute_ralph_intent(
        "ralph_approve",
        params={"panel_sha256": "any", "mission_candidate_sha256": "any"},
    )

    assert findings_path.stat().st_mtime == mtime_before


def test_refusal_is_structured():
    _RALPH_STATE.clear()
    result = execute_ralph_intent(
        "ralph_approve",
        params={"panel_sha256": "a" * 64, "mission_candidate_sha256": "b" * 64},
    )

    assert result["ok"] is False
    assert result["schema_version"] == "rig.desktop.intent_result.v1"
    assert result["status"] == "refused"
    assert result["error_code"] is not None
    assert result["message"] is not None
    assert result["execution_enabled"] is False


def test_all_refusal_codes_have_messages():
    from rig_relay.desktop.ralph_intents import REFUSAL_CODES

    for code, msg in REFUSAL_CODES.items():
        assert msg, f"Refusal code {code} has no message"


def test_ralph_scan_has_run_id_and_scan_id():
    _RALPH_STATE.clear()

    result = execute_ralph_intent("ralph_scan")
    panel = result["ralph"]["panel"]

    stored = _RALPH_STATE
    assert stored["run_id"] != ""
    assert stored["scan_id"] != ""
    assert panel["panel_sha256"] == stored["panel_sha256"]

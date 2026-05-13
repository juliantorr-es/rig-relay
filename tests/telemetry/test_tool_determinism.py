from __future__ import annotations

from pathlib import Path

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.doctor import summarize_tool_determinism
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
    ToolOutputKind,
)


def _write_event(log_file: Path, event: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(dump_canonical_json(event))
        handle.write("\n")


def _event(session_id: str, event_name: str, payload: dict) -> dict:
    return {
        "schema_version": "rig.relay.observability.v1",
        "session_id": session_id,
        "event_name": event_name,
        "payload": payload,
    }


def test_summarize_tool_determinism_captures_fields(tmp_path):
    session_id = "session-test"
    evidence_root = tmp_path / "evidence"
    session_root = evidence_root / "sessions" / session_id
    obs_path = session_root / "observability.jsonl"

    payload = {
        "tool_name": "read_file",
        "status": "success",
        "tool_input_sha256": "in-abc",
        "tool_output_sha256": "out-abc",
        "tool_output_kind": ToolOutputKind.INLINE,
        "tool_mutation_class": ToolMutationClass.READ_ONLY,
        "tool_determinism_class": ToolDeterminismClass.DETERMINISTIC_REPO_STATE,
        "message_id": "msg-1",
    }

    _write_event(obs_path, _event(session_id, EventName.TOOL_CALL_COMPLETED, payload))

    summary = summarize_tool_determinism(evidence_root, session_id)

    assert len(summary.tool_calls) == 1
    call = summary.tool_calls[0]
    assert call.tool_name == "read_file"
    assert call.input_sha256 == "in-abc"
    assert call.output_sha256 == "out-abc"
    assert call.output_kind == ToolOutputKind.INLINE
    assert call.mutation_class == ToolMutationClass.READ_ONLY
    assert call.determinism_class == ToolDeterminismClass.DETERMINISTIC_REPO_STATE


def test_summarize_tool_determinism_warns_on_missing_log(tmp_path):
    session_id = "session-missing"
    evidence_root = tmp_path / "evidence"

    summary = summarize_tool_determinism(evidence_root, session_id)

    assert len(summary.tool_calls) == 0
    assert any("Observability log missing" in w for w in summary.warnings)

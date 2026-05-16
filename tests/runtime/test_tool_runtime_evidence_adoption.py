from __future__ import annotations

import hashlib

from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus
from rig_relay.runtime.supervisor_result import (
    RuntimeSupervisorCommandDigest,
    RuntimeSupervisorOutputDigest,
    RuntimeSupervisorResourceUsage,
    RuntimeSupervisorResultClassification,
    RuntimeSupervisorResultEnvelope,
    RuntimeSupervisorTiming,
    build_runtime_supervisor_result_envelope,
)


def _make_envelope(
    classification: str = "completed",
) -> RuntimeSupervisorResultEnvelope:
    return build_runtime_supervisor_result_envelope(
        command=RuntimeSupervisorCommandDigest(
            executable="python",
            argv_hash=hashlib.sha256(b"python -c pass").hexdigest()[:16],
            argc=3,
            cwd_hash=hashlib.sha256(b"/tmp").hexdigest()[:16],
            cwd_kind="temp",
        ),
        cwd={"hash": "abc", "kind": "temp"},
        state_projection={"current_state": "running"},
        classification=classification,
        resource_usage=RuntimeSupervisorResourceUsage(exit_code=0),
        output=RuntimeSupervisorOutputDigest(
            stdout_sha256=hashlib.sha256(b"ok").hexdigest(),
            stderr_sha256=hashlib.sha256(b"").hexdigest(),
            stdout_bytes=3,
            stderr_bytes=0,
        ),
        timing=RuntimeSupervisorTiming(duration_ms=15.0),
    )


def test_completed_envelope_maps_to_success():
    env = _make_envelope("completed")
    assert env.classification == RuntimeSupervisorResultClassification.COMPLETED
    assert env.resource_usage.exit_code == 0


def test_failed_envelope_preserves_classification():
    env = _make_envelope("failed")
    assert env.classification == RuntimeSupervisorResultClassification.FAILED


def test_timed_out_envelope_preserved():
    env = _make_envelope("timed_out")
    assert env.classification == RuntimeSupervisorResultClassification.TIMED_OUT


def test_killed_envelope_preserved():
    env = _make_envelope("killed")
    assert env.classification == RuntimeSupervisorResultClassification.KILLED


def test_refused_envelope_preserved():
    env = _make_envelope("refused")
    assert env.classification == RuntimeSupervisorResultClassification.REFUSED


def test_envelope_sha256_is_stable():
    env1 = _make_envelope("completed")
    env2 = _make_envelope("completed")
    sha1 = hashlib.sha256(env1.model_dump_json().encode()).hexdigest()
    sha2 = hashlib.sha256(env2.model_dump_json().encode()).hexdigest()
    assert sha1 == sha2, "Envelope sha256 should be stable for same classification"


def test_envelope_carries_trace_ids():
    env = _make_envelope("completed")
    assert env.trace_id is None  # No trace context in default build
    assert env.result_id.startswith("sha256:")


def test_tool_result_carries_envelope_fields():
    result = ToolRuntimeResult(
        status=ToolRuntimeStatus.COMPLETED,
        tool_name="bash",
        tool_call_id="c1",
        supervisor_result_envelope_id="env_001",
        supervisor_result_envelope_sha256="sha256:abc123",
        supervisor_result_classification="completed",
    )
    assert result.supervisor_result_envelope_id == "env_001"
    assert result.supervisor_result_envelope_sha256 == "sha256:abc123"
    assert result.supervisor_result_classification == "completed"


def test_envelope_has_no_raw_output():
    env = _make_envelope("completed")
    d = env.model_dump(mode="json")
    assert "stdout_text" not in d
    assert "stderr_text" not in d
    assert "command_text" not in d
    assert "cwd_path" not in d
    assert "stdout" not in d.get("output", {}), (
        "Raw stdout should not be in output digest"
    )
    assert "stderr" not in d.get("output", {}), (
        "Raw stderr should not be in output digest"
    )
    assert "stdout_sha256" in d.get("output", {})
    assert "stderr_sha256" in d.get("output", {})


def test_classification_mapping_is_complete():
    all_classifications = {e.value for e in RuntimeSupervisorResultClassification}
    expected = {
        "completed",
        "failed",
        "timed_out",
        "killed",
        "cancelled",
        "spawn_failed",
        "cleanup_failed",
        "errored",
        "refused",
    }
    assert all_classifications == expected

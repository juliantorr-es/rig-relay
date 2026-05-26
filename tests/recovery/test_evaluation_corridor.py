"""Test evaluation corridor — real manifest, D0 pipeline, content-light events."""

from __future__ import annotations

import json
from pathlib import Path

from rig_relay.recovery.evaluation import evaluate_cases
from rig_relay.recovery.models import CanonicalToolSurfaceManifest


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _make_manifest() -> CanonicalToolSurfaceManifest:
    from rig_relay.recovery.models import AdmittedToolEntry, RecoveryAdmissionTier

    return CanonicalToolSurfaceManifest(
        manifest_id="eval-test",
        generated_at="2026-01-01T00:00:00Z",
        manifest_digest=_sha256("eval-manifest"),
        admitted_tools=[
            AdmittedToolEntry(
                canonical_name="read_file",
                aliases=["read-file"],
                mutation_class="read_only",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("rf"),
                arg_field_names=["file_path"],
                recovery_admission_tier=RecoveryAdmissionTier.READ_ONLY_RECOVERABLE,
            ),
            AdmittedToolEntry(
                canonical_name="write_file",
                aliases=["write-file"],
                mutation_class="writes_workspace",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("wf"),
                arg_field_names=["file_path", "content"],
                recovery_admission_tier=RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY,
            ),
            AdmittedToolEntry(
                canonical_name="bash",
                aliases=[],
                mutation_class="writes_workspace",
                determinism_class="nondeterministic_external_io",
                args_schema_digest=_sha256("bash"),
                arg_field_names=["command"],
                recovery_admission_tier=RecoveryAdmissionTier.RAW_SHELL_REFUSE,
            ),
        ],
    )


_MANIFEST = _make_manifest()


def test_canonical_read_only_produces_event(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c1",
            "raw_emission": {
                "name": "read_file",
                "arguments": {"file_path": "test.py"},
            },
            "source_kind": "curated_adversarial",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["selected_canonical_tool"] == "read_file"
    assert event["admission_decision"] == "auto_execute_read_only"
    assert event["payload_schema_valid"] is True
    assert event["recovered_mutation_auto_execution_violation"] is False


def test_mutation_produces_proposal_only(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c2",
            "raw_emission": {
                "name": "write_file",
                "arguments": {"file_path": "a.py", "content": "x"},
            },
            "source_kind": "curated_adversarial",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["admission_decision"] == "proposal_only_mutation"
    assert event["recovered_mutation_auto_execution_violation"] is False


def test_refusal_produces_event(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c3",
            "raw_emission": {"name": "unknown_tool", "arguments": {}},
            "source_kind": "curated_adversarial",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["refusal_code"] is not None
    assert event["admission_decision"] is None
    assert event["payload_schema_valid"] is False


def test_events_are_content_light(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c4",
            "raw_emission": {
                "name": "read_file",
                "arguments": {"file_path": "/secret/file"},
            },
            "source_kind": "curated_adversarial",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    event_data = json.dumps(events[0])
    assert "/secret" not in event_data
    for key in (
        "raw_emission",
        "raw_prompt",
        "raw_model_output",
        "file_content",
        "secret",
    ):
        assert key not in events[0], f"Forbidden raw-content key '{key}' found"
    assert "raw_emission_sha256" in events[0], "SHA256 hash field expected"


def test_wrapper_event(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c5",
            "raw_emission": {
                "function": {"name": "read_file", "arguments": {"file_path": "x.py"}}
            },
            "source_kind": "curated_adversarial",
            "expected_decision": "auto_execute_read_only",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["recovery_correct"] is True


def test_ambiguous_refuses_correctly(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": "c6",
            "raw_emission": {"name": "getstatus", "arguments": {}},
            "source_kind": "curated_adversarial",
            "expected_decision": "refuse_unsupported",
        }
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    assert events[0]["refusal_code"] is not None


def test_zero_mutation_auto_execution_violations(tmp_path: Path) -> None:
    cases = [
        {
            "case_id": f"m{i}",
            "raw_emission": {
                "name": "write_file",
                "arguments": {"file_path": "a.py", "content": "x"},
            },
            "source_kind": "curated_adversarial",
        }
        for i in range(5)
    ]
    events = evaluate_cases(_MANIFEST, cases, ledger_path=tmp_path / "events.jsonl")
    for event in events:
        assert event["recovered_mutation_auto_execution_violation"] is False

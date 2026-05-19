from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.adversarial]

from jsonschema import ValidationError, validate

from rig_relay.coordination.models import (
    _hash_file_paths,
    build_fake_green_test_detected_payload,
    build_proof_chain_incomplete_payload,
    build_seam_discovered_payload,
    reset_path_salt_for_testing,
    salted_path_hash,
)
from rig_relay.core.telemetry.constants import EventName

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

_SEAM_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.coordination.seam_event.v1.schema.json"
_PROOF_CHAIN_SCHEMA_PATH = (
    SCHEMAS_DIR / "rig.relay.coordination.proof_chain_event.v1.schema.json"
)
_FAKE_GREEN_SCHEMA_PATH = (
    SCHEMAS_DIR / "rig.relay.coordination.fake_green_event.v1.schema.json"
)


def _seam_schema() -> dict:
    return json.loads(_SEAM_SCHEMA_PATH.read_text(encoding="utf-8"))


def _proof_chain_schema() -> dict:
    return json.loads(_PROOF_CHAIN_SCHEMA_PATH.read_text(encoding="utf-8"))


def _fake_green_schema() -> dict:
    return json.loads(_FAKE_GREEN_SCHEMA_PATH.read_text(encoding="utf-8"))


_SAMPLE_PATHS = [
    "docs/schemas/rig.relay.mcp.capability_profile.v1.schema.json",
    "rig_relay/protocols/mcp/server.py",
    "tests/protocols/mcp/test_read_only_server.py",
]


def _sample_hashes() -> list[str]:
    return _hash_file_paths(_SAMPLE_PATHS)


# ── Schema validation ──────────────────────────────────────────────────────


def test_seam_event_schema_parses() -> None:
    assert _seam_schema() is not None


def test_proof_chain_event_schema_parses() -> None:
    assert _proof_chain_schema() is not None


def test_fake_green_event_schema_parses() -> None:
    assert _fake_green_schema() is not None


# ── All event kinds validate ────────────────────────────────────────────────


_EVENT_KINDS = [
    "contract_seam_discovered",
    "proof_chain_incomplete",
    "fake_green_test_detected",
    "schema_authority_missing",
    "schema_authority_disconnected",
    "producer_missing",
    "consumer_missing",
    "validator_theater_detected",
    "evidence_path_missing",
    "artifact_digest_missing",
    "stale_validation_run_detected",
    "release_blocker_unverifiable",
    "trace_context_missing",
    "telemetry_redaction_gap",
    "concurrency_authority_undefined",
    "mutation_authority_ambiguous",
    "contract_family_promoted",
    "contract_family_deferred",
]


@pytest.mark.parametrize("event_kind", _EVENT_KINDS)
def test_all_seam_event_kinds_validate(event_kind: str) -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=["trace_id", "span_id"],
        trace_fields_missing=["session_id"],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="Add CI evidence schemas and orchestrator.",
        detected_by="protocol_ci_sdk_assessment",
    )
    payload["event_kind"] = event_kind
    payload["event_id"] = "evt-test-" + event_kind
    validate(instance=payload, schema=_seam_schema())


# ── All seam_class values accepted ──────────────────────────────────────────


_SEAM_CLASSES = [
    "schema_authority_missing",
    "schema_authority_disconnected",
    "producer_missing",
    "consumer_missing",
    "validator_theater_detected",
    "evidence_path_missing",
    "artifact_digest_missing",
    "stale_validation_run_detected",
    "release_blocker_unverifiable",
    "trace_context_missing",
    "telemetry_redaction_gap",
    "concurrency_authority_undefined",
    "mutation_authority_ambiguous",
    "proof_chain_incomplete",
    "fake_green_test_detected",
]


@pytest.mark.parametrize("seam_class", _SEAM_CLASSES)
def test_all_seam_class_values_accepted(seam_class: str) -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class=seam_class,
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=["trace_id"],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    validate(instance=payload, schema=_seam_schema())


# ── Validation rejection ────────────────────────────────────────────────────


def test_missing_contract_family_id_rejected() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    del payload["contract_family_id"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_seam_schema())


def test_invalid_severity_rejected() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    payload["severity"] = "impossible"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_seam_schema())


def test_missing_affected_file_hashes_rejected() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    payload["affected_file_hashes"] = []
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_seam_schema())


# ── Content-light: no raw paths ─────────────────────────────────────────────


def test_seam_payload_contains_no_raw_paths() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    raw = json.dumps(payload)
    for path in _SAMPLE_PATHS:
        assert path not in raw, f"Raw path {path!r} found in seam payload"


def test_fake_green_payload_contains_no_raw_paths() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci_evidence_surface.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
        release_blocker_ids=["blk_ci_cd"],
        severity="critical",
    )
    raw = json.dumps(payload)
    assert "tests/ci/" not in raw


# ── Schema version resolution ───────────────────────────────────────────────


def test_seam_payload_schema_version_resolves_to_existing_schema() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_missing",
        severity="high",
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action="",
        detected_by="audit",
    )
    assert payload["schema_version"] == "rig.relay.coordination.seam_event.v1"
    assert _SEAM_SCHEMA_PATH.exists()


def test_proof_chain_payload_schema_version_resolves() -> None:
    reset_path_salt_for_testing()
    payload = build_proof_chain_incomplete_payload(
        surface_id="ci_cd",
        contract_family_id="ci_cd",
        proof_chain_status="partial",
        concrete_failure_mode="Missing CI evidence schemas.",
        recommended_next_action="Add CI schemas.",
    )
    assert payload["schema_version"] == "rig.relay.coordination.proof_chain_event.v1"
    assert _PROOF_CHAIN_SCHEMA_PATH.exists()


def test_fake_green_payload_schema_version_resolves() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_pass",
        fake_green_pattern="file_existence_only",
        why_theatrical="Only checks file existence.",
        what_would_still_pass_description="Empty file passes.",
        missing_adversarial_test_description="No schema validation check.",
    )
    assert payload["schema_version"] == "rig.relay.coordination.fake_green_event.v1"
    assert _FAKE_GREEN_SCHEMA_PATH.exists()


# ── EventName registration ───────────────────────────────────────────────────


def test_event_name_contains_coord_task_claim_refused() -> None:
    assert hasattr(EventName, "COORD_TASK_CLAIM_REFUSED")
    assert EventName.COORD_TASK_CLAIM_REFUSED == "coord.task.claim_refused"


def test_event_name_contains_release_bundle_built() -> None:
    assert hasattr(EventName, "RELEASE_BUNDLE_BUILT")
    assert EventName.RELEASE_BUNDLE_BUILT == "rig.relay.release.bundle_built"


def test_event_name_no_duplicate_values() -> None:
    values = [e.value for e in EventName]
    assert len(values) == len(set(values)), "Duplicate EventName values detected"

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

from jsonschema import ValidationError, validate

from rig_relay.coordination.models import (
    _hash_file_paths,
    build_fake_green_test_detected_payload,
    build_proof_chain_incomplete_payload,
    build_release_blocker_unverifiable_payload,
    build_seam_discovered_payload,
    reset_path_salt_for_testing,
    salted_path_hash,
)

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


def _sample_hashes(paths: list[str] | None = None) -> list[str]:
    if paths is None:
        paths = [
            "docs/schemas/rig.relay.mcp.capability_profile.v1.schema.json",
            "rig_relay/protocols/mcp/server.py",
            "tests/protocols/mcp/test_read_only_server.py",
        ]
    return _hash_file_paths(paths)


# ── Proof-chain event schema validation ────────────────────────────────────


def test_proof_chain_minimal_event_validates() -> None:
    reset_path_salt_for_testing()
    payload = build_proof_chain_incomplete_payload(
        surface_id="ci_cd",
        contract_family_id="ci_cd",
        proof_chain_status="partial",
        concrete_failure_mode="Missing CI evidence schemas.",
        recommended_next_action="Add CI schemas.",
    )
    validate(instance=payload, schema=_proof_chain_schema())


def test_proof_chain_with_all_hashes_validates() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_proof_chain_incomplete_payload(
        surface_id="ci_cd",
        contract_family_id="ci_cd",
        proof_chain_status="partial",
        authority_file_hashes=hashes,
        schema_file_hashes=hashes,
        producer_file_hashes=hashes,
        consumer_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        evidence_file_hashes=hashes,
        missing_schema_validation=True,
        missing_artifact_hash_validation=False,
        missing_trace_or_correlation_validation=True,
        missing_telemetry_or_redaction_validation=False,
        concrete_failure_mode="Missing CI evidence schemas.",
        recommended_next_action="Add CI schemas.",
    )
    validate(instance=payload, schema=_proof_chain_schema())


def test_proof_chain_rejects_impossible_status() -> None:
    reset_path_salt_for_testing()
    payload = build_proof_chain_incomplete_payload(
        surface_id="ci_cd",
        contract_family_id="ci_cd",
        proof_chain_status="partial",
        concrete_failure_mode="Test",
        recommended_next_action="Fix",
    )
    payload["proof_chain_status"] = "fantasy_status"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_proof_chain_schema())


def test_all_known_proof_chain_statuses_accepted() -> None:
    reset_path_salt_for_testing()
    for status in ("complete", "partial", "theatrical", "missing"):
        payload = build_proof_chain_incomplete_payload(
            surface_id="ci_cd",
            contract_family_id="ci_cd",
            proof_chain_status=status,
            concrete_failure_mode="Test",
            recommended_next_action="Fix",
        )
        validate(instance=payload, schema=_proof_chain_schema())


# ── Fake-green event schema validation ──────────────────────────────────────


def test_fake_green_minimal_event_validates() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
    )
    validate(instance=payload, schema=_fake_green_schema())


def test_fake_green_requires_test_function() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
    )
    del payload["test_function"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_fake_green_schema())


def test_fake_green_requires_why_theatrical() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
    )
    del payload["why_theatrical"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_fake_green_schema())


def test_fake_green_requires_missing_adversarial_test_description() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
    )
    del payload["missing_adversarial_test_description"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_fake_green_schema())


def test_fake_green_rejects_invalid_pattern() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="ci_cd",
        test_file_hash=salted_path_hash("tests/ci/test_ci.py"),
        test_function="test_ci_evidence_passes",
        fake_green_pattern="blocker_text_only_enforcement",
        why_theatrical="Test validates blocker text, not evidence artifact hash.",
        what_would_still_pass_description="A renamed file still passes.",
        missing_adversarial_test_description="Hash mismatch detection not tested.",
    )
    payload["fake_green_pattern"] = "imaginary_pattern"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_fake_green_schema())


# ── 14 audit seams normalisation ────────────────────────────────────────────

_AUDIT_SEAMS = [
    {
        "contract_family_id": "ci_cd",
        "seam_class": "schema_authority_disconnected",
        "severity": "critical",
        "affected": [".github/workflows/ci.yml", "scripts/rig_ci_orchestrator.py"],
    },
    {
        "contract_family_id": "sdk",
        "seam_class": "producer_missing",
        "severity": "critical",
        "affected": ["rig_relay/sdk/__init__.py", "rig_relay/sdk/_errors.py"],
    },
    {
        "contract_family_id": "a2a",
        "seam_class": "schema_authority_missing",
        "severity": "critical",
        "affected": ["rig_relay/protocols/a2a/server.py"],
    },
    {
        "contract_family_id": "mcp",
        "seam_class": "evidence_path_missing",
        "severity": "critical",
        "affected": [
            "rig_relay/protocols/mcp/server.py",
            "docs/schemas/rig.relay.mcp.capability_profile.v1.schema.json",
        ],
    },
    {
        "contract_family_id": "acp",
        "seam_class": "producer_missing",
        "severity": "high",
        "affected": [
            "rig_relay/acp/_disabled_tools.py",
            "rig_relay/acp/_session_lifecycle.py",
        ],
    },
    {
        "contract_family_id": "release_gate",
        "seam_class": "validator_theater_detected",
        "severity": "critical",
        "affected": [
            "scripts/rig_release_gate_validate.py",
            "tests/release_gate/test_release_gate.py",
        ],
    },
    {
        "contract_family_id": "release_gate",
        "seam_class": "proof_chain_incomplete",
        "severity": "high",
        "affected": ["scripts/rig_release_gate_validate.py"],
    },
    {
        "contract_family_id": "release_gate",
        "seam_class": "stale_validation_run_detected",
        "severity": "high",
        "affected": ["docs/json/release_gate/rc_readiness_gate.v1.json"],
    },
    {
        "contract_family_id": "telemetry",
        "seam_class": "telemetry_redaction_gap",
        "severity": "medium",
        "affected": [
            "rig_relay/core/telemetry/send.py",
            "docs/schemas/rig.relay.telemetry_settings.v1.schema.json",
        ],
    },
    {
        "contract_family_id": "coordination",
        "seam_class": "schema_authority_disconnected",
        "severity": "medium",
        "affected": [
            "rig_relay/coordination/models.py",
            "docs/schemas/rig.relay.coordination.event.v1.schema.json",
        ],
    },
    {
        "contract_family_id": "coordination",
        "seam_class": "artifact_digest_missing",
        "severity": "medium",
        "affected": ["rig_relay/coordination/store.py"],
    },
    {
        "contract_family_id": "local_api_envelope",
        "seam_class": "consumer_missing",
        "severity": "high",
        "affected": ["rig_relay/desktop/projection.py"],
    },
    {
        "contract_family_id": "fleet",
        "seam_class": "schema_authority_disconnected",
        "severity": "high",
        "affected": [
            "rig_relay/coordination/fleet_models.py",
            "docs/schemas/rig.fleet.coordination_event.v1.schema.json",
        ],
    },
    {
        "contract_family_id": "security",
        "seam_class": "schema_authority_disconnected",
        "severity": "high",
        "affected": ["docs/governance/security-threat-model.md"],
    },
]


@pytest.mark.parametrize(
    "seam", _AUDIT_SEAMS, ids=lambda s: f"{s['contract_family_id']}/{s['seam_class']}"
)
def test_audit_seam_normalizes_to_valid_seam_event(seam: dict) -> None:
    reset_path_salt_for_testing()
    hashes = _hash_file_paths(seam["affected"])
    payload = build_seam_discovered_payload(
        contract_family_id=seam["contract_family_id"],
        seam_class=seam["seam_class"],
        severity=seam["severity"],
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes[:1] if hashes else [],
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes[:1] if hashes else [],
        test_file_hashes=[],
        trace_fields_observed=[],
        trace_fields_missing=[],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action=f"Resolve {seam['seam_class']} for {seam['contract_family_id']}.",
        detected_by="audit_lane_protocol_ci_sdk",
    )
    validate(instance=payload, schema=_seam_schema())


# ── Payload builders validate against their declared schemas ────────────────


def test_build_seam_discovered_validates_against_schema() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_seam_discovered_payload(
        contract_family_id="ci_cd",
        seam_class="schema_authority_disconnected",
        severity="critical",
        proof_chain_status="missing",
        fake_green_risk="high",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=["trace_id"],
        trace_fields_missing=["span_id"],
        telemetry_redaction_implications="CI artifacts may contain raw paths.",
        concurrency_implications="No concurrent CI runs gated.",
        recommended_next_action="Add CI evidence schemas.",
        detected_by="audit",
    )
    validate(instance=payload, schema=_seam_schema())


def test_build_proof_chain_incomplete_validates_against_schema() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_proof_chain_incomplete_payload(
        surface_id="ci_cd",
        contract_family_id="ci_cd",
        proof_chain_status="theatrical",
        authority_file_hashes=hashes,
        schema_file_hashes=hashes,
        producer_file_hashes=[],
        consumer_file_hashes=[],
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        evidence_file_hashes=[],
        missing_schema_validation=True,
        missing_artifact_hash_validation=True,
        missing_trace_or_correlation_validation=True,
        missing_telemetry_or_redaction_validation=True,
        concrete_failure_mode="Validator checks text, not evidence hashes.",
        recommended_next_action="Add hash validation to gate validator.",
    )
    validate(instance=payload, schema=_proof_chain_schema())


def test_build_fake_green_validates_against_schema() -> None:
    reset_path_salt_for_testing()
    payload = build_fake_green_test_detected_payload(
        contract_family_id="release_gate",
        test_file_hash=salted_path_hash("tests/release_gate/test_release_gate.py"),
        test_function="test_all_blockers_have_tests",
        fake_green_pattern="field_presence_only",
        why_theatrical="Test checks that test files exist, not that they test evidence hashes.",
        what_would_still_pass_description="Stub test files that assert True pass.",
        missing_adversarial_test_description="Hash mismatch detection, schema-not-loaded tests missing.",
        release_blocker_ids=["blk_ci_cd_structured_evidence_surface"],
        severity="critical",
    )
    validate(instance=payload, schema=_fake_green_schema())


def test_build_release_blocker_unverifiable_validates_against_schema() -> None:
    reset_path_salt_for_testing()
    hashes = _sample_hashes()
    payload = build_release_blocker_unverifiable_payload(
        contract_family_id="ci_cd",
        blocker_id="blk_ci_cd_structured_evidence_surface",
        seam_class="schema_authority_disconnected",
        severity="critical",
        proof_chain_status="missing",
        fake_green_risk="high",
        affected_file_hashes=hashes,
        evidence_file_hashes=hashes,
        schema_file_hashes=hashes,
        implementation_file_hashes=hashes,
        validator_file_hashes=hashes,
        test_file_hashes=hashes,
        trace_fields_observed=[],
        trace_fields_missing=["build_id", "job_id"],
        telemetry_redaction_implications="CI verdict includes file hashes.",
        concurrency_implications="",
        recommended_next_action="Implement CI evidence schemas and orchestrator.",
        detected_by="audit",
    )
    validate(instance=payload, schema=_seam_schema())

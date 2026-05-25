from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from rig_relay.cli._steward._capsule import (
    append_observation_event,
    compile_handoff_packet,
)
from rig_relay.cli._steward._classification import (
    build_validation_plan,
    check_write_permission,
    classify_paths,
    explain_artifact,
)

pytestmark = [pytest.mark.integration]


# ── contract / real-artifact: profile schema validation ─────────────────


def test_contract_real_artifact_profile_validation() -> None:
    import jsonschema

    root = Path(__file__).resolve().parent.parent.parent
    schema_path = root / "docs/schemas/rig.relay.steward_profile.v1.schema.json"
    profile_path = root / "docs/json/governance/steward_profile.v1.json"

    assert schema_path.exists()
    assert profile_path.exists()

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=profile, schema=schema)


# ── contract / integration: explain artifact matching ───────────────────


def test_contract_integration_explain_resolves_mapping(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent.parent

    res = explain_artifact(
        root, "docs/schemas/rig.relay.steward_profile.v1.schema.json"
    )
    assert res["family_name"] == "Schema Files"
    assert res["class"] == "schema"

    res2 = explain_artifact(root, "docs/json/governance/steward_profile.v1.json")
    assert res2["family_name"] == "Canonical Governance/Issue JSON"
    assert res2["class"] == "canonical"

    res3 = explain_artifact(root, ".build/rig-relay/coordination/leases.jsonl")
    assert res3["family_name"] == "Coordination Ledgers"
    assert res3["class"] == "receipt"
    assert res3["protected_write_disposition"] == "require_approval"

    res4 = explain_artifact(root, "docs/collections/governance.html")
    assert res4["family_name"] == "Static Generated Projections"
    assert res4["class"] == "projection"


# ── integration / real-artifact: git diff and surface classification ───


def test_integration_real_artifact_impact_analysis(tmp_path: Path) -> None:
    # Set up real temporary git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    # Create dirty files across surfaces
    (tmp_path / "rig_relay/core/telemetry/send.py").parent.mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / "rig_relay/core/telemetry/send.py").write_text(
        "import os", encoding="utf-8"
    )

    (tmp_path / "docs/schemas").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/schemas/test.schema.json").write_text("{}", encoding="utf-8")

    (tmp_path / "tests/test_hello.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests/test_hello.py").write_text("def test(): pass", encoding="utf-8")

    (tmp_path / "random_doc.md").write_text("docs", encoding="utf-8")

    dirty_files = [
        "rig_relay/core/telemetry/send.py",
        "docs/schemas/test.schema.json",
        "tests/test_hello.py",
        "random_doc.md",
    ]

    classified = classify_paths(tmp_path, dirty_files)

    assert "rig_relay/core/telemetry/send.py" in classified["telemetry"]
    assert "docs/schemas/test.schema.json" in classified["schemas"]
    assert "tests/test_hello.py" in classified["tests"]
    assert "random_doc.md" in classified["unknown_unclassified"]


# ── integration / real-artifact: validation plan derivation ─────────────


def test_integration_real_artifact_validation_plan(tmp_path: Path) -> None:
    # Use real project root
    root = Path(__file__).resolve().parent.parent.parent

    changed = [
        "rig_relay/core/telemetry/send.py",
        "rig_relay/cli/steward.py",
        "docs/schemas/rig.relay.steward_profile.v1.schema.json",
        "README.md",
    ]

    plan = build_validation_plan(root, changed)

    # Telemetry changes must map to pytest tests/telemetry/
    telemetry_recs = [
        r
        for r in plan["recommended_targeted_validation"]
        if "tests/telemetry" in r["command"]
    ]
    assert len(telemetry_recs) > 0
    assert "telemetry" in telemetry_recs[0]["classification"]

    # Steward changes must map to test_opencode_idle_steward.py
    steward_recs = [
        r
        for r in plan["recommended_targeted_validation"]
        if "test_opencode_idle_steward.py" in r["command"]
    ]
    assert len(steward_recs) > 0

    # Schema changes must map to validate_schemas script
    schema_recs = [
        r
        for r in plan["recommended_targeted_validation"]
        if "validate_schemas.py" in r["command"]
    ]
    assert len(schema_recs) > 0

    # Markdown documentation changes must be listed as skipped
    skipped_md = [
        s for s in plan["intentionally_skipped_validation"] if s["path"] == "README.md"
    ]
    assert len(skipped_md) > 0
    assert "documentation" in skipped_md[0]["reason"].lower()


# ── adversarial / sabotage: check-write permissions ─────────────────────


def test_adversarial_sabotage_check_write_boundaries(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent.parent

    # denypath: secrets
    res_secrets = check_write_permission(root, "secrets.env")
    assert res_secrets["allowed"] is False
    assert res_secrets["action"] == "deny"

    # denypath: traversal outside root
    res_traversal = check_write_permission(root, "docs/../../.env")
    assert res_traversal["allowed"] is False
    assert res_traversal["action"] == "deny"

    # absolute path outside root
    res_abs = check_write_permission(root, "/etc/passwd")
    assert res_abs["allowed"] is False
    assert res_abs["action"] == "deny"

    # advise path: schema
    res_schema = check_write_permission(
        root, "docs/schemas/rig.relay.steward_profile.v1.schema.json"
    )
    assert res_schema["allowed"] is True
    assert res_schema["action"] == "advise"

    # require_approval path: coordination ledger
    res_ledger = check_write_permission(
        root, ".build/rig-relay/coordination/leases.jsonl"
    )
    assert res_ledger["allowed"] is True
    assert res_ledger["action"] == "require_approval"

    # allow path: generic file
    res_generic = check_write_permission(root, "rig_relay/cli/steward.py")
    assert res_generic["allowed"] is True
    assert res_generic["action"] == "allow"


# ── integration / real-artifact: session-scoped observations & handoff ──


def test_integration_real_artifact_handoff_honest_records(tmp_path: Path) -> None:
    # 1. Test distinct session ID isolation
    sess1 = "session-alpha"
    sess2 = "session-beta"

    append_observation_event(
        tmp_path, sess1, "tool_call", {"tool": "write_file", "path": "src/foo.py"}
    )
    append_observation_event(
        tmp_path, sess2, "tool_call", {"tool": "read_file", "path": "src/bar.py"}
    )

    p1 = (
        tmp_path
        / f".build/rig-relay/derived/opencode-steward/sessions/{sess1}/observations.v1.jsonl"
    )
    p2 = (
        tmp_path
        / f".build/rig-relay/derived/opencode-steward/sessions/{sess2}/observations.v1.jsonl"
    )

    assert p1.exists()
    assert p2.exists()

    # Verify content in sess1
    lines1 = p1.read_text(encoding="utf-8").splitlines()
    assert len(lines1) == 1
    assert "session-alpha" in lines1[0]
    assert "write_file" in lines1[0]

    # Verify content in sess2
    lines2 = p2.read_text(encoding="utf-8").splitlines()
    assert len(lines2) == 1
    assert "session-beta" in lines2[0]
    assert "read_file" in lines2[0]

    # 2. Test multiple queued events retain append order
    append_observation_event(
        tmp_path,
        sess1,
        "warning_raised",
        {"path": "docs/schemas/s.json", "reason": "edit schema"},
    )
    append_observation_event(
        tmp_path, sess1, "validation_run", {"command": "pytest", "outcome": "pass"}
    )

    lines_ordered = p1.read_text(encoding="utf-8").splitlines()
    assert len(lines_ordered) == 3
    assert json.loads(lines_ordered[0])["event_type"] == "tool_call"
    assert json.loads(lines_ordered[1])["event_type"] == "warning_raised"
    assert json.loads(lines_ordered[2])["event_type"] == "validation_run"

    # 3. Test compile_handoff_packet consumes only the session's flushed events
    handoff = compile_handoff_packet(tmp_path, sess1)

    assert handoff["session_id"] == sess1
    assert handoff["non_authoritative_steward_observation_packet"] is True
    assert len(handoff["tool_calls_observed"]) == 1
    assert handoff["tool_calls_observed"][0]["tool"] == "write_file"
    assert len(handoff["warnings_raised_and_ignored"]) == 1
    assert handoff["warnings_raised_and_ignored"][0]["reason"] == "edit schema"
    assert len(handoff["validations_observed"]) == 1
    assert handoff["validations_observed"][0]["command"] == "pytest"


# ── integration / real-artifact: strict session isolation ──────────────────


def test_integration_real_artifact_no_fabricated_default_session(
    tmp_path: Path,
) -> None:
    # Appending observations with empty/None session ID must raise ValueError
    with pytest.raises(ValueError, match="Session identifier is required"):
        append_observation_event(tmp_path, "", "tool_call", {"tool": "write_file"})

    with pytest.raises(ValueError, match="Session identifier is required"):
        compile_handoff_packet(tmp_path, "")


# ── contract / real-artifact: content-light event contract ──────────────────


def test_contract_real_artifact_content_light_event_contract(tmp_path: Path) -> None:
    sess = "session-gamma"
    forbidden_terms = [
        "prompt",
        "reasoning",
        "file_contents",
        "secret",
        "env",
        "command",
    ]

    append_observation_event(
        tmp_path, sess, "tool_call", {"tool": "write_file", "path": "src/foo.py"}
    )

    obs_file = (
        tmp_path
        / f".build/rig-relay/derived/opencode-steward/sessions/{sess}/observations.v1.jsonl"
    )
    assert obs_file.exists()

    lines = obs_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])

    # Assert allowed metadata
    assert "schema_version" in evt
    assert "session_id" in evt
    assert "event_type" in evt
    assert "generated_at" in evt

    # Assert no forbidden fields exist in the observation event
    for term in forbidden_terms:
        assert term not in evt["payload"]
        assert term not in evt

    handoff = compile_handoff_packet(tmp_path, sess)
    assert handoff["non_authoritative_steward_observation_packet"] is True
    assert "disclaimer" in handoff

    for term in forbidden_terms:
        assert term not in handoff


# ── substrate / integration: TypeScript plugin static contract test ─────────


def test_substrate_integration_typescript_plugin_hook_contract() -> None:
    root = Path(__file__).resolve().parent.parent.parent
    plugin_path = root / ".opencode/plugins/rig-roadmap-steward.ts"

    assert not plugin_path.exists(), f"Plugin file still present at: {plugin_path}"
    assert not any(root.glob(".opencode/plugins/*.ts"))


# ── contract / real-artifact: profile validation failure ────────────────
def test_contract_real_artifact_profile_validation_failure() -> None:
    import jsonschema

    root = Path(__file__).resolve().parent.parent.parent
    schema_path = root / "docs/schemas/rig.relay.steward_profile.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Missing profile_identifier (required field)
    invalid_profile_1 = {
        "schema_version": "rig.relay.steward_profile.v1",
        "content_light": True,
        "artifact_families": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_profile_1, schema=schema)

    # Invalid disposition enum value
    invalid_profile_2 = {
        "schema_version": "rig.relay.steward_profile.v1",
        "profile_identifier": "invalid-profile",
        "content_light": True,
        "artifact_families": [
            {
                "name": "Bad Family",
                "patterns": ["*.py"],
                "class": "unknown",
                "mutation_path": "none",
                "content_light": True,
                "validation_command": "none",
                "related_artifacts": [],
                "risk": "none",
                "protected_write_disposition": "invalid_disposition",
            }
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_profile_2, schema=schema)


# ── integration / real-artifact: handoff with incomplete flag ───────────
def test_integration_real_artifact_handoff_with_incomplete_flag(tmp_path: Path) -> None:
    sess = "session-incomplete-test"
    session_dir = (
        tmp_path / f".build/rig-relay/derived/opencode-steward/sessions/{sess}"
    )
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "evidence_incomplete.flag").write_text("true", encoding="utf-8")

    handoff = compile_handoff_packet(tmp_path, sess)
    assert handoff["session_id"] == sess
    assert handoff["evidence_incomplete"] is True

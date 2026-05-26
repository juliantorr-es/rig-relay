"""Test constraint compiler — deterministic, safe-subset, no silent dropping."""

from __future__ import annotations

import json

from rig_relay.recovery.constraint_compiler import (
    _SUPPORTED_SAFE_SCHEMA_FEATURES,
    _UNSUPPORTED_SCHEMA_FEATURES,
    compile_constraints,
)
from rig_relay.recovery.models import (
    AdmittedToolEntry,
    CanonicalToolSurfaceManifest,
    RecoveryAdmissionTier,
)


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _make_manifest() -> CanonicalToolSurfaceManifest:
    return CanonicalToolSurfaceManifest(
        manifest_id="comp-test",
        generated_at="2026-01-01T00:00:00Z",
        manifest_digest=_sha256("comp-manifest"),
        admitted_tools=[
            AdmittedToolEntry(
                canonical_name="read_file",
                aliases=[],
                mutation_class="read_only",
                determinism_class="deterministic_repo_state",
                args_schema_digest=_sha256("rf"),
                arg_field_names=["file_path", "offset", "limit"],
                recovery_admission_tier=RecoveryAdmissionTier.READ_ONLY_RECOVERABLE,
            ),
            AdmittedToolEntry(
                canonical_name="write_file",
                aliases=[],
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


def test_compilation_is_deterministic() -> None:
    r1 = compile_constraints(_MANIFEST, "json_schema_safe", compilation_id="stable-id")
    r2 = compile_constraints(_MANIFEST, "json_schema_safe", compilation_id="stable-id")
    assert r1.constraint_artifact_digest == r2.constraint_artifact_digest
    assert r1.tools_total == r2.tools_total


def test_compilation_preserves_supported_features() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    features_seen = {
        f.feature for f in receipt.feature_statuses if f.status == "preserved"
    }
    assert features_seen >= _SUPPORTED_SAFE_SCHEMA_FEATURES


def test_no_unsupported_features_preserved() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    preserved = {f.feature for f in receipt.feature_statuses if f.status == "preserved"}
    unsupported_preserved = preserved & _UNSUPPORTED_SCHEMA_FEATURES
    assert not unsupported_preserved, (
        f"Unsupported features preserved: {unsupported_preserved}"
    )


def test_compilation_counts_tools() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    assert receipt.tools_total == 3
    assert receipt.tools_fully_representable >= 0


def test_mutation_tools_counted_as_proposal_only() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    assert receipt.tools_proposal_only >= 1


def test_artifact_digest_present() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    assert receipt.constraint_artifact_digest.startswith("sha256:")


def test_receipt_digest_present() -> None:
    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    assert receipt.receipt_digest.startswith("sha256:")


def test_schema_valid() -> None:
    from pathlib import Path

    from jsonschema import validate as jsonschema_validate

    receipt = compile_constraints(_MANIFEST, "json_schema_safe")
    receipt_json = json.loads(receipt.model_dump_json())
    schema_path = (
        Path(__file__).parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.tool_constraint_compilation_receipt.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    jsonschema_validate(instance=receipt_json, schema=schema)

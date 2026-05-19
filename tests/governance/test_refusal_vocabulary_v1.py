from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact, pytest.mark.adversarial]

from jsonschema import validate

_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "json"
    / "governance"
    / "refusal_vocabulary_v1.v1.json"
)
_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.refusal_vocabulary.v1.schema.json"
)

_REQUIRED_SHARED_CLASSES = {
    "unknown_capability",
    "invalid_schema",
    "malformed_request",
    "missing_trace",
    "duplicate_or_replay",
    "oversized_payload",
    "unsafe_payload",
    "raw_secret",
    "raw_path",
    "auth_required",
    "credential_material_refused",
    "permission_missing",
    "scope_missing",
    "repository_or_resource_missing",
    "repository_or_resource_denied",
    "mutation_refused",
    "destructive_refused",
    "credentialed_mutation_refused",
    "external_network_refused",
    "live_auth_deferred",
    "live_transport_deferred",
    "not_implemented_deferred",
    "rate_limited",
    "resource_budget_exceeded",
    "internal_error",
    "validation_failed",
    "candidate_rejected",
    "ci_hold",
    "ci_fail",
}

_BRIDGE_REFUSAL_KINDS = [
    "unknown_intent_kind",
    "invalid_schema_version",
    "unknown_kind",
    "missing_trace_id",
    "duplicate_message_id",
    "oversized_payload",
    "mutation_without_capability",
    "missing_capability",
    "mutation_class_refused",
    "credentialed_provider_mutation_refused",
    "release_affecting_mutation_refused",
    "external_network_mutation_refused",
    "unsafe_payload_refused",
    "raw_secret_refused",
    "raw_path_refused",
    "auth_required_not_satisfied",
    "capability_gate_refused",
    "rate_limited",
    "server_full",
    "malformed_envelope",
    "redaction_violation",
    "internal_error",
]

_ALL_SURFACES = [
    "bridge",
    "sdk",
    "mcp",
    "acp",
    "a2a",
    "github_provider",
    "google_workspace",
    "ci_evidence",
    "tools_bash_runtime",
    "compiler",
]


def _artifact() -> dict:
    return json.loads(_ARTIFACT_PATH.read_text(encoding="utf-8"))


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Schema validation ─────────────────────────────────────────────────


def test_schema_parses_as_json() -> None:
    assert _schema() is not None


def test_artifact_parses_as_json() -> None:
    assert _artifact() is not None


def test_artifact_validates_against_schema() -> None:
    validate(instance=_artifact(), schema=_schema())


# ── Shared refusal classes ─────────────────────────────────────────────


def test_exactly_29_shared_refusal_classes_present() -> None:
    classes = _artifact()["shared_refusal_classes"]
    assert len(classes) == 29, f"Expected 29 shared refusal classes, got {len(classes)}"


def test_all_29_required_classes_present() -> None:
    class_ids = {c["class_id"] for c in _artifact()["shared_refusal_classes"]}
    missing = _REQUIRED_SHARED_CLASSES - class_ids
    assert not missing, f"Missing required shared classes: {missing}"


def test_no_duplicate_class_ids() -> None:
    class_ids = [c["class_id"] for c in _artifact()["shared_refusal_classes"]]
    assert len(class_ids) == len(set(class_ids)), (
        f"Duplicate class_ids found: {[cid for cid in class_ids if class_ids.count(cid) > 1]}"
    )


def test_every_shared_class_has_label() -> None:
    for cls_item in _artifact()["shared_refusal_classes"]:
        assert len(cls_item["class_label"]) > 0, (
            f"Class {cls_item['class_id']} has empty class_label"
        )


def test_every_shared_class_has_category() -> None:
    valid_categories = {
        "input_validation",
        "capability",
        "authorization",
        "resource",
        "mutation",
        "network",
        "deferral",
        "rate_limit",
        "error",
        "validation",
        "ci",
    }
    for cls_item in _artifact()["shared_refusal_classes"]:
        assert cls_item["category"] in valid_categories, (
            f"Class {cls_item['class_id']} has invalid category: {cls_item['category']}"
        )


def test_every_shared_class_has_severity_range() -> None:
    valid_severities = {"info", "low", "medium", "high", "critical"}
    for cls_item in _artifact()["shared_refusal_classes"]:
        assert cls_item["severity_range"] in valid_severities, (
            f"Class {cls_item['class_id']} has invalid severity_range: {cls_item['severity_range']}"
        )


def test_every_shared_class_has_canonical_refusal_code() -> None:
    for cls_item in _artifact()["shared_refusal_classes"]:
        assert len(cls_item["canonical_refusal_code"]) > 0, (
            f"Class {cls_item['class_id']} has empty canonical_refusal_code"
        )


# ── Surface coverage ───────────────────────────────────────────────────


def test_all_9_surfaces_have_at_least_one_mapping() -> None:
    mapped_surfaces = {m["surface"] for m in _artifact()["surface_mappings"]}
    for surface in _ALL_SURFACES:
        assert surface in mapped_surfaces, (
            f"Surface '{surface}' has no entries in surface_mappings"
        )


# ── Bridge refusal kind coverage ───────────────────────────────────────


@pytest.mark.parametrize("refusal_kind", _BRIDGE_REFUSAL_KINDS)
def test_bridge_refusal_kind_mapped(refusal_kind: str) -> None:
    bridge_mappings = [
        m
        for m in _artifact()["surface_mappings"]
        if m["surface"] == "bridge" and m["original_code"] == refusal_kind
    ]
    assert len(bridge_mappings) >= 1, (
        f"Bridge refusal_kind '{refusal_kind}' has no mapping entry"
    )


def test_bridge_has_exactly_22_refusal_kind_mappings() -> None:
    bridge_mappings = [
        m
        for m in _artifact()["surface_mappings"]
        if m["surface"] == "bridge" and m["original_kind"] == "refusal_kind"
    ]
    assert len(bridge_mappings) == 22, (
        f"Expected 22 bridge refusal_kind mappings, got {len(bridge_mappings)}"
    )


# ── Shared class coverage ──────────────────────────────────────────────


def test_every_shared_class_has_at_least_one_surface_mapped() -> None:
    class_ids = {c["class_id"] for c in _artifact()["shared_refusal_classes"]}
    mapped_classes = {m["shared_class"] for m in _artifact()["surface_mappings"]}
    unmapped = class_ids - mapped_classes
    assert not unmapped, f"Shared classes with no surface mappings: {unmapped}"


# ── Rationale enforcement ──────────────────────────────────────────────


def test_every_surface_mapping_has_rationale() -> None:
    for mapping in _artifact()["surface_mappings"]:
        assert len(mapping["rationale"]) > 0, (
            f"Mapping for {mapping['surface']}:{mapping['original_code']} has empty rationale"
        )


def test_every_surface_mapping_rationale_is_non_trivial() -> None:
    for mapping in _artifact()["surface_mappings"]:
        assert len(mapping["rationale"]) >= 20, (
            f"Mapping for {mapping['surface']}:{mapping['original_code']} has rationale shorter than 20 chars: '{mapping['rationale']}'"
        )


# ── Content-light enforcement ──────────────────────────────────────────


def test_artifact_no_forbidden_token_patterns() -> None:
    raw = json.dumps(_artifact())
    forbidden = [
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "sk-",
        "api_key",
        "client_secret",
        "private_key",
        "access_token",
    ]
    for fb in forbidden:
        assert fb not in raw, f"Forbidden token pattern '{fb}' found in artifact"


def test_artifact_no_forbidden_field_names() -> None:
    raw = json.dumps(_artifact())
    forbidden = [
        '"raw_prompt"',
        '"raw_completion"',
        '"raw_file_contents"',
        '"access_token"',
        '"client_secret"',
        '"private_key"',
    ]
    for fb in forbidden:
        assert fb not in raw, f"Forbidden field name {fb} found in artifact"


def test_artifact_has_redaction_status_content_light() -> None:
    assert _artifact()["redaction_status"] == "content_light"


# ── Structural integrity ───────────────────────────────────────────────


def test_artifact_has_artifact_id() -> None:
    assert len(_artifact()["artifact_id"]) > 0


def test_artifact_has_generated_at() -> None:
    assert len(_artifact()["generated_at"]) > 0


def test_artifact_has_schema_version() -> None:
    assert _artifact()["schema_version"] == "rig.relay.refusal_vocabulary.v1"


def test_unmapped_known_codes_have_valid_structure() -> None:
    for entry in _artifact()["unmapped_known_codes"]:
        assert len(entry["surface"]) > 0
        assert len(entry["code"]) > 0
        assert len(entry["why_unmapped"]) >= 20, (
            f"Unmapped code {entry['surface']}:{entry['code']} has trivial why_unmapped"
        )


def test_strict_mode_behavior_has_required_fields() -> None:
    smb = _artifact()["strict_mode_behavior"]
    assert "unknown_codes_fail_validation" in smb
    assert "missing_rationale_fails_validation" in smb
    assert isinstance(smb["unknown_codes_fail_validation"], bool)
    assert isinstance(smb["missing_rationale_fails_validation"], bool)


def test_claim_boundaries_have_entries() -> None:
    assert len(_artifact()["claim_boundaries"]) >= 4


# ── No Markdown report created ─────────────────────────────────────────


def test_no_markdown_report_created() -> None:
    md_paths = list(
        Path(__file__)
        .resolve()
        .parent.parent.parent.glob("docs/json/governance/refusal_vocabulary*.md")
    )
    assert len(md_paths) == 0, (
        "Markdown report found — JSON is the canonical evidence container"
    )


# ── Every surface mapping references a valid shared class ──────────────


def test_every_mapping_refers_to_known_shared_class() -> None:
    class_ids = {c["class_id"] for c in _artifact()["shared_refusal_classes"]}
    for mapping in _artifact()["surface_mappings"]:
        assert mapping["shared_class"] in class_ids, (
            f"Mapping for {mapping['surface']}:{mapping['original_code']} "
            f"references unknown shared_class '{mapping['shared_class']}'"
        )

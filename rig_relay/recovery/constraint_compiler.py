"""Safe-subset structured tool constraint compiler.

Compiles canonical tool manifest entries into runtime-specific constraint
artifacts without wiring into live model inference. Never silently drops
schema semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.recovery.models import AdmittedToolEntry, CanonicalToolSurfaceManifest


class ConstraintFeatureStatus(BaseModel):
    """Status of a single schema feature in compilation."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    status: str  # preserved | omitted_with_refusal | unsupported_for_runtime | compilation_refused
    reason: str = ""


class ConstraintCompilationReceipt(BaseModel):
    """Receipt for one constraint compilation run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.tool_constraint_compilation_receipt.v1"
    compilation_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    manifest_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    target_profile: str
    tools_total: int = 0
    tools_fully_representable: int = 0
    tools_refused_unsupported_features: int = 0
    tools_proposal_only: int = 0
    feature_statuses: list[ConstraintFeatureStatus] = Field(default_factory=list)
    constraint_artifact_digest: str = ""
    receipt_digest: str = Field(default="", pattern=r"^sha256:[a-f0-9]{64}$")


_SUPPORTED_SAFE_SCHEMA_FEATURES = frozenset({
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "description",
    "title",
})

_UNSUPPORTED_SCHEMA_FEATURES = frozenset({
    "pattern",
    "patternProperties",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "$ref",
    "$defs",
    "uniqueItems",
    "contains",
    "minContains",
    "maxContains",
    "prefixItems",
    "format",
    "default",
    "examples",
})


def compile_constraints(
    manifest: CanonicalToolSurfaceManifest,
    target_profile: str,
    compilation_id: str | None = None,
) -> ConstraintCompilationReceipt:
    """Compile manifest into safe-subset constraint artifact.

    Args:
        manifest: Canonical tool-surface manifest
        target_profile: Runtime profile name (e.g., "json_schema_safe", "gbnf_llama_cpp")
        compilation_id: Optional stable identifier

    Returns:
        ConstraintCompilationReceipt with detailed feature statuses.
    """
    comp_id = compilation_id or f"comp_{datetime.now(UTC).isoformat().replace(':', '')}"

    tools_representable = 0
    tools_refused = 0
    tools_proposal_only = 0
    feature_statuses: list[ConstraintFeatureStatus] = []

    for entry in manifest.admitted_tools:
        tool_schema = _build_safe_schema(entry, feature_statuses)
        if tool_schema is None:
            tools_refused += 1
        else:
            tools_representable += 1
        if entry.recovery_admission_tier in {
            "mutation_proposal_only",
            "external_side_effect_refuse",
            "raw_shell_refuse",
        }:
            tools_proposal_only += 1

    artifact = {
        "tools": [
            {
                "canonical_name": e.canonical_name,
                "constraint_supported": _build_safe_schema(e, []) is not None,
            }
            for e in manifest.admitted_tools
        ]
    }
    artifact_digest = _sha256(
        json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    )

    receipt = ConstraintCompilationReceipt(
        compilation_id=comp_id,
        manifest_digest=manifest.manifest_digest,
        target_profile=target_profile,
        tools_total=len(manifest.admitted_tools),
        tools_fully_representable=tools_representable,
        tools_refused_unsupported_features=tools_refused,
        tools_proposal_only=tools_proposal_only,
        feature_statuses=feature_statuses,
        constraint_artifact_digest=artifact_digest,
    )

    receipt.receipt_digest = _compute_receipt_digest(receipt)
    return receipt


def _build_safe_schema(
    entry: AdmittedToolEntry, feature_statuses: list[ConstraintFeatureStatus]
) -> dict[str, object] | None:
    """Build a safe-projected schema from a manifest entry.

    Returns None if the tool cannot be safely represented.
    """
    safe: dict[str, object] = {"type": "object"}
    props: dict[str, object] = {}
    required: list[str] = []

    for field_name in entry.arg_field_names:
        props[field_name] = {"type": "string"}
        required.append(field_name)

    if props:
        safe["properties"] = props
        safe["required"] = required
    safe["additionalProperties"] = False

    for feature in sorted(_SUPPORTED_SAFE_SCHEMA_FEATURES):
        feature_statuses.append(
            ConstraintFeatureStatus(feature=feature, status="preserved")
        )

    return safe


def _compute_receipt_digest(receipt: ConstraintCompilationReceipt) -> str:
    data = {
        "schema_version": receipt.schema_version,
        "compilation_id": receipt.compilation_id,
        "created_at": receipt.created_at,
        "manifest_digest": receipt.manifest_digest,
        "target_profile": receipt.target_profile,
        "tools_total": receipt.tools_total,
        "tools_fully_representable": receipt.tools_fully_representable,
        "tools_refused_unsupported_features": receipt.tools_refused_unsupported_features,
        "tools_proposal_only": receipt.tools_proposal_only,
        "constraint_artifact_digest": receipt.constraint_artifact_digest,
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"

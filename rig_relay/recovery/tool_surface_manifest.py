"""Canonical tool-surface manifest derived from the real ToolManager.

Constructs a content-light AdmittedToolEntry list from the actual
built-in tool registry. Sorted deterministically by canonical name.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.recovery.alias_policy import (
    _ALIAS_MAP,
    check_alias_shadows_canonical,
    validate_alias_registry,
)
from rig_relay.recovery.models import (
    AdmittedToolEntry,
    CanonicalToolSurfaceManifest,
    RecoveryAdmissionTier,
    RecoveryRefusal,
    utcnow_iso,
)

if TYPE_CHECKING:
    from rig_relay.core.tools.base import BaseTool


def build_tool_surface_manifest(
    available_tools: dict[str, type[BaseTool]],
) -> CanonicalToolSurfaceManifest | RecoveryRefusal:
    """Build a canonical manifest from the real tool registry.

    Args:
        available_tools: dict of canonical_name → tool_class from ToolManager

    Returns:
        CanonicalToolSurfaceManifest or RecoveryRefusal if the alias
        registry is inconsistent with the tool set.
    """
    admitted_names = set(available_tools.keys())

    alias_refusal = validate_alias_registry(admitted_names)
    if alias_refusal is not None:
        return alias_refusal

    shadow = check_alias_shadows_canonical(admitted_names)
    if shadow is not None:
        from rig_relay.recovery.models import RecoveryRefusalCode as RC

        return RecoveryRefusal(
            refusal_code=RC.AMBIGUOUS_ALIAS,
            reason=f"Alias '{shadow}' shadows a different canonical tool name",
            candidate_count=0,
            manifest_digest="sha256:" + "0" * 64,
            original_emission_hash="sha256:" + "0" * 64,
        )

    entries: list[AdmittedToolEntry] = []
    for canonical_name in sorted(admitted_names):
        tool_cls = available_tools[canonical_name]
        entries.append(_build_entry(canonical_name, tool_cls))

    serialized = _serialize_entries(entries)
    manifest_digest = _sha256(serialized)

    return CanonicalToolSurfaceManifest(
        manifest_id=f"manifest_{utcnow_iso().replace(':', '').replace('-', '').replace('T', '_')[:20]}",
        generated_at=utcnow_iso(),
        admitted_tools=entries,
        manifest_digest=manifest_digest,
    )


def _build_entry(canonical_name: str, tool_cls: type[BaseTool]) -> AdmittedToolEntry:
    """Build a single AdmittedToolEntry from a tool class."""
    mutation_class = str(tool_cls.mutation_class)
    aliases = _gather_aliases(canonical_name)
    args_schema = tool_cls.get_parameters()
    args_schema_digest = _sha256(json.dumps(args_schema, sort_keys=True))
    arg_field_names = sorted(args_schema.get("properties", {}).keys())
    admission_tier = _classify_admission_tier(mutation_class, canonical_name)

    return AdmittedToolEntry(
        canonical_name=canonical_name,
        aliases=sorted(set(aliases)),
        mutation_class=mutation_class,
        determinism_class=str(tool_cls.determinism_class),
        args_schema_digest=args_schema_digest,
        arg_field_names=arg_field_names,
        recovery_admission_tier=admission_tier,
    )


def _gather_aliases(canonical_name: str) -> list[str]:
    """Gather all alias map entries that point to this canonical name."""
    return [a for a, c in _ALIAS_MAP.items() if c == canonical_name]


def _classify_admission_tier(
    mutation_class: str, canonical_name: str
) -> RecoveryAdmissionTier:
    """Classify a tool into a recovery admission tier."""
    mc = mutation_class.lower()

    if canonical_name in {"bash"}:
        return RecoveryAdmissionTier.RAW_SHELL_REFUSE

    if canonical_name in {"validate", "validation_suite"}:
        return RecoveryAdmissionTier.VALIDATION_RECOVERABLE

    if mc == ToolMutationClass.READ_ONLY:
        return RecoveryAdmissionTier.READ_ONLY_RECOVERABLE

    if mc in {ToolMutationClass.WRITES_WORKSPACE, ToolMutationClass.MUTATES_GIT_STATE}:
        return RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY

    if mc == ToolMutationClass.EXTERNAL_SIDE_EFFECT:
        return RecoveryAdmissionTier.EXTERNAL_SIDE_EFFECT_REFUSE

    return RecoveryAdmissionTier.UNSUPPORTED_REFUSE


def _serialize_entries(entries: list[AdmittedToolEntry]) -> bytes:
    """Deterministically serialize entries for digest computation."""
    data = [
        {
            "canonical_name": e.canonical_name,
            "aliases": sorted(e.aliases),
            "mutation_class": e.mutation_class,
            "determinism_class": e.determinism_class,
            "args_schema_digest": e.args_schema_digest,
            "arg_field_names": e.arg_field_names,
            "recovery_admission_tier": str(e.recovery_admission_tier),
        }
        for e in entries
    ]
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"

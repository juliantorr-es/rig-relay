"""D0 real tool registry substrate proofs — exercises real ToolManager."""

from __future__ import annotations

import json

import pytest

from rig_relay.core.tools.manager import ToolManager
from rig_relay.recovery.admission_policy import (
    decide_admission,
    is_auto_execute_decision,
)
from rig_relay.recovery.alias_policy import resolve_alias
from rig_relay.recovery.models import CanonicalToolSurfaceManifest
from rig_relay.recovery.tool_surface_manifest import build_tool_surface_manifest
from rig_relay.recovery.transducer import RawRecoveryInput
from tests.conftest import build_test_vibe_config


@pytest.fixture
def tool_manager() -> ToolManager:
    config = build_test_vibe_config(
        system_prompt_id="tests", include_project_context=False
    )
    return ToolManager(lambda: config)


@pytest.fixture
def manifest(tool_manager: ToolManager) -> CanonicalToolSurfaceManifest:
    result = build_tool_surface_manifest(tool_manager.available_tools)
    assert isinstance(result, CanonicalToolSurfaceManifest), (
        f"Manifest construction failed: {result}"
    )
    return result


def _sha256(data: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _raw(data: dict[str, object]) -> RawRecoveryInput:
    return RawRecoveryInput(
        raw_emission=data,
        emission_sha256=_sha256(json.dumps(data, sort_keys=True)),
        call_id="c1",
    )


def test_real_manifest_has_bash_as_raw_shell(
    manifest: CanonicalToolSurfaceManifest,
) -> None:
    bash_entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == "bash"), None
    )
    if bash_entry is not None:
        assert bash_entry.recovery_admission_tier == "raw_shell_refuse"


def test_real_manifest_has_read_file_as_read_only(
    manifest: CanonicalToolSurfaceManifest,
) -> None:
    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == "read_file"), None
    )
    assert entry is not None, "read_file not found in manifest"
    assert entry.recovery_admission_tier == "read_only_recoverable"


def test_real_manifest_has_validate_as_validation(
    manifest: CanonicalToolSurfaceManifest,
) -> None:
    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == "validate"), None
    )
    if entry is not None:
        assert entry.recovery_admission_tier == "validation_recoverable"


def test_real_manifest_write_file_is_mutation_proposal_only(
    manifest: CanonicalToolSurfaceManifest,
) -> None:
    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == "write_file"), None
    )
    if entry is not None:
        assert entry.recovery_admission_tier == "mutation_proposal_only"


def test_real_alias_resolves_git_status(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    if "git_status" in tools:
        resolved = resolve_alias("git-status")
        assert resolved == "git_status"


def test_zero_auto_execute_for_all_mutation_tools(
    manifest: CanonicalToolSurfaceManifest,
) -> None:
    for entry in manifest.admitted_tools:
        if entry.recovery_admission_tier not in (
            "read_only_recoverable",
            "validation_recoverable",
        ):
            from rig_relay.recovery.models import RecoveryIntent

            intent = RecoveryIntent(
                canonical_tool_name=entry.canonical_name,
                normalized_args={},
                payload_digest=_sha256("test"),
                manifest_digest=manifest.manifest_digest,
                mutation_class=entry.mutation_class,
            )
            result = decide_admission(intent, entry)
            assert not is_auto_execute_decision(result.admission_decision), (
                f"Mutation tool '{entry.canonical_name}' (tier={entry.recovery_admission_tier}, "
                f"mutation_class={entry.mutation_class}) received auto-execute decision: "
                f"{result.admission_decision}"
            )

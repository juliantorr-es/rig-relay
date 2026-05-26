"""Test canonical tool-surface manifest construction from real ToolManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.core.tools.manager import ToolManager
from rig_relay.recovery.models import CanonicalToolSurfaceManifest
from rig_relay.recovery.tool_surface_manifest import build_tool_surface_manifest
from tests.conftest import build_test_vibe_config


@pytest.fixture
def tool_manager() -> ToolManager:
    config = build_test_vibe_config(
        system_prompt_id="tests", include_project_context=False
    )
    return ToolManager(lambda: config)


def test_manifest_contains_real_tools(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    assert len(tools) > 5, (
        f"Expected at least 6 tools in available_tools, got {len(tools)}"
    )


def test_manifest_is_deterministic(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest1 = build_tool_surface_manifest(tools)
    manifest2 = build_tool_surface_manifest(tools)
    assert isinstance(manifest1, CanonicalToolSurfaceManifest)
    assert isinstance(manifest2, CanonicalToolSurfaceManifest)
    assert manifest1.manifest_digest == manifest2.manifest_digest
    assert len(manifest1.admitted_tools) == len(manifest2.admitted_tools)


def test_manifest_entries_are_sorted(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    names = [e.canonical_name for e in manifest.admitted_tools]
    assert names == sorted(names), f"Tool entries not sorted: {names}"


def test_manifest_digest_is_valid_sha256(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    assert manifest.manifest_digest.startswith("sha256:")
    assert len(manifest.manifest_digest) == 71


def test_manifest_schema_valid(tool_manager: ToolManager) -> None:
    from jsonschema import validate

    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    manifest_dict = json.loads(manifest.model_dump_json())
    schema_path = (
        Path(__file__).parents[2]
        / "docs"
        / "schemas"
        / "rig.relay.tool_surface_manifest.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    validate(instance=manifest_dict, schema=schema)


def test_manifest_alias_entries_match_policy(tool_manager: ToolManager) -> None:
    from rig_relay.recovery.alias_policy import _ALIAS_MAP

    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    for entry in manifest.admitted_tools:
        for alias in entry.aliases:
            assert alias in _ALIAS_MAP, f"Alias {alias} not in alias map"
            assert _ALIAS_MAP[alias] == entry.canonical_name


def test_read_only_tools_have_read_only_tier(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    for entry in manifest.admitted_tools:
        if entry.mutation_class == "read_only":
            assert entry.recovery_admission_tier in (
                "read_only_recoverable",
                "validation_recoverable",
            ), (
                f"{entry.canonical_name}: read_only but tier={entry.recovery_admission_tier}"
            )


def test_mutation_tools_have_proposal_only_tier(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    mutation_classes = ("writes_workspace", "mutates_git_state")
    for entry in manifest.admitted_tools:
        if entry.mutation_class in mutation_classes and entry.canonical_name not in (
            "bash",
        ):
            assert entry.recovery_admission_tier == "mutation_proposal_only", (
                f"{entry.canonical_name}: {entry.mutation_class} "
                f"but tier={entry.recovery_admission_tier}"
            )


def test_bash_has_raw_shell_refuse_tier(tool_manager: ToolManager) -> None:
    tools = tool_manager.available_tools
    manifest = build_tool_surface_manifest(tools)
    assert isinstance(manifest, CanonicalToolSurfaceManifest)
    bash_entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == "bash"), None
    )
    if bash_entry is not None:
        assert bash_entry.recovery_admission_tier == "raw_shell_refuse"

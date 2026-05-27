from __future__ import annotations

from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles._projection import (
    build_profile_projection,
    merge_profile_projection_into_desktop,
)
from rig_relay.profiles._resolver import resolve_profile
from rig_relay.profiles.models import ProfileResolutionInput


def test_build_projection_with_resolution():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    proj = build_profile_projection(resolution, BUILTIN_PROFILES)
    assert proj["schema_version"] == "rig.relay.profile_resolution_projection.v1"
    assert proj["current_profile"] is not None
    assert proj["available_profile_count"] == len(BUILTIN_PROFILES)
    profiles = proj["profiles"]
    assert isinstance(profiles, list)
    assert len(profiles) == len(BUILTIN_PROFILES)


def test_build_projection_without_resolution():
    proj = build_profile_projection(None, BUILTIN_PROFILES)
    assert proj["current_profile"] is None
    assert proj["available_profile_count"] == len(BUILTIN_PROFILES)


def test_merge_into_desktop_projection():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    proj = build_profile_projection(resolution, BUILTIN_PROFILES)
    desktop: dict[str, object] = {"existing_section": "value"}
    merged = merge_profile_projection_into_desktop(desktop, proj)
    assert "existing_section" in merged
    assert "provider_profiles" in merged
    assert merged["provider_profiles"] == proj


def test_projection_content_light():
    inp = ProfileResolutionInput(
        provider="openai",
        model_id="gpt-4o",
        model_capabilities={"supports_tools": True},
    )
    resolution = resolve_profile(inp)
    proj = build_profile_projection(resolution, BUILTIN_PROFILES)
    forbidden = {"raw_prompt", "raw_file_contents", "secrets", "api_key"}
    proj_str = str(proj)
    for field in forbidden:
        assert field not in proj_str.lower(), (
            f"Forbidden field '{field}' found in projection"
        )


def test_projection_evaluation_summary():
    proj = build_profile_projection(None, BUILTIN_PROFILES)
    summary = proj["evaluation_summary"]
    assert isinstance(summary, dict)
    total = sum(summary.values())
    assert total == len(BUILTIN_PROFILES)

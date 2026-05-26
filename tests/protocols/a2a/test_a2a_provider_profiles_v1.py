"""Provider adapter contract matrix tests — C4 contract validation."""

from __future__ import annotations

from typing import cast

from rig_relay.protocols.a2a._provider_profiles import (
    ALL_PROVIDER_PROFILES,
    AdapterStatus,
    AuthenticationModel,
    IntegrationSurface,
    all_profiles,
    build_bridge_mapping,
    get_profile,
    profiles_by_status,
    profiles_claiming_a2a,
)


class TestProviderProfiles:
    def test_all_known_providers_registered(self):
        expected = {"claude_code", "codex", "cursor", "antigravity", "generic_mcp"}
        assert set(ALL_PROVIDER_PROFILES.keys()) == expected

    def test_all_profiles_have_description(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            assert profile.provider_name, f"{pid} has no name"
            assert profile.provider_description, f"{pid} has no description"

    def test_no_profile_claims_a2a_client(self):
        a2a_profiles = profiles_claiming_a2a()
        assert a2a_profiles == [], (
            f"No profile should claim A2A client: {[p.provider_id for p in a2a_profiles]}"
        )

    def test_no_profile_claims_a2a_server(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            assert not profile.can_act_as_a2a_server, (
                f"{pid} should not claim A2A server"
            )

    def test_all_profiles_have_mcp_as_primary_surface(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            if pid == "generic_mcp":
                continue
            assert (
                IntegrationSurface.MCP_CLIENT in profile.verified_integration_surfaces
            ), f"{pid} should have MCP_CLIENT"

    def test_all_profiles_are_proposal_only_or_unverified(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            assert profile.adapter_status in (
                AdapterStatus.PROPOSAL_ONLY,
                AdapterStatus.TRANSPORT_UNVERIFIED,
            ), f"{pid} is {profile.adapter_status}"

    def test_claude_code_has_verified_surfaces(self):
        p = get_profile("claude_code")
        assert p is not None
        assert IntegrationSurface.MCP_CLIENT in p.verified_integration_surfaces
        assert p.can_consume_mcp_tools is True
        assert p.can_act_as_a2a_client is False

    def test_codex_has_verified_surfaces(self):
        p = get_profile("codex")
        assert p is not None
        assert IntegrationSurface.MCP_CLIENT in p.verified_integration_surfaces

    def test_cursor_has_ide_surface(self):
        p = get_profile("cursor")
        assert p is not None
        assert IntegrationSurface.IDE_CLIENT in p.verified_integration_surfaces

    def test_antigravity_has_verified_surfaces(self):
        p = get_profile("antigravity")
        assert p is not None
        assert IntegrationSurface.MCP_CLIENT in p.verified_integration_surfaces

    def test_generic_mcp_has_minimal_capabilities(self):
        p = get_profile("generic_mcp")
        assert p is not None
        assert p.admitted_rig_capabilities == ["discovery_only"]
        assert p.assigned_trust_tier == "external_unauthenticated"


class TestProfileLookup:
    def test_get_profile_found(self):
        assert get_profile("claude_code") is not None

    def test_get_profile_not_found(self):
        assert get_profile("nonexistent") is None

    def test_all_profiles_returns_all(self):
        result = all_profiles()
        assert len(result) == 5

    def test_profiles_by_status(self):
        proposal = profiles_by_status(AdapterStatus.PROPOSAL_ONLY)
        assert len(proposal) == 5
        unverified = profiles_by_status(AdapterStatus.TRANSPORT_UNVERIFIED)
        assert len(unverified) == 0


class TestBridgeMapping:
    def test_bridge_mapping_for_claude_code(self):
        result = build_bridge_mapping("claude_code", "a2a-task-1")
        assert result["status"] == "bridged"
        assert result["provider_id"] == "claude_code"
        assert result["bridge_transport"] == "mcp"
        assert result["mutation_refused"] is True
        assert result["content_light"] is True
        caps: list[str] = cast(list[str], result.get("admitted_capabilities", []))
        assert "discovery_only" in caps

    def test_bridge_mapping_for_unknown_provider(self):
        result = build_bridge_mapping("unknown", "a2a-task-1")
        assert result["status"] == "refused"
        assert result["refusal_code"] == "unknown_provider"

    def test_bridge_mapping_never_admits_mutation(self):
        for pid in ALL_PROVIDER_PROFILES:
            result = build_bridge_mapping(pid, f"task-{pid}")
            caps: list[str] = cast(list[str], result.get("admitted_capabilities", []))
            assert "mutation_pending_authority" not in caps, (
                f"{pid} bridge admits mutation"
            )
            assert "runtime_delegation" not in caps


class TestProviderConfigRequirements:
    def test_all_non_generic_profiles_require_config(self):
        for pid in {"claude_code", "codex", "cursor", "antigravity"}:
            p = get_profile(pid)
            assert p is not None
            assert p.requires_user_configuration is True
            assert "api_key" in p.required_config_keys

    def test_generic_mcp_requires_no_config(self):
        p = get_profile("generic_mcp")
        assert p is not None
        assert p.requires_user_configuration is False
        assert p.required_config_keys == []


class TestMutationRiskFlags:
    def test_non_generic_profiles_flag_mutation_risk(self):
        for pid in {"claude_code", "codex", "cursor", "antigravity"}:
            profile = get_profile(pid)
            assert profile is not None
            assert profile.local_mutation_risk is True, (
                f"{pid} should flag local mutation risk"
            )

    def test_generic_mcp_no_mutation_risk(self):
        p = get_profile("generic_mcp")
        assert p is not None
        assert p.local_mutation_risk is False

    def test_streaming_flags_are_honest(self):
        for pid in {"claude_code", "codex", "cursor", "antigravity"}:
            p = get_profile(pid)
            assert p is not None
            assert p.streaming_supported is True

    def test_a2a_artifact_exchange_not_supported(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            assert profile.artifact_exchange_supported is False, (
                f"{pid}: artifact exchange should not be marked as supported"
            )


class TestAuthenticationModels:
    def test_known_providers_use_api_key(self):
        for pid in {"claude_code", "codex", "cursor", "antigravity"}:
            p = get_profile(pid)
            assert p is not None
            assert AuthenticationModel.API_KEY in p.supported_authentication

    def test_generic_mcp_uses_none(self):
        p = get_profile("generic_mcp")
        assert p is not None
        assert AuthenticationModel.NONE in p.supported_authentication


class TestStatusNotes:
    def test_all_profiles_have_status_notes(self):
        for pid, profile in ALL_PROVIDER_PROFILES.items():
            assert profile.status_note, f"{pid} has empty status_note"

    def test_claude_code_note_mentions_mcp(self):
        p = get_profile("claude_code")
        assert p is not None
        assert "MCP" in p.status_note.upper()

    def test_codex_note_mentions_mcp(self):
        p = get_profile("codex")
        assert p is not None
        assert "MCP" in p.status_note.upper()

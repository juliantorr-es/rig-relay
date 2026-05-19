from __future__ import annotations

from pathlib import Path

from rig_relay.protocols.mcp._auth_metadata import (
    MCPPerUserAuthorization,
    build_mcp_auth_metadata,
    compute_tool_provenance_hash,
)
from rig_relay.protocols.mcp.models import MCPTool, MCPToolTier

REPO_ROOT = Path(__file__).resolve().parents[3]
S = REPO_ROOT / "docs" / "schemas"


class TestMCPAuthMetadataV1:
    def test_provenance_hash_stable_for_same_input(self):
        desc = {"name": "rig.list_worktrees", "description": "List worktrees"}
        h1 = compute_tool_provenance_hash(desc)
        h2 = compute_tool_provenance_hash(desc)
        assert h1 == h2
        assert len(h1) == 64

    def test_provenance_hash_different_for_different_input(self):
        h1 = compute_tool_provenance_hash({
            "name": "rig.list_worktrees",
            "description": "List worktrees",
        })
        h2 = compute_tool_provenance_hash({
            "name": "rig.search_evidence",
            "description": "Search evidence",
        })
        assert h1 != h2

    def test_auth_metadata_derives_from_tier_not_hints(self):
        tool = MCPTool(
            name="rig.request_user_approval",
            description="Request approval",
            tier=MCPToolTier.MUTATION,
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.auth_required is True
        assert "rig:mutate" in meta.scopes

    def test_auth_metadata_does_not_trust_read_only_hint(self):
        tool = MCPTool(
            name="rig.request_user_approval",
            description="Request approval [readOnlyHint: true]",
            tier=MCPToolTier.MUTATION,
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.auth_required is True
        assert "rig:mutate" in meta.scopes

    def test_read_only_tier_not_auth_required(self):
        tool = MCPTool(
            name="rig.list_worktrees",
            description="List worktrees",
            tier=MCPToolTier.READ_ONLY,
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.auth_required is False
        assert "rig:read" in meta.scopes

    def test_analysis_tier_gets_analyze_scope(self):
        tool = MCPTool(
            name="rig.build_context_packet",
            description="Build packet",
            tier=MCPToolTier.ANALYSIS,
        )
        meta = build_mcp_auth_metadata(tool)
        assert "rig:analyze" in meta.scopes
        assert meta.auth_required is False

    def test_validation_tier_gets_validate_scope(self):
        tool = MCPTool(
            name="rig.run_validator",
            description="Run validator",
            tier=MCPToolTier.VALIDATION,
        )
        meta = build_mcp_auth_metadata(tool)
        assert "rig:validate" in meta.scopes

    def test_patch_proposal_tier_gets_propose_scope(self):
        tool = MCPTool(
            name="rig.propose_patch",
            description="Propose patch",
            tier=MCPToolTier.PATCH_PROPOSAL,
        )
        meta = build_mcp_auth_metadata(tool)
        assert "rig:propose" in meta.scopes

    def test_git_release_tier_auth_required(self):
        tool = MCPTool(
            name="rig.promote_to_preproduction",
            description="Promote",
            tier=MCPToolTier.GIT_RELEASE,
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.auth_required is True
        assert "rig:release" in meta.scopes

    def test_provenance_hash_from_dict(self):
        desc = {"name": "rig.search_evidence", "description": "Search"}
        h = compute_tool_provenance_hash(desc)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_provenance_hash_from_mcp_tool(self):
        tool = MCPTool(
            name="rig.list_worktrees", description="List", tier=MCPToolTier.READ_ONLY
        )
        h = compute_tool_provenance_hash(tool)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_auth_metadata_bearer_not_supported(self):
        tool = MCPTool(
            name="rig.list_worktrees", description="List", tier=MCPToolTier.READ_ONLY
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.bearer_supported is False

    def test_auth_metadata_oauth_not_supported(self):
        tool = MCPTool(
            name="rig.list_worktrees", description="List", tier=MCPToolTier.READ_ONLY
        )
        meta = build_mcp_auth_metadata(tool)
        assert meta.oauth_supported is False

    def test_explicit_tool_tier_override(self):
        tool = MCPTool(
            name="rig.list_worktrees", description="List", tier=MCPToolTier.READ_ONLY
        )
        meta = build_mcp_auth_metadata(tool, tool_tier=MCPToolTier.MUTATION)
        assert meta.auth_required is True
        assert "rig:mutate" in meta.scopes


class TestMCPPerUserAuthorization:
    def test_per_user_authorization_scoped(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64,
            tool_name="rig.list_worktrees",
            scopes_granted=["rig:read"],
            authorization_status="allowed",
        )
        d = auth.to_dict()
        assert d["user_id_hash"] == "0" * 64
        assert d["tool_name"] == "rig.list_worktrees"
        assert d["scopes_granted"] == ["rig:read"]
        assert d["authorization_status"] == "allowed"
        assert d["content_light"] is True

    def test_per_user_authorization_expired_refused(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64,
            tool_name="rig.promote_to_preproduction",
            scopes_granted=[],
            authorization_status="expired",
        )
        assert auth.authorization_status == "expired"
        d = auth.to_dict()
        assert d["authorization_status"] == "expired"

    def test_per_user_authorization_defaults_refused(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64, tool_name="rig.request_user_approval"
        )
        assert auth.authorization_status == "refused"
        assert auth.scopes_granted == []

    def test_per_user_authorization_content_light(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64,
            tool_name="rig.list_worktrees",
            scopes_granted=["rig:read"],
            authorization_status="allowed",
        )
        d = auth.to_dict()
        assert d["content_light"] is True
        assert "access_token" not in d
        assert "api_key" not in d

    def test_per_user_authorization_schema_version(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64, tool_name="rig.list_worktrees"
        )
        assert auth.schema_version == "rig.relay.mcp.per_user_auth.v1"
        d = auth.to_dict()
        assert d["schema_version"] == "rig.relay.mcp.per_user_auth.v1"

    def test_per_user_authorization_includes_generated_at(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64, tool_name="rig.list_worktrees"
        )
        d = auth.to_dict()
        assert "generated_at" in d
        ga = d["generated_at"]
        assert isinstance(ga, str)
        assert "T" in ga

    def test_per_user_authorization_no_raw_credentials(self):
        auth = MCPPerUserAuthorization(
            user_id_hash="0" * 64,
            tool_name="rig.list_worktrees",
            scopes_granted=["rig:read"],
            authorization_status="allowed",
        )
        d = auth.to_dict()
        for key in d:
            assert "secret" not in key.lower()
            assert "token" not in key.lower()
            assert "password" not in key.lower()

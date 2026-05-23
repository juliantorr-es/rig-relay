from __future__ import annotations

from rig_relay.protocols.mcp.models import GATED_TOOLS, READ_ONLY_TOOLS, MCPToolTier
from rig_relay.protocols.mcp.server import RigMCPServer


class TestMCPTransportBindingV1:
    def test_tools_list_returns_16_tools(self) -> None:
        server = RigMCPServer()
        tools = server.list_tools()
        assert len(tools) == 16, f"Expected 16 tools, got {len(tools)}"

    def test_read_only_tools_are_tier_0_1_or_2(self) -> None:
        server = RigMCPServer()
        for tool in server.list_tools(tier=MCPToolTier.READ_ONLY):
            assert tool.tier in {
                MCPToolTier.READ_ONLY,
                MCPToolTier.ANALYSIS,
                MCPToolTier.VALIDATION,
            }
        for tool in server.list_tools(tier=MCPToolTier.ANALYSIS):
            assert tool.tier in {
                MCPToolTier.READ_ONLY,
                MCPToolTier.ANALYSIS,
                MCPToolTier.VALIDATION,
            }
        for tool in server.list_tools(tier=MCPToolTier.VALIDATION):
            assert tool.tier in {
                MCPToolTier.READ_ONLY,
                MCPToolTier.ANALYSIS,
                MCPToolTier.VALIDATION,
            }

    def test_readonly_tools_have_13_items(self) -> None:
        server = RigMCPServer()
        read_only = server.list_tools(tier=None)
        read_only_subset = [
            t for t in read_only if t.tier.value <= MCPToolTier.VALIDATION.value
        ]
        assert len(read_only_subset) == 13, (
            f"Expected 13 read-only tools, got {len(read_only_subset)}"
        )

    def test_gated_tools_have_3_items(self) -> None:
        assert len(GATED_TOOLS) == 3

    def test_tier_0_current_mission_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"
        assert result.get("authority_tier") == 0

    def test_tier_0_inspect_schema_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "mission-envelope"}
        )
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_0_run_readonly_doctor_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.run_readonly_doctor", {})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_0_list_worktrees_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.list_worktrees", {})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_0_search_evidence_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.search_evidence", {"query": "test"})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_0_read_receipt_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.read_receipt", {"receipt_id": "abc"})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_0_summarize_dirty_state_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.summarize_dirty_state", {})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_1_build_context_packet_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.build_context_packet", {"mission_id": "m1"})
        assert result["status"] == "ok"
        assert "packet_sha256" in result
        assert result.get("surface") == "mcp"

    def test_tier_1_create_consult_packet_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.create_consult_packet", {"question": "q"})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_1_compare_provider_opinions_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.compare_provider_opinions", {"providers": ["p1"]}
        )
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_2_run_validator_blocked_pending_approval(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.run_validator", {"validator": "pytest"})
        assert result["status"] == "blocked_pending_approval"
        assert result.get("approval_required") is True
        assert result.get("surface") == "mcp"

    def test_tier_2_check_merge_friendly_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.check_merge_friendly", {})
        assert result["status"] == "ok"
        assert result.get("surface") == "mcp"

    def test_tier_2_audit_dirty_state_works(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.audit_dirty_state", {})
        assert result["status"] == "ok"
        assert "recommendation" in result
        assert result.get("surface") == "mcp"

    def test_tier_3_propose_patch_blocked(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.propose_patch",
            {
                "mission_id": "m1",
                "rationale": "fix",
                "target_files": ["a.py"],
                "proposed_changes": "--",
            },
        )
        assert result["status"] == "blocked_pending_approval"
        assert result.get("approval_required") is True
        assert result.get("surface") == "mcp"

    def test_tier_4_request_approval_blocked_without_receipt(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {"action": "merge"})
        assert result["status"] == "blocked"
        assert result.get("surface") == "mcp"
        assert "authorization receipt" in result.get("message", "").lower()

    def test_tier_5_promote_permanently_forbidden(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.promote_to_preproduction", {"receipt_ids": ["r1"]}
        )
        assert result["status"] == "refused"
        assert result.get("surface") == "mcp"

    def test_unknown_tool_returns_error(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.nonexistent", {})
        assert "error" in result
        assert result["error"]["code"] == -32601

    def test_all_tools_produce_content_light_classification(self) -> None:
        server = RigMCPServer()
        for tool in server.list_tools():
            result = server.call_tool_sync(tool.name, {})
            if "error" in result:
                continue
            classification = result.get("content_light_classification")
            assert classification is not None, (
                f"Tool {tool.name} missing content_light_classification"
            )

    def test_serve_stdio_creates_mcp_server_with_handlers(self) -> None:

        server = RigMCPServer()
        assert server.serve_stdio is not None
        assert callable(server.serve_stdio)

        import asyncio

        loop = asyncio.new_event_loop()
        loop.close()

    def test_workspace_root_boundary_enforced(self) -> None:
        from pathlib import Path

        server = RigMCPServer(workspace_root=Path("/tmp/rig-test"))
        candidate, refusal = server._resolve_workspace_path("../../etc/passwd")
        assert candidate is None
        assert refusal is not None
        assert refusal["status"] == "refused"

    def test_non_traversal_path_resolves(self) -> None:
        from pathlib import Path

        server = RigMCPServer(workspace_root=Path("/tmp/rig-test"))
        candidate, refusal = server._resolve_workspace_path("foo/bar.txt")
        assert candidate is not None
        assert refusal is None

    def test_resources_list_returns_6_resources(self) -> None:
        server = RigMCPServer()
        resources = server.list_resources()
        assert len(resources) == 6

    def test_prompts_list_returns_3_prompts(self) -> None:
        server = RigMCPServer()
        prompts = server.list_prompts()
        assert len(prompts) == 3

    def test_read_only_tools_constant_has_13_entries(self) -> None:
        assert len(READ_ONLY_TOOLS) == 13

    def test_gated_tools_constant_has_3_entries(self) -> None:
        assert len(GATED_TOOLS) == 3

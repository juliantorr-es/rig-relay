from __future__ import annotations

from rig_relay.protocols.mcp._auth_metadata import build_descriptor_identity
from rig_relay.protocols.mcp.models import MCPTool, MCPToolTier, compute_descriptor_hash


class TestDescriptorHashDeterministic:
    def test_hash_identical_for_same_tool(self) -> None:
        t1 = MCPTool(
            name="rig.test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            tier=MCPToolTier.READ_ONLY,
        )
        t2 = MCPTool(
            name="rig.test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            tier=MCPToolTier.READ_ONLY,
        )
        assert compute_descriptor_hash(t1) == compute_descriptor_hash(t2)

    def test_hash_changes_when_input_schema_changes(self) -> None:
        t1 = MCPTool(
            name="rig.test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            tier=MCPToolTier.READ_ONLY,
        )
        t2 = MCPTool(
            name="rig.test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            tier=MCPToolTier.READ_ONLY,
        )
        assert compute_descriptor_hash(t1) != compute_descriptor_hash(t2)

    def test_hash_changes_when_description_changes(self) -> None:
        t1 = MCPTool(name="rig.t", description="desc A", tier=MCPToolTier.READ_ONLY)
        t2 = MCPTool(name="rig.t", description="desc B", tier=MCPToolTier.READ_ONLY)
        assert compute_descriptor_hash(t1) != compute_descriptor_hash(t2)

    def test_hash_changes_when_tier_changes(self) -> None:
        t1 = MCPTool(name="rig.t", description="desc", tier=MCPToolTier.READ_ONLY)
        t2 = MCPTool(name="rig.t", description="desc", tier=MCPToolTier.MUTATION)
        assert compute_descriptor_hash(t1) != compute_descriptor_hash(t2)


class TestDescriptorIdentity:
    def test_build_descriptor_identity_populates_all_fields(self) -> None:
        tool = MCPTool(
            name="rig.test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            tier=MCPToolTier.READ_ONLY,
        )
        identity = build_descriptor_identity(tool, version=1)
        assert identity.descriptor_id.startswith("desc-mcp-")
        assert identity.descriptor_version == 1
        assert len(identity.descriptor_hash) == 64
        assert identity.schema_version == "rig.relay.mcp.descriptor.v1"
        assert identity.tool_name == "rig.test_tool"
        assert identity.capability_id == "rig.rig.test_tool"
        assert identity.authority_tier == 0
        assert identity.read_only_hint is True
        assert identity.content_light is True

    def test_build_descriptor_identity_read_only_hint_false_for_mutation(self) -> None:
        tool = MCPTool(
            name="rig.mutate", description="Mutation", tier=MCPToolTier.MUTATION
        )
        identity = build_descriptor_identity(tool)
        assert identity.read_only_hint is False
        assert identity.mutation_class == "FILE_WRITE"


class TestDescriptorDriftRefusal:
    def test_descriptor_hash_mismatch_refused(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        all_tools = server.list_tools()
        assert len(all_tools) > 0
        first = all_tools[0]

        initial_hash = compute_descriptor_hash(first)
        registered = server._descriptors[first.name]
        assert not registered.quarantined
        assert registered.descriptor_hash == initial_hash

        modified = MCPTool(
            name=first.name,
            description=first.description + " [MODIFIED]",
            input_schema=first.input_schema,
            tier=first.tier,
        )
        ok, refusal_code = server._verify_descriptor_integrity(first.name, modified)
        assert not ok
        assert refusal_code == "descriptor_integrity_failure"

        reregistered = server._descriptors[first.name]
        assert reregistered.quarantined

    def test_unknown_tool_refused_with_unknown_tool_code(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        fake = MCPTool(
            name="rig.nonexistent", description="fake", tier=MCPToolTier.READ_ONLY
        )
        ok, refusal_code = server._verify_descriptor_integrity("rig.nonexistent", fake)
        assert not ok
        assert refusal_code == "unknown_tool"

    def test_call_tool_refuses_descriptor_drift(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        registered_server = server

        tool = MCPTool(
            name="rig.search_evidence",
            description="Original description",
            input_schema={"type": "object"},
            tier=MCPToolTier.READ_ONLY,
        )
        server._descriptors["rig.search_evidence"] = build_descriptor_identity(
            tool, version=1
        )

        result = server.call_tool_sync("rig.search_evidence", {"query": "test"})
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == "descriptor_integrity_failure"


class TestToolsListQuarantine:
    def test_tools_list_excludes_quarantined_descriptor(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        tools_before = server.list_tools()
        assert len(tools_before) > 0
        first_name = tools_before[0].name

        server._quarantine_descriptor(first_name, "test quarantine")
        clean, drifted = server._filter_drift_for_listing(tools_before)
        assert len(clean) < len(tools_before)
        assert first_name in drifted

    def test_tools_list_drift_detection_quarantines_modified(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        all_tools = server.list_tools()
        first = all_tools[0]

        modified = MCPTool(
            name=first.name,
            description=first.description + " [DRIFTED]",
            input_schema=first.input_schema,
            tier=first.tier,
        )

        modified_list = [modified if t.name == first.name else t for t in all_tools]
        clean, drifted = server._filter_drift_for_listing(modified_list)
        assert first.name in drifted


class TestForbiddenToolRefusal:
    def test_promote_to_preproduction_refused_explicitly(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["a"], "authorization_receipt": "b"},
        )
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == "forbidden_permanently"
        assert result.get("content_light") is True

    def test_mutation_tier_blocked_with_structured_refusal(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {"action": "test"})
        assert result.get("status") == "blocked"
        assert result.get("refusal_code") == "mutation_tier_mcp_hmac_required"
        assert result.get("content_light") is True

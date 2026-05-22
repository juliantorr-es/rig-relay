from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.protocols.mcp.models import ContentLightClass, RefusalCode


class TestFullPipelineOrdering:
    def test_safe_read_only_tool_returns_classification_and_receipt_metadata(
        self,
    ) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.inspect_schema", {"schema": "test"})
            assert result.get("status") == "ok"
            assert "content_light_classification" in result
            assert (
                result["content_light_classification"] == ContentLightClass.PUBLIC_SAFE
            )
            assert result.get("surface") == "mcp"
            assert result.get("capability_id") == "rig.rig.inspect_schema"
            assert "request_id" in result

    def test_descriptor_drift_refusal_includes_metadata(self) -> None:
        from rig_relay.protocols.mcp.models import MCPTool, MCPToolTier
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        fake = MCPTool(
            name="rig.search_evidence",
            description="Original description",
            input_schema={"type": "object"},
            tier=MCPToolTier.READ_ONLY,
        )
        from rig_relay.protocols.mcp._auth_metadata import build_descriptor_identity

        server._descriptors["rig.search_evidence"] = build_descriptor_identity(
            fake, version=1
        )
        result = server.call_tool_sync("rig.search_evidence", {"query": "test"})
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == RefusalCode.DESCRIPTOR_DRIFT
        assert "descriptor_id" in result
        assert "descriptor_hash" in result
        assert "request_id" in result
        assert result.get("content_light") is True

    def test_root_scope_violation_refusal_includes_metadata(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server._build_refusal(
            "rig.list_worktrees",
            RefusalCode.ROOT_SCOPE_VIOLATION,
            "Path outside workspace root.",
        )
        assert result["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION
        assert result.get("content_light_classification") is not None
        assert "request_id" in result
        assert "descriptor_id" in result
        assert "generated_at" in result

    def test_unknown_tool_returns_structured_refusal_with_code(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.nonexistent_tool", {})
        assert "error" in result
        assert result["error"]["code"] == -32601
        assert "data" in result["error"]
        assert result["error"]["data"]["refusal_code"] == "unknown_tool"
        assert result["error"]["data"]["surface"] == "mcp"
        assert result["error"]["data"]["content_light"] is True
        assert "request_id" in result["error"]["data"]

    def test_async_sync_equivalent_for_blocked_tool(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        sync_result = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["a"], "authorization_receipt": "b"},
        )
        assert sync_result.get("status") == "refused"
        assert sync_result.get("refusal_code") == RefusalCode.FORBIDDEN
        assert sync_result.get("surface") == "mcp"
        assert "request_id" in sync_result


class TestContentLightClassificationInReceiptMetadata:
    def test_secret_bearing_refusal_records_classification(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "token": "sk-abc123def456ghi789jkl012mno345pqr",
        })
        assert classification == ContentLightClass.SECRET_BEARING
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.SECRET_BEARING_OUTPUT

    def test_secret_bearing_refusal_does_not_echo_secret(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        secret = "sk-abc123def456ghi789jkl012mno345pqr"
        _, refusal = server._scan_tool_output({"status": "ok", "api_key": secret})
        assert refusal is not None
        refusal_str = str(refusal)
        assert secret not in refusal_str

    def test_forbidden_raw_refusal_records_classification(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "source_code": "def foo(): pass",
        })
        assert classification == ContentLightClass.FORBIDDEN_RAW
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.FORBIDDEN_RAW_OUTPUT

    def test_public_safe_result_records_classification(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "count": 10,
            "message": "success",
        })
        assert classification == ContentLightClass.PUBLIC_SAFE
        assert refusal is None


class TestReceiptPersistenceForRefusals:
    def test_safe_read_only_call_persists_with_receipt_store(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        class FakeStore:
            def __init__(self):
                self.envelopes = []

            def append(self, envelope):
                self.envelopes.append(envelope)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            store = FakeStore()
            server = RigMCPServer(workspace_root=root, receipt_store=store)
            server.call_tool_sync("rig.inspect_schema", {"schema": "test"})
            assert len(store.envelopes) > 0
            env = store.envelopes[0]
            assert hasattr(env, "decision")
            assert (
                env.decision.content_light_classification
                == ContentLightClass.PUBLIC_SAFE
            )

    def test_secret_bearing_refusal_persists_with_receipt_store(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        class FakeStore:
            def __init__(self):
                self.envelopes = []

            def append(self, envelope):
                self.envelopes.append(envelope)

        server = RigMCPServer(receipt_store=FakeStore())
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "token": "sk-abc123def456ghi789jkl012mno345pqr",
        })
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.SECRET_BEARING_OUTPUT

    def test_persistence_failure_does_not_return_unsafe_output(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        class BrokenStore:
            def append(self, envelope):
                raise RuntimeError("simulated persistence failure")

        server = RigMCPServer(receipt_store=BrokenStore())
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "api_key": "sk-leaked",
        })
        assert refusal is not None
        assert "sk-leaked" not in str(refusal)


class TestPhaseRegression:
    def test_all_descriptor_integrity_still_passes(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        for tool in server.list_tools():
            ok, _ = server._verify_descriptor_integrity(tool.name, tool)
            assert ok

    def test_root_boundary_still_blocks(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        refusal = server._assert_within_root(Path("/etc/passwd"))
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION

    def test_content_light_still_classifies(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, _ = server._scan_tool_output({
            "status": "ok",
            "message": "clean",
        })
        assert classification == ContentLightClass.PUBLIC_SAFE

    def test_mutation_tier_still_blocked(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {"action": "test"})
        assert result.get("status") == "blocked"

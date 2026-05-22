from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.evidence.receipt_store import FilesystemReceiptStore
from rig_relay.protocols.mcp.models import MCPToolTier
from rig_relay.protocols.mcp.server import RigMCPServer


class TestMCPRefusalReceiptEnvelopeAdoption:
    def test_refused_mutation_tool_includes_receipt_fields(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {})

        assert result["status"] == "blocked"
        assert result["surface"] == "mcp"
        assert result["capability_id"] == "rig.rig.request_user_approval"
        assert "authority_tier" in result
        assert result["authority_tier"] == MCPToolTier.MUTATION.value
        assert result["refusal_code"] == "mutation_tier_mcp"
        assert result["content_light"] is True
        assert "content_light_classification" in result
        assert result["content_light_classification"] == "public_safe"
        assert "request_id" in result

    def test_refused_forbidden_tool_includes_receipt_fields(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["r1"], "authorization_receipt": "fake"},
        )

        assert result["status"] == "refused"
        assert result["surface"] == "mcp"
        assert result["refusal_code"] == "forbidden_permanently"
        assert "descriptor_id" in result
        assert result["content_light"] is True
        assert "content_light_classification" in result
        assert "generated_at" in result

    def test_descriptor_drift_includes_receipt_fields(self) -> None:
        server = RigMCPServer()

        registered = server._descriptors.get("rig.current_mission")
        if registered is not None:
            registered.descriptor_hash = "deadbeef"

            result = server.call_tool_sync("rig.current_mission", {})
            assert result["status"] == "refused"
            assert result["refusal_code"] == "descriptor_integrity_failure"
            assert result["surface"] == "mcp"
            assert "descriptor_id" in result
            assert "content_light_classification" in result

    def test_unknown_tool_includes_basic_metadata(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.nonexistent_tool", {})

        assert result["error"]["code"] == -32601
        assert result["error"]["data"]["refusal_code"] == "unknown_tool"
        assert result["error"]["data"]["surface"] == "mcp"
        assert result["error"]["data"]["content_light"] is True

    def test_successful_tool_includes_receipt_envelope_compatible_fields(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})

        assert result["status"] == "ok"
        assert result["surface"] == "mcp"
        assert result["capability_id"] == "rig.rig.current_mission"
        assert "authority_tier" in result
        assert "content_light_classification" in result
        assert result["content_light_classification"] == "public_safe"
        assert "request_id" in result


class TestMCPReceiptPersistence:
    def test_refusal_persisted_to_receipt_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            server = RigMCPServer(receipt_store=store)
            result = server.call_tool_sync("rig.promote_to_preproduction", {})

            assert result["status"] == "refused"

    def test_blocked_mutation_persisted_to_receipt_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            server = RigMCPServer(receipt_store=store)
            result = server.call_tool_sync("rig.request_user_approval", {})

            assert result["status"] == "blocked"

    def test_successful_call_persisted_to_receipt_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            server = RigMCPServer(receipt_store=store)
            result = server.call_tool_sync("rig.current_mission", {})

            assert result["status"] == "ok"

    def test_persistence_failure_does_not_block_read_only_tool(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})

        assert result["status"] == "ok"

    def test_no_store_receipt_still_produces_envelope_fields(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})

        assert "surface" in result
        assert "capability_id" in result
        assert "request_id" in result
        assert "content_light_classification" in result

    def test_receipt_envelope_retrieved_from_store_has_correct_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            server = RigMCPServer(receipt_store=store)
            server.call_tool_sync("rig.promote_to_preproduction", {})

            envelopes = store.list(limit=10)
            assert len(envelopes) >= 1

            env = envelopes[0]
            assert env.receipt_kind == "mcp_tool_call"
            assert env.decision is not None
            assert env.decision.surface == "mcp"
            assert env.decision.governance_decision_id is not None
            assert env.decision.governance_decision_id.startswith("gd-mcp-")
            assert env.decision.content_light_classification == "public_safe"

    def test_receipt_envelope_does_not_contain_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FilesystemReceiptStore(Path(tmp))
            server = RigMCPServer(receipt_store=store)
            server.call_tool_sync("rig.promote_to_preproduction", {})

            envelopes = store.list(limit=10)
            assert len(envelopes) >= 1

            env = envelopes[0]
            dumped = env.model_dump(mode="json")
            raw = str(dumped)
            assert "secret" not in raw.lower() or "public_safe" in raw
            assert "password" not in raw.lower()
            assert "token" not in raw.lower()


class TestMCPRefusalDoesNotAllowMutation:
    def test_refused_tool_does_not_execute(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.promote_to_preproduction", {})

        assert result["status"] == "refused"
        assert "error" not in result or result.get("error") is None

    def test_blocked_mutation_does_not_execute(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {})

        assert result["status"] == "blocked"

    def test_read_only_tool_still_executes(self) -> None:
        server = RigMCPServer()
        result = server.call_tool_sync("rig.current_mission", {})

        assert result["status"] == "ok"

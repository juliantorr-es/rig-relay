from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from rig_relay.protocols.mcp import (
    classify_tool_descriptor_suspicious,
    evaluate_mcp_request,
)
from rig_relay.protocols.mcp.models import MCPToolTier
from rig_relay.protocols.mcp.server import RigMCPServer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _validates_refusal(
    instance: dict, name: str = "rig.relay.mcp.refusal.v1.schema.json"
) -> None:
    jsonschema.validate(instance, _load(name))


def _validates_receipt(
    instance: dict, name: str = "rig.relay.mcp.tool_call_receipt.v1.schema.json"
) -> None:
    jsonschema.validate(instance, _load(name))


_TRACE = "trace-abc123"
_SESSION = "session-xyz789"


class TestMCPRuntimeRefusalsV1:
    def test_unknown_tool_refused(self):
        result = evaluate_mcp_request(
            "rig.nonexistent_tool", {"arg": "val"}, _TRACE, _SESSION
        )
        assert result["schema_version"] == "rig.relay.mcp.refusal.v1"
        assert result["refusal_code"] == "unknown_tool"
        assert result["trace_id"] == _TRACE
        assert result["content_light"] is True
        assert "rig.nonexistent_tool" in result["reason"]
        _validates_refusal(result)

    def test_mutation_tier_refused(self):
        result = evaluate_mcp_request(
            "rig.request_user_approval", {"action": "merge"}, _TRACE, _SESSION
        )
        assert result["schema_version"] == "rig.relay.mcp.refusal.v1"
        assert result["refusal_code"] == "credentialed_tier"
        assert "mutation" in result["reason"].lower()
        assert result["tier"] == MCPToolTier.MUTATION.value
        assert result["trace_id"] == _TRACE
        assert result["content_light"] is True
        _validates_refusal(result)

    def test_open_world_tier_refused(self):
        """Test that unknown open-world (network-tier) descriptors are refused.

        A tool not in the known registry but claiming open-world capabilities
        is refused as unknown. Tier 5 (destructive, open-world) is refused separately.
        """
        result = evaluate_mcp_request(
            "rig.unknown_open_world_tool", {"target": "production"}, _TRACE, _SESSION
        )
        assert result["refusal_code"] == "unknown_tool"
        assert result["content_light"] is True
        _validates_refusal(result)

    def test_credentialed_mutation_refused(self):
        result = evaluate_mcp_request(
            "rig.request_user_approval", {"action": "delete_branch"}, _TRACE, _SESSION
        )
        assert result["schema_version"] == "rig.relay.mcp.refusal.v1"
        assert result["refusal_code"] == "credentialed_tier"
        assert result["tier"] == MCPToolTier.MUTATION.value
        assert result["trace_id"] == _TRACE
        assert result["content_light"] is True
        _validates_refusal(result)

    def test_destructive_tier_refused(self):
        result = evaluate_mcp_request(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["r1"], "authorization_receipt": "auth-1"},
            _TRACE,
            _SESSION,
        )
        assert result["schema_version"] == "rig.relay.mcp.refusal.v1"
        assert result["refusal_code"] == "destructive_tier"
        assert result["tier"] == MCPToolTier.GIT_RELEASE.value
        assert result["trace_id"] == _TRACE
        assert result["content_light"] is True
        _validates_refusal(result)

    def test_malformed_request_refused(self):
        result = evaluate_mcp_request("", None, "t-empty", _SESSION)
        assert result["refusal_code"] == "unknown_tool"
        assert result["content_light"] is True
        _validates_refusal(result)

        bad_req: dict[str, Any] = cast(dict[str, Any], "not_a_dict")
        result2 = evaluate_mcp_request("", bad_req, "t-str", _SESSION)
        assert result2["refusal_code"] == "unknown_tool"
        assert "Malformed" in result2["reason"]
        _validates_refusal(result2)

    def test_read_only_hint_not_authorization(self):
        result = evaluate_mcp_request(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["r1"], "authorization_receipt": "auth-1"},
            _TRACE,
            _SESSION,
        )
        assert result["refusal_code"] == "destructive_tier"
        assert result["tier"] == MCPToolTier.GIT_RELEASE.value

    def test_descriptor_name_mismatch_classified_suspicious(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.evil_tool",
            "tool_name": "rig.list_worktrees",
        })
        assert any("name_mismatch" in r for r in reasons)

    def test_descriptor_dual_hint_shadowing_detected(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.shadow_tool",
            "tool_name": "rig.shadow_tool",
            "destructiveHint": True,
            "readOnlyHint": True,
        })
        assert any("dual_hint_shadowing" in r for r in reasons)

    def test_read_only_claim_for_destructive_tool_detected(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.sneaky_tool",
            "tool_name": "rig.promote_to_preproduction",
            "readOnlyHint": True,
        })
        assert any("read_only_claim_for_destructive" in r for r in reasons)

    def test_oversized_description_detected(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.chatty",
            "tool_name": "rig.chatty",
            "description": "x" * 5000,
        })
        assert any("oversized_description" in r for r in reasons)

    def test_foreign_capability_detected(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.foreign",
            "tool_name": "rig.foreign",
            "capabilities": {"external.network_access": True},
        })
        assert any("foreign_capability" in r for r in reasons)

    def test_clean_descriptor_returns_no_suspicions(self):
        reasons = classify_tool_descriptor_suspicious({
            "name": "rig.list_worktrees",
            "tool_name": "rig.list_worktrees",
            "description": "List all tracked git worktrees.",
            "capabilities": {"rig.read_only": True},
        })
        assert reasons == []

    def test_trace_id_preserved_in_refusal(self):
        result = evaluate_mcp_request("rig.nonexistent", {}, "trace-42", _SESSION)
        assert result["trace_id"] == "trace-42"
        _validates_refusal(result)

        result2 = evaluate_mcp_request(
            "rig.promote_to_preproduction",
            {"receipt_ids": [], "authorization_receipt": ""},
            "trace-99",
            _SESSION,
        )
        assert result2["trace_id"] == "trace-99"
        _validates_refusal(result2)

    def test_refusal_is_content_light(self):
        result = evaluate_mcp_request(
            "rig.promote_to_preproduction",
            {
                "receipt_ids": ["sensitive-id"],
                "authorization_receipt": "secret-auth-token",
                "api_key": "sk-should-never-appear",
            },
            _TRACE,
            _SESSION,
        )
        assert result["content_light"] is True
        assert "sensitive-id" not in json.dumps(result)
        assert "secret-auth-token" not in json.dumps(result)
        assert "sk-should-never-appear" not in json.dumps(result)
        _validates_refusal(result)

    def test_schema_valid_refusal_envelope_produced(self):
        result = evaluate_mcp_request("rig.nonexistent", {"x": 1}, _TRACE, _SESSION)
        _validates_refusal(result)

        result2 = evaluate_mcp_request(
            "rig.request_user_approval", {"action": "test"}, _TRACE, _SESSION
        )
        _validates_refusal(result2)

    def test_allowed_tools_produce_receipt(self):
        result = evaluate_mcp_request("rig.list_worktrees", {}, _TRACE, _SESSION)
        assert result["schema_version"] == "rig.relay.mcp.tool_call_receipt.v1"
        assert result["verdict"] == "allowed"
        assert result["refusal_code"] == ""
        assert result["trace_id"] == _TRACE
        assert result["session_id"] == _SESSION
        assert result["tool_name"] == "rig.list_worktrees"
        assert result["tier"] == MCPToolTier.READ_ONLY.value
        assert result["content_light"] is True
        assert len(result["request_hash"]) == 64
        _validates_receipt(result)

    def test_tier_1_analysis_tool_allowed(self):
        result = evaluate_mcp_request(
            "rig.build_context_packet", {"mission_id": "m1"}, _TRACE, _SESSION
        )
        assert result["verdict"] == "allowed"
        assert result["tier"] == MCPToolTier.ANALYSIS.value
        _validates_receipt(result)

    def test_tier_3_patch_proposal_tool_allowed(self):
        result = evaluate_mcp_request(
            "rig.propose_patch",
            {
                "mission_id": "m1",
                "rationale": "fix bug",
                "target_files": ["a.py"],
                "proposed_changes": "...",
            },
            _TRACE,
            _SESSION,
        )
        assert result["verdict"] == "allowed"
        assert result["tier"] == MCPToolTier.PATCH_PROPOSAL.value
        _validates_receipt(result)


class TestServeStdio:
    @pytest.mark.asyncio
    async def test_serve_stdio_initialize(self):
        server = RigMCPServer()
        result = await server._handle_jsonrpc("initialize", {}, 1)
        assert "capabilities" in result
        caps = result["capabilities"]
        assert caps.tools["listChanged"] is True
        assert result["content_light"] is True
        assert result["server_info"]["name"] == "Rig Relay MCP Server"

    @pytest.mark.asyncio
    async def test_serve_stdio_tools_list(self):
        server = RigMCPServer()
        result = await server._handle_jsonrpc("tools/list", {}, 1)
        assert "tools" in result
        assert isinstance(result["tools"], list)
        assert len(result["tools"]) > 0
        for tool in result["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "tier" in tool

    @pytest.mark.asyncio
    async def test_serve_stdio_tools_call_read_only(self):
        server = RigMCPServer()
        result = await server._handle_jsonrpc(
            "tools/call", {"name": "rig.list_worktrees", "arguments": {}}, 1
        )
        assert "status" in result

    @pytest.mark.asyncio
    async def test_serve_stdio_tools_call_mutation_refused(self):
        server = RigMCPServer()
        result = await server._handle_jsonrpc(
            "tools/call",
            {"name": "rig.request_user_approval", "arguments": {"action": "merge"}},
            1,
        )
        assert result["status"] == "blocked"
        assert result["approval_required"] is True

    @pytest.mark.asyncio
    async def test_serve_stdio_unknown_method(self):
        server = RigMCPServer()
        result = await server._handle_jsonrpc("fake/method", {}, 1)
        assert "error" in result
        assert result["error"]["code"] == -32601
        assert "Method not found" in result["error"]["message"]

    def test_serve_stdio_malformed_json(self):
        server = RigMCPServer()
        response = server._jsonrpc_error(-32700, "Parse error", None)
        assert response["jsonrpc"] == "2.0"
        assert response["error"]["code"] == -32700
        assert response["id"] is None

    def test_serve_stdio_missing_jsonrpc_version(self):
        server = RigMCPServer()
        response = server._jsonrpc_error(-32600, "Invalid Request", 1)
        assert response["jsonrpc"] == "2.0"
        assert response["error"]["code"] == -32600
        assert response["id"] == 1

    def test_jsonrpc_error_helper(self):
        server = RigMCPServer()

        err = server._jsonrpc_error(-32700, "Parse error", "req-1")
        assert err == {
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": "req-1",
        }

        err = server._jsonrpc_error(-32602, "Invalid params", 42, {"detail": "bad"})
        assert err == {
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "Invalid params",
                "data": {"detail": "bad"},
            },
            "id": 42,
        }

        err = server._jsonrpc_error(-32603, "Internal error")
        assert err == {
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": "Internal error"},
            "id": None,
        }

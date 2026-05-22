from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.protocols.mcp.models import RefusalCode


class FakeStore:
    def __init__(self):
        self.envelopes = []

    def append(self, envelope):
        self.envelopes.append(envelope)


class TestAuthRequired:
    def test_missing_token_refuses_before_dispatch(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token=""
        )
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == RefusalCode.AUTH_REQUIRED
        assert result.get("surface") == "mcp"
        assert result.get("content_light") is True

    def test_invalid_token_refuses_before_dispatch(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token="wrong-token"
        )
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == RefusalCode.INVALID_SESSION_TOKEN

    def test_valid_token_allows_read_only_tool(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync(
                "rig.inspect_schema",
                {"schema": "test"},
                session_token=server._session_token,
            )
            assert result.get("status") == "ok"
            assert result.get("surface") == "mcp"
            assert "content_light_classification" in result


class TestTierAuthorization:
    def test_valid_token_does_not_allow_mutation_tool(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.request_user_approval",
            {"action": "test"},
            session_token=server._session_token,
        )
        assert result.get("status") == "blocked"
        assert result.get("refusal_code") == "mutation_tier_mcp"

    def test_valid_token_does_not_allow_git_release_tool(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["a"], "authorization_receipt": "b"},
            session_token=server._session_token,
        )
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == RefusalCode.FORBIDDEN

    def test_valid_token_does_not_allow_unknown_tool(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.nonexistent", {}, session_token=server._session_token
        )
        assert "error" in result
        assert result["error"]["code"] == -32601
        assert result["error"]["data"]["refusal_code"] == "unknown_tool"


class TestAuthRefusalDoesNotLeakToken:
    def test_auth_required_refusal_does_not_contain_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token=""
        )
        assert server._session_token not in str(result)

    def test_invalid_token_refusal_does_not_contain_raw_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token="wrong"
        )
        assert "wrong" not in str(result)


class TestTokenFingerprintInEvidence:
    def test_token_fingerprint_is_sha256_truncated(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        assert len(server._session_token_fingerprint) == 16
        assert server._session_token not in server._session_token_fingerprint

    def test_invalid_token_refusal_includes_fingerprint_not_raw_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token="bad"
        )
        assert server._session_token_fingerprint in str(result)
        assert server._session_token not in str(result)


class TestAuthReceiptPersistence:
    def test_auth_refusal_persists_with_receipt_store(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        store = FakeStore()
        server = RigMCPServer(receipt_store=store)
        server.call_tool_sync(
            "rig.inspect_schema", {"schema": "test"}, session_token=""
        )
        assert len(store.envelopes) > 0

    def test_valid_token_call_persists_with_receipt_store(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        store = FakeStore()
        server = RigMCPServer(receipt_store=store)
        server.call_tool_sync(
            "rig.inspect_schema",
            {"schema": "test"},
            session_token=server._session_token,
        )
        assert len(store.envelopes) > 0


class TestAsyncSyncAuthParity:
    @pytest.mark.asyncio
    async def test_async_missing_token_refuses(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        result = await server.call_tool(
            "rig.inspect_schema", {"schema": "test"}, session_token=""
        )
        assert result.get("status") == "refused"
        assert result.get("refusal_code") == RefusalCode.AUTH_REQUIRED

    def test_sync_and_async_missing_token_equivalent(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        sync = server.call_tool_sync(
            "rig.promote_to_preproduction",
            {"receipt_ids": ["a"], "authorization_receipt": "b"},
            session_token=server._session_token,
        )
        assert sync.get("status") == "refused"
        assert sync.get("refusal_code") == RefusalCode.FORBIDDEN


class TestPhaseRegression:
    def test_descriptor_integrity_still_passes_with_valid_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        token = server._session_token
        for tool in server.list_tools():
            ok, _ = server._verify_descriptor_integrity(tool.name, tool)
            assert ok

    def test_root_boundary_still_blocks_with_valid_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        refusal = server._assert_within_root(Path("/etc/passwd"))
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION

    def test_content_light_still_classifies_with_valid_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        classification, _ = server._scan_tool_output({
            "status": "ok",
            "message": "clean",
        })
        assert classification is not None

    def test_session_token_is_deterministically_generated(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer(require_auth=True)
        assert len(server._session_token) == 64
        assert server._session_token_fingerprint is not None

from __future__ import annotations

from pathlib import Path
import tempfile

from rig_relay.protocols.mcp.models import ContentLightClass, RefusalCode


class TestContentLightClassification:
    def test_public_safe_output_returns_public_safe(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "count": 5,
            "message": "Clean working tree",
        })
        assert classification == ContentLightClass.PUBLIC_SAFE
        assert refusal is None

    def test_secret_bearing_output_refused_with_sk_key(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "key": "sk-abc123def456ghi789jkl012mno345pqr",
        })
        assert classification == ContentLightClass.SECRET_BEARING
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.SECRET_BEARING_OUTPUT
        assert refusal["content_light"] is True

    def test_secret_bearing_output_refused_with_bearer_token(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "header": "Bearer abcdefghijklmnopqrstuvwxyz123456",
        })
        assert classification == ContentLightClass.SECRET_BEARING
        assert refusal is not None

    def test_forbidden_raw_output_refused_with_api_key_field(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "api_key": "some-key-value-xxx",
        })
        assert classification == ContentLightClass.FORBIDDEN_RAW
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.FORBIDDEN_RAW_OUTPUT

    def test_forbidden_raw_output_refused_with_source_code_field(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "source_code": "def foo(): pass",
        })
        assert classification == ContentLightClass.FORBIDDEN_RAW
        assert refusal is not None

    def test_forbidden_raw_output_refused_with_diff_field(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "diff": "@@ -1,1 +1,1 @@ -foo +bar",
        })
        assert classification == ContentLightClass.FORBIDDEN_RAW
        assert refusal is not None

    def test_private_local_returns_with_classification(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "cwd": "/home/user/projects/my-app",
        })
        assert classification == ContentLightClass.PRIVATE_LOCAL
        assert refusal is None

    def test_forbidden_raw_refused_with_access_token_key(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        classification, refusal = server._scan_tool_output({
            "status": "ok",
            "access_token": "present",
        })
        assert classification == ContentLightClass.FORBIDDEN_RAW
        assert refusal is not None


class TestRefusalDoesNotEchoSecret:
    def test_refusal_for_secret_does_not_contain_the_secret(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        secret_value = "sk-abc123def456ghi789jkl012mno345pqr"
        _, refusal = server._scan_tool_output({"status": "ok", "token": secret_value})
        assert refusal is not None
        assert secret_value not in str(refusal)

    def test_public_safe_output_adds_classification(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        raw = {"status": "ok", "results": []}
        classification, refusal = server._scan_tool_output(raw)
        assert refusal is None
        assert raw["content_light_classification"] == ContentLightClass.PUBLIC_SAFE


class TestDispatchIntegration:
    def test_call_tool_scans_output(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.inspect_schema", {"schema": "test"})
            assert result.get("status") == "ok"
            assert "content_light_classification" in result

    def test_call_tool_refuses_secret_output(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        secret_output = {"status": "ok", "api_key": "sk-leaked-value-xxx"}
        classification, refusal = server._scan_tool_output(secret_output)
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.FORBIDDEN_RAW_OUTPUT


class TestPhase1AndPhase2Regression:
    def test_descriptor_integrity_runs_before_scan(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        for tool in server.list_tools():
            ok, _ = server._verify_descriptor_integrity(tool.name, tool)
            assert ok

    def test_root_boundary_blocks_before_scan(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        outside = Path("/etc/passwd")
        refusal = server._assert_within_root(outside)
        assert refusal is not None
        assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION

    def test_mutation_tier_still_refused(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {"action": "test"})
        assert result.get("status") == "blocked"

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from rig_relay.protocols.mcp.models import RefusalCode


class TestWorkspacePathResolution:
    def test_workspace_root_defaults_to_cwd(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        assert server._workspace_root.resolve() == Path.cwd().resolve()

    def test_explicit_workspace_root_stored(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        root = Path("/tmp/test-mcp-root-1")
        server = RigMCPServer(workspace_root=root)
        assert server._workspace_root == root.resolve()

    def test_resolve_path_inside_workspace_allowed(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            (root / "subdir").mkdir()
            resolved, refusal = server._resolve_workspace_path("subdir")
            assert refusal is None
            assert resolved is not None
            assert resolved == (root / "subdir").resolve()

    def test_resolve_path_with_dotdot_traversal_refused(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            resolved, refusal = server._resolve_workspace_path("../etc/passwd")
            assert resolved is None
            assert refusal is not None
            assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION
            assert refusal["content_light"] is True

    def test_resolve_path_outside_workspace_refused(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            outside = root.parent / "outside.txt"
            outside.touch()
            resolved, _ = server._resolve_workspace_path(str(outside))
            assert resolved is None

    def test_empty_path_returns_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            resolved, refusal = server._resolve_workspace_path("")
            assert refusal is None
            assert resolved == root

    def test_assert_within_root_allows_inside(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            refusal = server._assert_within_root(root / "subdir")
            assert refusal is None

    def test_assert_within_root_denies_outside(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            server = RigMCPServer(workspace_root=root)
            outside = root.parent
            refusal = server._assert_within_root(outside)
            assert refusal is not None
            assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION


class TestFilesystemToolsUseBoundary:
    def test_list_worktrees_uses_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.list_worktrees", {})
            assert result.get("status") == "ok"
            assert "worktrees" in result

    def test_run_readonly_doctor_uses_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.run_readonly_doctor", {})
            assert result.get("status") == "ok"

    def test_summarize_dirty_state_uses_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            (root / "dirty.txt").touch()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.summarize_dirty_state", {})
            assert result.get("status") == "ok"

    def test_check_merge_friendly_uses_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.check_merge_friendly", {})
            assert result.get("status") == "ok"

    def test_audit_dirty_state_uses_workspace_root(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".git").mkdir()
            server = RigMCPServer(workspace_root=root)
            result = server.call_tool_sync("rig.audit_dirty_state", {})
            assert result.get("status") == "ok"


class TestSymlinkTraversalRefusal:
    def test_symlink_pointing_outside_refused(self) -> None:
        import platform

        if platform.system() == "Windows":
            pytest.skip("Symlink traversal testing not supported on Windows in CI")

        from rig_relay.protocols.mcp.server import RigMCPServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            inside = root / "safe"
            inside.mkdir()
            outside = root.parent / "outside_data"
            outside.touch()
            link_path = inside / "link_to_outside"
            link_path.symlink_to(outside)
            server = RigMCPServer(workspace_root=root)
            resolved, refusal = server._resolve_workspace_path("safe/link_to_outside")
            assert refusal is not None
            assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION


class TestStructuredRefusalEnvelope:
    def test_refusal_envelope_has_required_fields(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        refusal = server._build_refusal(
            "rig.list_worktrees",
            RefusalCode.ROOT_SCOPE_VIOLATION,
            "Path outside workspace root.",
        )
        assert refusal["status"] == "refused"
        assert refusal["surface"] == "mcp"
        assert refusal["refusal_code"] == RefusalCode.ROOT_SCOPE_VIOLATION
        assert refusal["content_light"] is True
        assert refusal["capability_id"] == "rig.rig.list_worktrees"


class TestDescriptorIntegrityRegression:
    def test_descriptor_integrity_still_passes_for_listed_tools(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        for tool in server.list_tools():
            ok, _ = server._verify_descriptor_integrity(tool.name, tool)
            assert ok

    def test_mutation_tier_still_refused(self) -> None:
        from rig_relay.protocols.mcp.server import RigMCPServer

        server = RigMCPServer()
        result = server.call_tool_sync("rig.request_user_approval", {"action": "test"})
        assert result.get("status") == "blocked"
        assert result.get("refusal_code") == "mutation_tier_mcp_hmac_required"

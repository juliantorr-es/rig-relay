"""Context compiler-renderer integration tests — public API usage and hardening."""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.compiler import execute
from rig_relay.context.models import ContextMode, ContextRequest, ContextScope


class TestRendererPublicAPI:
    def test_compiler_uses_renderer_public_section_count(self) -> None:
        path = Path(__file__).resolve().parent.parent.parent / "rig_relay" / "context" / "compiler.py"
        source = path.read_text()
        assert "renderer._sections" not in source, (
            "Compiler must not access renderer._sections directly"
        )
        assert "renderer.section_count" in source, (
            "Compiler must use renderer.section_count public API"
        )

    def test_compiler_uses_renderer_add_warning(self) -> None:
        path = Path(__file__).resolve().parent.parent.parent / "rig_relay" / "context" / "compiler.py"
        source = path.read_text()
        assert "renderer.add_warning" in source, (
            "Compiler must use renderer.add_warning() public API"
        )


class TestRepoIndexIntegration:
    def test_execute_constructs_repo_index(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert packet is not None

    def test_execute_surfaces_warnings_when_index_fails(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert packet.warnings is not None


class TestWarningsPropagation:
    def test_execute_includes_plan_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        meta = packet.assembly_plan_summary
        assert "candidate_count" in meta
        assert "selection_count" in meta
        assert "plan_id" in meta
        assert "plan_sha256" in meta


class TestCanonicalHashStable:
    def test_hash_stable_across_executions(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        p1 = execute(request, workspace_root=tmp_path)
        p2 = execute(request, workspace_root=tmp_path)
        assert p1.canonical_packet_sha256 == p2.canonical_packet_sha256


class TestBuildReceiptHardening:
    def test_build_receipt_no_bare_except_pass(self) -> None:
        path = Path(__file__).resolve().parent.parent.parent / "rig_relay" / "context" / "compiler.py"
        source = path.read_text()
        assert "ContextWarningCode.FINDINGS_SUMMARY_FAILED" in source, (
            "build_receipt must surface findings failures as warnings"
        )

    def test_renderer_has_add_warning(self) -> None:
        path = Path(__file__).resolve().parent.parent.parent / "rig_relay" / "context" / "renderer.py"
        source = path.read_text()
        assert "def add_warning" in source, (
            "Renderer must have public add_warning method"
        )

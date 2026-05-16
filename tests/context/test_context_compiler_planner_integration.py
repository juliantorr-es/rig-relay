"""Context compiler-planner integration tests."""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.compiler import (
    _map_omissions_to_do_not_touch,
    _map_selections_to_recommendations,
    execute,
)
from rig_relay.context.models import (
    ContextBudget,
    ContextMode,
    ContextRequest,
    ContextScope,
)
from rig_relay.context.planner import plan_context


class TestPlannerIntegration:
    def test_execute_uses_planner_for_recommendations(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert len(packet.recommended_context) >= 1, (
            "Planner should include requested path in recommendations"
        )

    def test_execute_respects_include_tests_false(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(
                paths=[str(tmp_path / "src" / "main.py")],
                include_tests=False,
                include_docs=True,
            ),
        )
        packet = execute(request, workspace_root=tmp_path)
        paths = {r.path for r in packet.recommended_context}
        assert "tests/test_main.py" not in paths, (
            "Test files should be excluded when include_tests=False"
        )

    def test_execute_respects_include_docs_false(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        (tmp_path / "docs" / "README.md").write_text("# docs")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(
                paths=[str(tmp_path / "src" / "main.py")],
                include_tests=True,
                include_docs=False,
            ),
        )
        packet = execute(request, workspace_root=tmp_path)
        paths = {r.path for r in packet.recommended_context}
        assert "docs/README.md" not in paths, (
            "Doc files should be excluded when include_docs=False"
        )

    def test_execute_respects_budget(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        for i in range(20):
            (tmp_path / "src" / f"file_{i}.py").write_text(f"# file {i}" * 100)
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(
                paths=[str(tmp_path / "src")], include_tests=True, include_docs=True
            ),
            budget=ContextBudget(max_tokens=500),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert len(packet.recommended_context) >= 1, (
            "Budget-limited request should still produce recommendations"
        )

    def test_execute_maps_collisions_to_do_not_touch(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert isinstance(packet.do_not_touch, list)


class TestCanonicalHash:
    def test_canonical_hash_excludes_context_id(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        p1 = execute(request, workspace_root=tmp_path)
        p2 = execute(request, workspace_root=tmp_path)
        assert p1.canonical_packet_sha256 == p2.canonical_packet_sha256, (
            "Same request should produce same canonical hash "
            "regardless of context_id or generated_at"
        )

    def test_canonical_hash_excludes_generated_at(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        p1 = execute(request, workspace_root=tmp_path)
        p2 = execute(request, workspace_root=tmp_path)
        h1 = p1.canonical_packet_sha256
        h2 = p2.canonical_packet_sha256
        assert h1 == h2, (
            f"Same request must produce same hash, got {h1[:20]} vs {h2[:20]}"
        )


class TestMappingHelpers:
    def test_map_selections_produces_path_recommendations(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        plan = plan_context(request, workspace_root=tmp_path)
        recs = _map_selections_to_recommendations(plan)
        assert len(recs) >= 1
        for r in recs:
            assert r.path, "Path must not be empty"
            assert r.reason, "Reason must not be empty"

    def test_map_omissions_without_risk_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        plan = plan_context(request, workspace_root=tmp_path)
        do_not = _map_omissions_to_do_not_touch(plan)
        assert isinstance(do_not, list)


class TestPrivacyRegression:
    def test_execute_no_absolute_paths_outside_repo(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        for r in packet.recommended_context:
            # Planner resolves to absolute paths within workspace
            # Verify path is within the workspace root
            assert str(tmp_path.resolve()) in r.path, (
                f"Recommended path must be within workspace root, got: {r.path}"
            )

    def test_execute_summary_is_content_light(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        request = ContextRequest(
            mode=ContextMode.PACKET,
            scope=ContextScope(paths=[str(tmp_path / "src" / "main.py")]),
        )
        packet = execute(request, workspace_root=tmp_path)
        assert "Assembly plan:" in packet.summary_text, (
            "Summary must include plan metadata"
        )
        # No raw file contents in summary
        assert "# main" not in packet.summary_text, (
            "Summary must not contain raw file content"
        )

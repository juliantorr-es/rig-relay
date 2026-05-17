from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIAGRAM_SCHEMA = _REPO_ROOT / "docs" / "schemas" / "rig.diagram.v1.schema.json"
_EXAMPLE_DIAGRAM = (
    _REPO_ROOT / "docs" / "json" / "diagrams" / "desktop_golden_path_flow.v1.json"
)
_PAGE_SCHEMA = _REPO_ROOT / "docs" / "schemas" / "rig.documentation.page.v1.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestDiagramSchema:
    def test_diagram_schema_parses(self) -> None:
        schema = _load_json(_DIAGRAM_SCHEMA)
        assert schema["title"] == "Rig Diagram Specification"
        assert "$id" in schema

    def test_example_diagram_parses_and_validates(self) -> None:
        import jsonschema

        schema = _load_json(_DIAGRAM_SCHEMA)
        data = _load_json(_EXAMPLE_DIAGRAM)
        jsonschema.validate(data, schema)
        assert data["schema_version"] == "rig.diagram.v1"
        assert data["kind"] == "flow"
        assert len(data["nodes"]) == 8
        assert len(data["edges"]) == 7


class TestPageSchemaDiagramRef:
    def test_diagram_ref_accepted_by_page_schema(self) -> None:
        schema = _load_json(_PAGE_SCHEMA)
        section_types = schema["properties"]["sections"]["items"]["properties"]["type"][
            "enum"
        ]
        assert "diagram_ref" in section_types

    def test_diagram_ref_block_with_required_fields(self) -> None:
        import jsonschema

        schema = _load_json(_PAGE_SCHEMA)
        block = {
            "block_id": "test-diag",
            "type": "diagram_ref",
            "diagram_id": "desktop-golden-path-flow",
            "path": "docs/json/diagrams/desktop_golden_path_flow.v1.json",
            "caption": "Desktop Golden Path",
            "fallback_text": "Flow diagram of bridge startup sequence",
        }
        section = {
            "schema_version": "rig.documentation.page.v1",
            "document_id": "test-page",
            "title": "Test Page",
            "sections": [block],
        }
        jsonschema.validate(section, schema)


class TestDiagramRenderer:
    def test_diagram_ref_renders_figure(self) -> None:
        from rig_relay.docs_renderer.diagrams import render_diagram_ref

        block = {
            "block_id": "diag-1",
            "type": "diagram_ref",
            "diagram_id": "desktop-golden-path-flow",
            "path": "docs/json/diagrams/desktop_golden_path_flow.v1.json",
            "caption": "Desktop Golden Path",
            "fallback_text": "Bridge startup flow",
        }
        html = render_diagram_ref(block)
        assert "<figure" in html
        assert "<figcaption>" in html
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in html
        assert 'role="img"' in html

    def test_missing_path_renders_fallback(self) -> None:
        from rig_relay.docs_renderer.diagrams import render_diagram_ref

        block = {
            "block_id": "diag-missing",
            "type": "diagram_ref",
            "diagram_id": "missing-diagram",
            "caption": "Missing",
        }
        html = render_diagram_ref(block)
        assert "diagram-missing" in html
        assert "Missing diagram path" in html

    def test_unsupported_kind_renders_placeholder(self) -> None:

        # We can't easily test unsupported kind without a file;
        # test the placeholder function directly
        from rig_relay.docs_renderer.diagrams import _placeholder

        spec = {"kind": "state_machine", "title": "My State Machine"}
        html = _placeholder(spec, "test", "Caption", "Fallback")
        assert "diagram-unsupported" in html
        assert "Unsupported diagram kind" in html
        assert "state_machine" in html


class TestDataSources:
    def test_json_loader_loads_dict(self) -> None:
        from rig_relay.docs_renderer.data_sources import load_json_data

        result = load_json_data("docs/json/diagrams/desktop_golden_path_flow.v1.json")
        assert isinstance(result, dict)
        assert result["kind"] == "flow"

    def test_csv_loader_treats_values_as_strings(self) -> None:
        import tempfile

        from rig_relay.docs_renderer.data_sources import load_csv_data

        tmp_dir = Path(tempfile.mkdtemp(dir=_REPO_ROOT))
        try:
            csv_path = tmp_dir / "test.csv"
            csv_path.write_text("name,count\nAlice,10\nBob,20\n")
            rows = load_csv_data(str(csv_path.relative_to(_REPO_ROOT)))
            assert len(rows) == 2
            assert all(isinstance(v, str) for row in rows for v in row.values())
        finally:
            import shutil

            shutil.rmtree(tmp_dir)

    def test_remote_paths_rejected(self) -> None:
        from rig_relay.docs_renderer.data_sources import _is_safe_relative

        assert not _is_safe_relative("https://evil.com/data.json")
        assert not _is_safe_relative("/etc/passwd")
        assert not _is_safe_relative("../outside/data.json")

    def test_generated_html_paths_rejected(self) -> None:
        from rig_relay.docs_renderer.data_sources import _is_safe_relative

        assert not _is_safe_relative("docs/pages/some-page.html")
        assert not _is_safe_relative("docs/search-index.json")
        assert not _is_safe_relative("some-file.html")


class TestDiagramKinds:
    def test_state_machine_renders_svg(self) -> None:
        from rig_relay.docs_renderer.diagrams import render_diagram_ref

        block = {
            "block_id": "sm-1",
            "type": "diagram_ref",
            "diagram_id": "websocket-security-states",
            "path": "docs/json/diagrams/websocket_security_states.v1.json",
            "caption": "WebSocket States",
        }
        html = render_diagram_ref(block)
        assert "<figure" in html
        assert "<svg" in html
        assert "state_machine" in html or 'role="img"' in html

    def test_timeline_renders_svg(self) -> None:
        from rig_relay.docs_renderer.diagrams import _render_timeline_svg

        spec = {
            "kind": "timeline",
            "title": "Test Timeline",
            "nodes": [
                {"id": "1", "label": "Start", "status": "completed"},
                {"id": "2", "label": "Middle", "status": "active"},
                {"id": "3", "label": "End", "status": "pending"},
            ],
        }
        svg = _render_timeline_svg(spec, None)
        assert "<svg" in svg
        assert "<circle" in svg

    def test_matrix_renders_svg(self) -> None:
        from rig_relay.docs_renderer.diagrams import _render_matrix_svg

        spec = {
            "kind": "matrix",
            "title": "Test Matrix",
            "columns": ["A", "B"],
            "rows": [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}],
        }
        svg = _render_matrix_svg(spec, None)
        assert "<svg" in svg
        assert "<rect" in svg

    def test_dependency_graph_renders_svg(self) -> None:
        from rig_relay.docs_renderer.diagrams import _render_dependency_graph_svg

        spec = {
            "kind": "dependency_graph",
            "title": "Test Deps",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
        }
        svg = _render_dependency_graph_svg(spec, None)
        assert "<svg" in svg

    def test_all_kinds_have_renderers(self) -> None:
        from rig_relay.docs_renderer.diagrams import _DIAGRAM_RENDERERS

        expected = {
            "flow",
            "state_machine",
            "timeline",
            "matrix",
            "dependency_graph",
            "risk_map",
            "architecture_map",
        }
        assert set(_DIAGRAM_RENDERERS.keys()) == expected

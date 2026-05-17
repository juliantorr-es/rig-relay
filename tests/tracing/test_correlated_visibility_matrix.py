from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = (
    REPO_ROOT / "docs" / "json" / "tracing" / "correlated_visibility_matrix.v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.tracing.correlated_visibility_matrix.v1.schema.json"
)

REQUIRED_PATH_IDS = [
    "desktop_bridge_startup",
    "websocket_auth_projection",
    "frontend_breadcrumbs",
    "websocket_security_rejections",
    "context_assembly",
    "code_schema_routing",
    "agent_loop_turn",
    "tool_execution",
    "worktree_mutation",
    "static_docs_render",
    "security_threat_model_release_gates",
    "session_lifecycle",
]


@pytest.fixture
def matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def paths_by_id(matrix: dict) -> dict[str, dict]:
    return {p["path_id"]: p for p in matrix["critical_paths"]}


class TestCorrelatedVisibilityMatrixExists:
    def test_matrix_json_exists(self) -> None:
        assert MATRIX_PATH.exists(), f"Missing {MATRIX_PATH}"

    def test_matrix_json_parses(self, matrix: dict) -> None:
        assert matrix["schema_version"] == "rig.tracing.correlated_visibility_matrix.v1"
        assert "critical_paths" in matrix
        assert isinstance(matrix["critical_paths"], list)
        assert len(matrix["critical_paths"]) > 0

    def test_matrix_schema_exists(self) -> None:
        assert SCHEMA_PATH.exists(), f"Missing {SCHEMA_PATH}"


class TestRequiredCriticalPaths:
    @pytest.mark.parametrize("path_id", REQUIRED_PATH_IDS)
    def test_required_path_present(
        self, paths_by_id: dict[str, dict], path_id: str
    ) -> None:
        assert path_id in paths_by_id, (
            f"Required critical path '{path_id}' missing from visibility matrix"
        )


class TestCriticalPathStructure:
    def test_every_path_has_start_event(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            assert path.get("required_start_event"), (
                f"Path '{path['path_id']}' missing required_start_event"
            )

    def test_every_path_has_success_event(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            assert path.get("required_success_event"), (
                f"Path '{path['path_id']}' missing required_success_event"
            )

    def test_every_path_has_correlation_fields(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            fields = path.get("required_correlation_fields", [])
            assert isinstance(fields, list) and len(fields) > 0, (
                f"Path '{path['path_id']}' missing required_correlation_fields"
            )

    def test_every_path_has_visibility_status(self, matrix: dict) -> None:
        valid = {"complete", "partial", "missing", "unknown"}
        for path in matrix["critical_paths"]:
            status = path.get("visibility_status")
            assert status, f"Path '{path['path_id']}' missing visibility_status"
            assert status in valid, (
                f"Path '{path['path_id']}' invalid visibility_status: {status}"
            )

    def test_every_path_has_owner_area(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            assert path.get("owner_area"), (
                f"Path '{path['path_id']}' missing owner_area"
            )


class TestReleaseBlockers:
    def test_release_blocker_paths_have_recommended_fix(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            if path.get("release_blocker"):
                assert path.get("recommended_fix"), (
                    f"Release-blocking path '{path['path_id']}' missing recommended_fix"
                )

    def test_release_blocker_paths_are_not_complete(self, matrix: dict) -> None:
        for path in matrix["critical_paths"]:
            if path.get("release_blocker"):
                assert path.get("visibility_status") != "complete", (
                    f"Release-blocking path '{path['path_id']}' marked complete"
                )

    def test_summary_matches_paths(self, matrix: dict) -> None:
        summary = matrix.get("summary", {})
        paths = matrix["critical_paths"]
        assert summary.get("complete", 0) == sum(
            1 for p in paths if p["visibility_status"] == "complete"
        )
        assert summary.get("partial", 0) == sum(
            1 for p in paths if p["visibility_status"] == "partial"
        )
        assert summary.get("missing", 0) == sum(
            1 for p in paths if p["visibility_status"] == "missing"
        )
        assert summary.get("release_blockers", 0) == sum(
            1 for p in paths if p.get("release_blocker")
        )


class TestSpecificPaths:
    def test_desktop_bridge_has_handshake_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["desktop_bridge_startup"]["required_correlation_fields"]
        assert "handshake_id" in fields

    def test_websocket_auth_has_connection_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["websocket_auth_projection"]["required_correlation_fields"]
        assert "connection_id" in fields

    def test_frontend_breadcrumbs_has_frontend_session_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["frontend_breadcrumbs"]["required_correlation_fields"]
        assert "frontend_session_id" in fields

    def test_websocket_security_has_refusal_events(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        refusal = paths_by_id["websocket_security_rejections"].get(
            "required_refusal_events", []
        )
        assert len(refusal) >= 4, "Expected at least 4 refusal event types"

    def test_tool_execution_has_tool_batch_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["tool_execution"]["required_correlation_fields"]
        assert "tool_batch_id" in fields

    def test_code_schema_routing_has_schema_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["code_schema_routing"]["required_correlation_fields"]
        assert "schema_id" in fields

    def test_static_docs_render_has_document_id(
        self, paths_by_id: dict[str, dict]
    ) -> None:
        fields = paths_by_id["static_docs_render"]["required_correlation_fields"]
        assert "document_id" in fields

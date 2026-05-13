"""Tests for the desktop projection pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from rig_relay.desktop.projection import (
    _load_json as relay_load_json,
    _load_markdown_summary as relay_load_markdown_summary,
    build_projection as relay_build_projection,
)
from scripts.rig_relay_desktop_projection import (
    _load_json,
    _load_markdown_summary,
    build_projection,
)


class TestProjectionBuilder:
    """Projection builder behaves correctly with real and missing artifacts."""

    def test_build_projection_returns_dict(self, projection_from_build) -> None:
        assert isinstance(projection_from_build, dict)
        assert (
            projection_from_build["schema_version"] == "rig.relay.desktop_projection.v1"
        )

    def test_build_projection_has_required_keys(self, projection_from_build) -> None:
        required = [
            "schema_version",
            "generated_at",
            "app_version",
            "source_status",
            "current_state",
            "queue",
            "dataset",
            "semantic_snippets",
            "telemetry_bundle",
            "update",
            "warnings",
            "read_only_actions",
        ]
        for key in required:
            assert key in projection_from_build, f"Missing key: {key}"

    def test_build_projection_no_invented_fields(self, projection_from_build) -> None:
        """All fields must come from actual artifact schemas, never invented."""
        # Categories should only contain fields from real schemas
        forbidden = [
            "workspace_header",
            "proposal_lifecycle",
            "audit_trail",
            "integrity_status",
            "chat_sessions",
            "composer_state",
            "job_store",
            "worktree_executor",
            "intake_auth",
        ]
        for cat in (
            "current_state",
            "queue",
            "dataset",
            "semantic_snippets",
            "telemetry_bundle",
            "update",
        ):
            data = projection_from_build.get(cat, {})
            for key in data:
                assert key not in forbidden, f"Forbidden field '{key}' in '{cat}'"

    def test_missing_source_returns_available_false(
        self, projection_from_build
    ) -> None:
        """Missing sources return available: false instead of crashing."""
        for source in ("current_state", "queue", "telemetry_bundle"):
            if not projection_from_build["source_status"].get(source):
                entry = projection_from_build[source]
                assert entry == {"available": False} or (
                    isinstance(entry, dict) and entry.get("available") is False
                )

    def test_warnings_for_missing_sources(self, projection_from_build) -> None:
        """Warnings are emitted for unavailable data sources."""
        missing = [
            k for k, v in projection_from_build["source_status"].items() if not v
        ]
        for source in missing:
            assert any(source in w for w in projection_from_build["warnings"]), (
                f"No warning for missing source '{source}'"
            )

    def test_read_only_actions_are_defined(self, projection_from_build) -> None:
        assert isinstance(projection_from_build["read_only_actions"], list)
        assert len(projection_from_build["read_only_actions"]) > 0

    def test_alpha_label_is_boolean(self, projection_from_build) -> None:
        assert isinstance(projection_from_build["alpha_label"], bool)

    def test_source_status_is_bool_dict(self, projection_from_build) -> None:
        assert isinstance(projection_from_build["source_status"], dict)
        for v in projection_from_build["source_status"].values():
            assert isinstance(v, bool)

    def test_available_dataset_has_expected_fields(
        self, tmp_path, sample_export_manifest
    ) -> None:
        """When dataset is available, it has the expected field names."""
        build_root = tmp_path / ".build" / "rig-relay"
        derived_dir = build_root / "derived"
        derived_dir.mkdir(parents=True)
        (derived_dir / "export_manifest.json").write_text(
            json.dumps(sample_export_manifest)
        )
        projection = build_projection(build_root=build_root)
        ds = projection["dataset"]
        assert ds["available"] is True
        assert ds["coordination_rows"] == 416
        assert ds["tool_failure_rows"] == 129
        assert ds["datasets_generated"] is True

    def test_missing_export_manifest_returns_available_false(self, tmp_path) -> None:
        build_root = tmp_path / ".build" / "rig-relay"
        build_root.mkdir(parents=True)
        projection = build_projection(build_root=build_root)
        assert projection["dataset"]["available"] is False


class TestLoadFunctions:
    """Low-level loader functions handle edge cases."""

    def test_load_json_missing_file(self, tmp_path) -> None:
        result = _load_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_json_invalid_json(self, tmp_path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json")
        result = _load_json(p)
        assert result is None

    def test_load_json_valid(self, tmp_path) -> None:
        p = tmp_path / "good.json"
        p.write_text('{"hello": "world"}')
        result = _load_json(p)
        assert result == {"hello": "world"}

    def test_load_markdown_summary_missing_file(self, tmp_path) -> None:
        result = _load_markdown_summary(tmp_path / "nonexistent.md")
        assert result is None

    def test_load_markdown_summary_empty(self, tmp_path) -> None:
        p = tmp_path / "empty.md"
        p.write_text("")
        result = _load_markdown_summary(p)
        assert result is None

    def test_load_markdown_summary_executive_table(self, tmp_path) -> None:
        """Parse the Executive Summary table only."""
        md = """# Dataset Summary

## Executive Summary

| Metric | Value |
|---|---|
| Sessions Observed | 71 |
| Coordination Events | 416 |
| Tool Calls | 1672 |

## Per-Dataset Counts

| Dataset | Rows | Strict |
|---|---|---|
| coordination | 416 | No |
| tool_failure | 129 | No |
"""
        p = tmp_path / "dataset-summary.md"
        p.write_text(md)
        result = _load_markdown_summary(p)
        assert result is not None
        assert result.get("exec_sessions_observed") == 71
        assert result.get("exec_coordination_events") == 416
        assert result.get("exec_tool_calls") == 1672

    def test_load_markdown_summary_non_numeric_ignored(self, tmp_path) -> None:
        """Non-numeric values in the Executive Summary are ignored."""
        md = """## Executive Summary

| Metric | Value |
|---|---|
| Total Rows | 1200 |
| Status | healthy |
| Mode | strict |
"""
        p = tmp_path / "dataset-summary.md"
        p.write_text(md)
        result = _load_markdown_summary(p)
        assert result is not None
        assert result.get("exec_total_rows") == 1200
        assert "exec_status" not in result
        assert "exec_mode" not in result

    def test_load_markdown_summary_only_exec_table(self, tmp_path) -> None:
        """Ignores subsequent tables with non-numeric values."""
        md = """## Executive Summary

| Metric | Value |
|---|---|
| Tool Calls | 1672 |

## Config Table

| Setting | Value |
|---|---|
| Mode | auto |
| Verbose | yes |
"""
        p = tmp_path / "dataset-summary.md"
        p.write_text(md)
        result = _load_markdown_summary(p)
        assert result is not None
        assert result.get("exec_tool_calls") == 1672
        assert len(result) == 1  # Only the numeric field


class TestProjectionContentSafeguards:
    """Projection must not contain raw content, prompts, or secrets."""

    FORBIDDEN_PATTERNS: ClassVar[list[str]] = [
        "sk-",  # OpenAI key fragment
        "ghp_",  # GitHub PAT fragment
        "bearer ",  # Bearer token
        "-----BEGIN",  # PEM key
        "model_output",
        "raw_prompt",
        "stdout_body",
        "stderr_body",
        "file_contents",
    ]

    def test_no_forbidden_content_in_projection(self, projection_from_build) -> None:
        serialized = json.dumps(projection_from_build)
        for pattern in self.FORBIDDEN_PATTERNS:
            assert pattern.lower() not in serialized.lower(), (
                f"Forbidden pattern '{pattern}' found in projection"
            )

    def test_projection_contains_only_hashes_not_full_content(
        self, projection_from_build
    ) -> None:
        """SHA256 hashes in projection should be hashes, not full file contents."""
        bundle = projection_from_build.get("telemetry_bundle", {})
        if bundle.get("available") and bundle.get("bundle_sha256"):
            sha = bundle["bundle_sha256"]
            assert sha.startswith("sha256:") or len(sha) == 64, (
                f"bundle_sha256 should be a hash, got: {sha[:50]}..."
            )

    def test_projection_no_raw_paths(self, projection_from_build) -> None:
        """No raw private paths in projection."""
        serialized = json.dumps(projection_from_build)
        # Home directory paths should not appear
        assert "/Users/" not in serialized


class TestDesktopCockpit:
    """Desktop cockpit script uses projection builder correctly."""

    def test_cockpit_dry_run_uses_projection_builder(self) -> None:
        """Running with --dry-run should call build_projection successfully."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/rig_relay_desktop_cockpit.py", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent.parent,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Projection summary:" in result.stdout
        assert "Data sources:" in result.stdout
        assert "Available actions:" in result.stdout

    def test_cockpit_exposes_projection_api(self) -> None:
        """Verify the API class exposes the correct read-only methods."""
        from scripts.rig_relay_desktop_projection import READ_ONLY_ACTIONS

        expected_actions = [
            "refresh_projection",
            "view_current_state",
            "view_dataset_summary",
            "view_semantic_snippets",
            "view_telemetry_bundle",
            "view_update_status",
            "view_queue_plan",
        ]
        for action in expected_actions:
            assert action in READ_ONLY_ACTIONS, f"Missing action: {action}"

    def test_frontend_assets_exist(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        index = repo_root / "frontend" / "desktop" / "index.html"
        styles = repo_root / "frontend" / "desktop" / "styles.css"
        app_js = repo_root / "frontend" / "desktop" / "app.js"
        assert index.is_file(), f"Missing: {index}"
        assert styles.is_file(), f"Missing: {styles}"
        assert app_js.is_file(), f"Missing: {app_js}"


class TestRelayNativeImports:
    """Verify every public function from the Relay-native module is reachable and works identically."""

    def test_relay_build_projection_returns_same_structure(self, tmp_path) -> None:

        build_root = tmp_path / ".build" / "rig-relay"
        build_root.mkdir(parents=True)
        p1 = build_projection(build_root=build_root)
        p2 = relay_build_projection(build_root=build_root)
        # Compare non-temporal fields (generated_at differs between calls)
        for key in (
            "schema_version",
            "app_version",
            "alpha_label",
            "source_status",
            "read_only_actions",
        ):
            assert p1[key] == p2[key], f"Mismatch in key: {key}"
        assert p2["schema_version"] == "rig.relay.desktop_projection.v1"

    def test_relay_load_json_same_behavior(self, tmp_path) -> None:
        p = tmp_path / "test.json"
        p.write_text('{"a": 1}')
        assert _load_json(p) == relay_load_json(p)
        assert relay_load_json(tmp_path / "nonexistent.json") is None

    def test_relay_load_markdown_summary_same_behavior(self, tmp_path) -> None:
        md = "## Executive Summary\n\n| Metric | Value |\n|---|---|\n| Tool Calls | 42 |\n"
        p = tmp_path / "summary.md"
        p.write_text(md)
        assert _load_markdown_summary(p) == relay_load_markdown_summary(p)
        assert relay_load_markdown_summary(tmp_path / "missing.md") is None

    def test_relay_module_imports_all_read_only_actions(self) -> None:
        from rig_relay.desktop.projection import READ_ONLY_ACTIONS as relay_actions
        from scripts.rig_relay_desktop_projection import (
            READ_ONLY_ACTIONS as script_actions,
        )

        assert relay_actions == script_actions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_export_manifest() -> dict:
    return {
        "exported_at": "2026-05-13T16:00:26.921662+00:00",
        "row_counts": {
            "cross_session_coordination_dataset": 416,
            "tool_failure_patterns_dataset": 129,
            "provider_task_performance_dataset": 1239,
            "findings_dataset": 4,
            "artifact_reuse_dataset": 94,
            "checkpoint_eval_dataset": 0,
        },
        "skipped_event_count": 0,
        "strict": False,
        "datasets_generated": True,
    }


@pytest.fixture
def projection_from_build() -> dict:
    """Build a projection from the actual .build/rig-relay directory."""
    return build_projection()

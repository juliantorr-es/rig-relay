from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTER_SCRIPT = _REPO_ROOT / "scripts" / "rig_relay_select_code_schemas.py"
_REGISTRY = _REPO_ROOT / "docs" / "json" / "code_schemas" / "index.v1.json"
_CODE_SCHEMA_DIR = _REPO_ROOT / "docs" / "json" / "code_schemas"


def _run_router(*args: str, registry_path: str = "") -> dict:
    cmd = [sys.executable, str(_ROUTER_SCRIPT), *args, "--format", "json"]
    if registry_path:
        cmd.extend(["--registry-path", registry_path])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=_REPO_ROOT)
    assert result.returncode == 0, f"router failed: {result.stderr}"
    return json.loads(result.stdout)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestCodeSchemaRouterLoads:
    def test_router_loads_registry_and_active_schemas(self) -> None:
        result = _run_router("--prompt", "irrelevant prompt no match")
        assert result["total_active"] == 5
        assert result["total_loaded"] == 5
        assert result["total_selected"] == 0
        assert len(result["reported_schemas"]) == 5
        assert len(result["selected_schemas"]) == 0

    def test_explicit_schema_id_mention_selects_that_schema(self) -> None:
        result = _run_router("--prompt", "use tool_batch_execution.v1 for this fix")
        selected = result["selected_schemas"]
        assert len(selected) >= 1
        assert selected[0]["schema_id"] == "tool_batch_execution.v1"
        assert selected[0]["score"] >= 10

    def test_frontend_breadcrumb_prompt_selects_frontend_trace_endpoint(self) -> None:
        result = _run_router(
            "--prompt",
            "frontend breadcrumb is broken POST /ws returns 405",
            "--changed-file",
            "frontend/desktop/js/utils.js",
        )
        selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
        assert "frontend_trace_endpoint.v1" in selected_ids

    def test_desktop_golden_path_prompt_selects_desktop_golden_path(self) -> None:
        result = _run_router(
            "--prompt", "desktop golden path WebSocket auth projection rendered status"
        )
        selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
        assert "desktop_golden_path_trace.v1" in selected_ids

    def test_markdown_migration_prompt_selects_json_documentation_migration(
        self,
    ) -> None:
        result = _run_router(
            "--prompt", "markdown to json migration of our documentation"
        )
        selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
        assert "json_documentation_migration.v1" in selected_ids

    def test_tool_batch_prompt_selects_tool_batch_execution(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("execute_tool_batch failed\n")
            tb_path = f.name
        try:
            result = _run_router(
                "--prompt", "fix tool batch", "--traceback-file", tb_path
            )
            selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
            assert "tool_batch_execution.v1" in selected_ids
        finally:
            Path(tb_path).unlink()

    def test_transport_reducer_prompt_selects_frontend_transport_state_reducer(
        self,
    ) -> None:
        result = _run_router(
            "--prompt", "wsConnected status bar transport reducer broken"
        )
        selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
        assert "frontend_transport_state_reducer.v1" in selected_ids


class TestCodeSchemaRouterExclusions:
    def test_generated_html_paths_excluded_from_context_packs(self) -> None:
        result = _run_router(
            "--prompt",
            "frontend trace endpoint",
            "--changed-file",
            "frontend/desktop/js/utils.js",
        )
        for schema in result["selected_schemas"]:
            ctx = schema.get("context_pack", {})
            for key in ("include_files", "include_docs", "include_schemas"):
                for item in ctx.get(key, []):
                    assert "/pages/" not in item
                    assert not item.endswith(".html")
                    assert "docs/assets/" not in item
                    assert "collections/" not in item

    def test_docs_pages_glob_in_exclude_patterns(self) -> None:
        result = _run_router("--prompt", "desktop golden path trace")
        for schema in result["selected_schemas"]:
            exclude = schema.get("context_pack", {}).get("exclude_patterns", [])
            assert "docs/pages/**" in exclude or "**/*.html" in exclude


class TestCodeSchemaRouterAuthority:
    def test_untrusted_schema_not_selected_as_authoritative(self) -> None:
        result = _run_router("--prompt", "irrelevant no match")
        for schema in result["selected_schemas"]:
            assert schema.get("authority", {}).get("trusted", False)
        for warning in result.get("warnings", []):
            if (
                "not selected as authoritative" in warning.lower()
                or "authority check failed" in warning.lower()
            ):
                assert "untrusted" in warning.lower() or "authority" in warning.lower()

    def test_source_hash_mismatch_prevents_authoritative_selection(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            registry_path = tmp / "index.v1.json"

            entries_copy = []
            for entry in _load_json(_REGISTRY)["entries"]:
                src_path = _REPO_ROOT / entry["path"]
                src_data = _load_json(src_path)
                basename = entry["path"].split("/")[-1]
                dst_path = tmp / basename
                src_data["authority"]["source_hash"] = "sha256:deadbeef"
                dst_path.write_text(json.dumps(src_data, indent=2))
                entries_copy.append({**entry, "path": str(dst_path)})

            registry_data = {
                "schema_version": "rig.code_schema.index.v1",
                "title": "Test",
                "summary": "Test",
                "generated_at": "2026-05-16",
                "entries": entries_copy,
            }
            registry_path.write_text(json.dumps(registry_data, indent=2))

            result = _run_router(
                "--prompt",
                "frontend trace endpoint breadcrumb",
                registry_path=str(registry_path),
            )
            selected_ids = [s["schema_id"] for s in result["selected_schemas"]]
            assert len(selected_ids) == 0
            assert any("source_hash mismatch" in w for w in result.get("warnings", []))


class TestCodeSchemaRouterOutput:
    def test_selection_output_includes_validation_commands(self) -> None:
        result = _run_router("--prompt", "frontend trace endpoint breadcrumb")
        for schema in result["selected_schemas"]:
            assert schema.get("validation_commands")

    def test_selection_output_includes_matched_signals_and_scores(self) -> None:
        result = _run_router(
            "--prompt",
            "frontend trace endpoint",
            "--changed-file",
            "frontend/desktop/js/utils.js",
        )
        for schema in result["selected_schemas"]:
            assert isinstance(schema.get("score"), int)
            assert schema.get("matched_signals")

    def test_no_token_or_secret_fields_in_selection_output(self) -> None:
        result = _run_router(
            "--prompt",
            "frontend trace endpoint breadcrumb",
            "--changed-file",
            "rig_relay/desktop/bridge_server.py",
        )
        output_json = json.dumps(result)
        assert (
            "token" not in output_json.lower()
            or "no token values" in output_json.lower()
        )
        for banned in ["TOKEN", "SECRET", "PASSWORD", "API_KEY"]:
            for schema in result["selected_schemas"]:
                cp_json = json.dumps(schema.get("context_pack", {}))
                assert banned.lower() not in cp_json.lower()

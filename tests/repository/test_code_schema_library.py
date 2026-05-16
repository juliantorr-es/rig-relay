"""Code schema library tests — parsing, registry linkage, authority, rendering."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON = _REPO_ROOT / "docs" / "json"
_DOCS_SCHEMAS = _REPO_ROOT / "docs" / "schemas"
_SITE_MANIFEST = _DOCS_JSON / "site_manifest.v1.json"
_REGISTRY = _DOCS_JSON / "code_schemas" / "index.v1.json"
_CODE_SCHEMA_DIR = _DOCS_JSON / "code_schemas"
_DOCS_OUT = _REPO_ROOT / "docs"
_RENDERER = _REPO_ROOT / "scripts" / "render_static_docs.py"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _git_ls_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=_REPO_ROOT
    )
    return set(result.stdout.strip().split("\n"))


def _schema_files() -> list[Path]:
    return sorted(_CODE_SCHEMA_DIR.glob("*.json"))


def _is_plan_schema(data: dict) -> bool:
    return str(data.get("schema_version", "")).startswith("rig.code_schema.plan.v")


def _is_registry(path: Path) -> bool:
    return path == _REGISTRY


def _active_schema_files() -> list[Path]:
    return [
        path
        for path in _schema_files()
        if not _is_registry(path) and not _is_plan_schema(_load_json(path))
    ]


class TestCodeSchemaFilesParse:
    def test_all_code_schema_files_parse(self) -> None:
        for path in _schema_files():
            try:
                _load_json(path)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{path.name}: invalid JSON — {exc}")

    def test_all_code_schema_files_have_required_top_level_fields(self) -> None:
        for path in _schema_files():
            data = _load_json(path)
            if _is_registry(path):
                for field in {"schema_version", "title", "summary", "generated_at", "entries"}:
                    assert field in data, f"{path.name}: missing {field}"
                continue
            if _is_plan_schema(data):
                for field in {
                    "schema_version",
                    "title",
                    "summary",
                    "status",
                    "steps",
                    "selection_signals",
                    "authority_rules",
                    "context_packing_rules",
                    "validation_surface",
                }:
                    assert field in data, f"{path.name}: missing {field}"
                continue

            required = {
                "schema_id",
                "title",
                "change_kind",
                "status",
                "authority",
                "model_facing_summary",
                "context_pack",
            }
            for field in required:
                assert field in data, f"{path.name}: missing {field}"


class TestCodeSchemaRegistry:
    def test_registry_parses(self) -> None:
        data = _load_json(_REGISTRY)
        assert data["schema_version"] == "rig.code_schema.index.v1"
        assert isinstance(data.get("entries", []), list)
        assert len(data.get("entries", [])) == 5

    def test_registry_entries_point_to_existing_files(self) -> None:
        data = _load_json(_REGISTRY)
        for entry in data.get("entries", []):
            path = _REPO_ROOT / entry["path"]
            assert path.is_file(), f"missing schema file: {entry['path']}"

    def test_registry_only_lists_active_schemas(self) -> None:
        data = _load_json(_REGISTRY)
        for entry in data.get("entries", []):
            assert entry["status"] == "active"

    def test_registry_entries_have_authority_markers(self) -> None:
        data = _load_json(_REGISTRY)
        required = {"authority_trusted", "review_status", "last_reviewed_at"}
        for entry in data.get("entries", []):
            for field in required:
                assert field in entry, f"{entry['schema_id']}: missing {field}"


class TestCodeSchemaAuthority:
    def test_trusted_entries_have_source_metadata(self) -> None:
        for path in _active_schema_files():
            data = _load_json(path)
            authority = data["authority"]
            if authority.get("trusted"):
                assert authority.get("source_path"), f"{path.name}: missing source_path"
                assert authority.get(
                    "review_status"
                ), f"{path.name}: missing review_status"
                source_path = _REPO_ROOT / authority["source_path"]
                assert source_path.is_file(), f"{path.name}: missing source_path file"
                expected = f"sha256:{sha256(source_path.read_bytes()).hexdigest()}"
                assert (
                    authority.get("source_hash") == expected
                ), f"{path.name}: source_hash mismatch"
                assert authority.get("source_hash") != "sha256:placeholder"

    def test_active_schemas_have_tests_or_validation(self) -> None:
        for path in _active_schema_files():
            data = _load_json(path)
            assert data.get("schema_version") == "rig.code_schema.v1"
            assert data.get("required_tests") or data.get(
                "validation_commands"
            ), f"{path.name}: missing tests or validation commands"
            assert data.get("required_invariants"), f"{path.name}: missing invariants"
            assert data.get("context_pack"), f"{path.name}: missing context_pack"
            assert data.get("validation_commands"), f"{path.name}: missing validation commands"

    def test_no_schema_sources_generated_docs_html(self) -> None:
        for path in _active_schema_files():
            data = _load_json(path)
            ctx = data.get("context_pack", {})
            for key in ("include_files", "include_docs", "include_schemas"):
                for item in ctx.get(key, []):
                    assert "/pages/" not in item
                    assert not item.endswith(".html")

    def test_active_schema_ids_are_unique(self) -> None:
        ids = [_load_json(path)["schema_id"] for path in _active_schema_files()]
        assert len(ids) == len(set(ids))

    def test_plan_schema_is_not_active(self) -> None:
        plan = _load_json(_CODE_SCHEMA_DIR / "context_assembler_integration_plan.v1.json")
        assert plan["schema_version"] == "rig.code_schema.plan.v1"
        assert plan.get("status") == "active"
        assert "authority" not in plan
        assert "required_tests" not in plan
        assert "validation_commands" not in plan


class TestCodeSchemaRenderer:
    def test_renderer_includes_code_schema_docs(self) -> None:
        site = _load_json(_SITE_MANIFEST)
        code_schema_collection = next(
            c for c in site.get("collections", []) if c["collection_id"] == "code-schemas"
        )
        assert len(code_schema_collection.get("documents", [])) >= 5
        assert all(doc["document_id"] for doc in code_schema_collection.get("documents", []))

    def test_renderer_outputs_code_schema_pages(self) -> None:
        assert _DOCS_OUT.joinpath("pages", "frontend-trace-endpoint.html").is_file()
        assert _DOCS_OUT.joinpath("pages", "desktop-golden-path-trace.html").is_file()
        assert _DOCS_OUT.joinpath("pages", "json-documentation-migration.html").is_file()
        assert _DOCS_OUT.joinpath("pages", "tool-batch-execution.html").is_file()
        assert _DOCS_OUT.joinpath("pages", "frontend-transport-state-reducer.html").is_file()

    def test_renderer_script_is_present(self) -> None:
        assert _RENDERER.is_file()


class TestCodeSchemaGitTracking:
    def test_code_schema_files_are_tracked_or_present(self) -> None:
        tracked = _git_ls_files()
        for path in _schema_files():
            rel = str(path.relative_to(_REPO_ROOT))
            assert rel in tracked or path.is_file(), f"{rel} not tracked"

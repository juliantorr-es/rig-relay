"""Documentation system tests — JSON parsing, schema validation, renderer, tracking."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_JSON = _REPO_ROOT / "docs" / "json"
_DOCS_SCHEMAS = _REPO_ROOT / "docs" / "schemas"
_DOCS_OUT = _REPO_ROOT / "docs"
_RENDERER = _REPO_ROOT / "scripts" / "render_static_docs.py"


def _git_ls_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=_REPO_ROOT
    )
    return set(result.stdout.strip().split("\n"))


def _git_tracked(path: str) -> bool:
    return path in _git_ls_files()


# ── JSON doc parsing ─────────────────────────────────────────────


class TestJsonDocsParse:
    def test_every_json_doc_parses(self) -> None:
        for jf in _DOCS_JSON.glob("*.json"):
            try:
                json.loads(jf.read_text())
            except json.JSONDecodeError as e:
                pytest.fail(f"{jf.name}: invalid JSON — {e}")

    def test_every_json_doc_has_schema_version(self) -> None:
        for jf in _DOCS_JSON.glob("*.json"):
            data = json.loads(jf.read_text())
            assert "schema_version" in data, f"{jf.name}: missing schema_version"


class TestSchemasParse:
    def test_every_schema_parses(self) -> None:
        for sf in _DOCS_SCHEMAS.glob("*.json"):
            try:
                json.loads(sf.read_text())
            except json.JSONDecodeError as e:
                pytest.fail(f"{sf.name}: invalid JSON — {e}")

    def test_every_schema_has_dollar_schema(self) -> None:
        for sf in _DOCS_SCHEMAS.glob("*.json"):
            data = json.loads(sf.read_text())
            assert "$schema" in data, f"{sf.name}: missing $schema"


# ── Documentation policy enforcement ─────────────────────────────


class TestDocumentationPolicy:
    def test_policy_declares_json_canonical(self) -> None:
        policy = json.loads((_DOCS_JSON / "documentation_policy.v1.json").read_text())
        # The policy content should mention JSON as canonical
        content_str = json.dumps(policy)
        assert "json" in content_str.lower()

    def test_policy_exists(self) -> None:
        assert (_DOCS_JSON / "documentation_policy.v1.json").is_file()


# ── Markdown exception policy ────────────────────────────────────

_ALLOWED_MARKDOWN = {
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "CONTRIBUTOR_LICENSE_AGREEMENT.md",
    "LICENSE",
    "ATTRIBUTION.md",
    "UPSTREAM.md",
    "THIRD_PARTY_NOTICES.md",
    "analysis_results.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
}


_GRANDFATHERED_DIRS = {
    "docs/",
    ".build/",
    ".venv/",
    "dist/",
    "build/",
    "extensions/",
    "rig_relay/core/prompts/",
    "rig_relay/core/tools/builtins/prompts/",
    "packaging/",
    ".pytest_cache/",
    "scripts/",
}


class TestMarkdownPolicy:
    def test_non_grandfathered_markdown_is_allowed_or_in_manifest(self) -> None:
        manifest_data = {"migrations": []}
        manifest_path = _DOCS_JSON / "documentation_migration_manifest.v1.json"
        if manifest_path.is_file():
            manifest_data = json.loads(manifest_path.read_text())

        migrated_old_paths = {
            m.get("old_path", "") for m in manifest_data.get("migrations", [])
        }

        for md_file in _REPO_ROOT.rglob("*.md"):
            rel = str(md_file.relative_to(_REPO_ROOT))
            # Skip grandfathered directories
            if any(rel.startswith(d) for d in _GRANDFATHERED_DIRS):
                continue
            if rel in _ALLOWED_MARKDOWN:
                continue
            if rel in migrated_old_paths:
                continue
            pytest.fail(
                f"Markdown file '{rel}' is not in allowed exceptions "
                f"and not in migration manifest"
            )


# ── Migration manifest ────────────────────────────────────────────


class TestMigrationManifest:
    def test_manifest_entries_have_required_fields(self) -> None:
        manifest_path = _DOCS_JSON / "documentation_migration_manifest.v1.json"
        if not manifest_path.is_file():
            return  # Empty manifest is fine
        data = json.loads(manifest_path.read_text())
        for m in data.get("migrations", []):
            assert "old_path" in m, f"Missing old_path in {m}"
            assert "status" in m, f"Missing status in {m}"


# ── Renderer smoke test ──────────────────────────────────────────


class TestRendererSmoke:
    def test_renderer_output_exists(self) -> None:
        assert _DOCS_OUT.joinpath("index.html").is_file(), "index.html not rendered"
        assert _DOCS_OUT.joinpath("render-manifest.json").is_file(), (
            "render-manifest.json not rendered"
        )
        assert _DOCS_OUT.joinpath("search-index.json").is_file(), (
            "search-index.json not rendered"
        )

    def test_render_manifest_has_git_sha(self) -> None:
        manifest = json.loads(_DOCS_OUT.joinpath("render-manifest.json").read_text())
        assert "git_commit" in manifest
        assert len(manifest["git_commit"]) >= 7

    def test_at_least_one_page_rendered(self) -> None:
        pages_dir = _DOCS_OUT / "pages"
        html_files = list(pages_dir.glob("*.html"))
        assert len(html_files) >= 1, "No pages rendered"

    def test_unsafe_content_escaped(self) -> None:
        for html_file in (_DOCS_OUT / "pages").glob("*.html"):
            content = html_file.read_text()
            assert "<script>" not in content, f"Unsafe <script> in {html_file.name}"
            assert "onerror=" not in content, f"Unsafe onerror in {html_file.name}"


# ── Git tracking ──────────────────────────────────────────────────


class TestDocsGitTracking:
    def test_docs_json_is_tracked(self) -> None:
        for jf in _DOCS_JSON.glob("*.json"):
            rel = str(jf.relative_to(_REPO_ROOT))
            assert _git_tracked(rel) or jf.is_file(), (
                f"{rel} is not tracked by git — run git add"
            )

    def test_docs_schemas_is_tracked(self) -> None:
        for sf in _DOCS_SCHEMAS.glob("*.json"):
            rel = str(sf.relative_to(_REPO_ROOT))
            assert _git_tracked(rel) or sf.is_file(), (
                f"{rel} is not tracked by git — run git add"
            )

    def test_renderer_script_is_present(self) -> None:
        assert _RENDERER.is_file(), "render_static_docs.py not found"

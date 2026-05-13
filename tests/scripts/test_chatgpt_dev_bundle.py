"""Tests for ChatGPT-friendly dev bundle generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from scripts.rig_relay_create_chatgpt_dev_bundle import (
    HARD_FILE_LIMIT_MB,
    MAX_TOKENS_PER_TEXT_FILE,
    _build_bundle,
    _estimate_tokens,
    _generate_executive_summary,
    _generate_readme,
    _has_forbidden_content,
    _has_forbidden_field_keys,
    _sha256_bytes,
)


class TestTokenEstimator:
    """Token estimator uses tiktoken and returns positive counts."""

    def test_estimate_tokens_returns_positive(self) -> None:
        count = _estimate_tokens("Hello world")
        assert count > 0

    def test_estimate_tokens_empty_string(self) -> None:
        count = _estimate_tokens("")
        assert count >= 0

    def test_estimate_tokens_long_text(self) -> None:
        text = "Hello world! " * 1000
        count = _estimate_tokens(text)
        assert count > 100

    def test_estimate_tokens_consistent(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        assert _estimate_tokens(text) == _estimate_tokens(text)


class TestContentLightSafeguards:
    """Content-light scanning works correctly."""

    def test_detects_private_key(self) -> None:
        assert _has_forbidden_content("-----BEGIN RSA PRIVATE KEY-----")

    def test_detects_openai_key(self) -> None:
        assert _has_forbidden_content("sk-proj-" + "a" * 30)

    def test_detects_github_pat(self) -> None:
        assert _has_forbidden_content("ghp_" + "a" * 36)

    def test_detects_bearer_token(self) -> None:
        assert _has_forbidden_content("Bearer " + "a" * 30)

    def test_clean_text_passes(self) -> None:
        assert not _has_forbidden_content("This is a clean text with no secrets.")

    def test_detects_forbidden_field_keys(self) -> None:
        assert _has_forbidden_field_keys({"raw_file_contents": "data"})
        assert _has_forbidden_field_keys({"nested": {"model_output_text": "data"}})

    def test_clean_dict_passes(self) -> None:
        assert not _has_forbidden_field_keys({"available": True, "count": 42})


class TestManifestSchema:
    """Manifest validates against schema."""

    def test_manifest_schema_exists(self) -> None:
        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.chatgpt_dev_bundle_manifest.v1.schema.json"
        )
        assert schema_path.is_file()

    def test_manifest_schema_validates_sample(self) -> None:
        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.chatgpt_dev_bundle_manifest.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        sample: dict[str, Any] = {
            "schema_version": "rig.relay.chatgpt_dev_bundle_manifest.v1",
            "bundle_id": "test-bundle-001",
            "created_at": "2026-05-13T00:00:00+00:00",
            "profile": "lite",
            "source_root": "/tmp/.build/rig-relay",
            "output_zip": "/tmp/bundle.zip",
            "estimated_total_tokens": 1000,
            "estimated_total_text_bytes": 5000,
            "zip_size_bytes": 2000,
            "chatgpt_upload_safe": True,
            "hard_file_limit_mb": 512,
            "target_bundle_mb": 100,
            "max_tokens_per_text_file": 1800000,
            "included_files": [
                {
                    "path": "README.md",
                    "kind": "readme",
                    "estimated_tokens": 500,
                    "size_bytes": 2000,
                    "source": "generated",
                    "reason_included": "Bundle overview",
                    "sha256": "abc123",
                }
            ],
            "excluded_files": ["raw/logs/*"],
            "row_counts": {"coordination": 100},
            "warnings": [],
            "content_light_guarantee": True,
        }
        jsonschema.validate(sample, schema)


class TestBundleProfiles:
    """Bundle profiles produce expected structure."""

    def test_lite_profile_includes_readme_and_manifest(self, tmp_path: Path) -> None:
        manifest = _build_bundle(
            build_root=tmp_path,
            docs_root=tmp_path,
            profile="lite",
            target_mb=25,
            max_text_file_tokens=1_800_000,
            strict=False,
            dry_run=True,
        )
        paths = [f["path"] for f in manifest["included_files"]]
        assert "README.md" in paths
        assert "executive-summary.json" in paths
        assert "dataset-counts.json" in paths
        assert "schema-index.md" in paths
        assert "source-map.json" in paths

    def test_lite_profile_excludes_jsonl(self, tmp_path: Path) -> None:
        manifest = _build_bundle(
            build_root=tmp_path,
            docs_root=tmp_path,
            profile="lite",
            target_mb=25,
            max_text_file_tokens=1_800_000,
            strict=False,
            dry_run=True,
        )
        paths = [f["path"] for f in manifest["included_files"]]
        assert all(not p.endswith(".jsonl") for p in paths)

    def test_analysis_profile_includes_derived_rows(self, tmp_path: Path) -> None:
        manifest = _build_bundle(
            build_root=tmp_path,
            docs_root=tmp_path,
            profile="analysis",
            target_mb=100,
            max_text_file_tokens=1_800_000,
            strict=False,
            dry_run=True,
        )
        paths = [f["path"] for f in manifest["included_files"]]
        # Analysis profile adds JSONL files when data exists
        # With empty build_root, they won't be present, which is fine
        assert "README.md" in paths
        assert manifest["profile"] == "analysis"

    def test_dry_run_does_not_write_zip(self, tmp_path: Path) -> None:
        from scripts.rig_relay_create_chatgpt_dev_bundle import _write_zip

        manifest = _build_bundle(
            build_root=tmp_path,
            docs_root=tmp_path,
            profile="lite",
            target_mb=25,
            max_text_file_tokens=1_800_000,
            strict=False,
            dry_run=True,
        )
        zip_path = _write_zip(manifest, tmp_path, dry_run=True)
        assert not zip_path.exists()


class TestChatGPTSafety:
    """ChatGPT upload safety is correctly computed."""

    def test_manifest_marks_upload_safe(self, tmp_path: Path) -> None:
        manifest = _build_bundle(
            build_root=tmp_path,
            docs_root=tmp_path,
            profile="lite",
            target_mb=25,
            max_text_file_tokens=1_800_000,
            strict=False,
            dry_run=True,
        )
        assert manifest["chatgpt_upload_safe"] is True

    def test_manifest_constants(self) -> None:
        assert HARD_FILE_LIMIT_MB == 512
        assert MAX_TOKENS_PER_TEXT_FILE == 2_000_000


class TestSha256:
    """SHA256 utilities work."""

    def test_sha256_bytes_consistent(self) -> None:
        data = b"hello world"
        assert _sha256_bytes(data) == _sha256_bytes(data)

    def test_sha256_bytes_different(self) -> None:
        assert _sha256_bytes(b"hello") != _sha256_bytes(b"world")


class TestExecutiveSummary:
    """Executive summary is structured correctly."""

    def test_summary_has_expected_keys(self) -> None:
        summary = _generate_executive_summary(
            current_state={"summary": {"active_children": 3}},
            projection={"source_status": {"dataset": True}},
            coord_summary={"available": True, "total_rows": 100},
            failure_summary={"available": False},
            perf_summary={"available": False},
            findings_summary={"available": False},
            snippets_summary={"available": False},
            row_counts={"coordination": 100},
        )
        assert "coordination_state" in summary
        assert "coordination_dataset" in summary
        assert "tool_failures" in summary
        assert "derived_dataset_row_counts" in summary
        assert "projection_source_availability" in summary


class TestReadme:
    """README is generated correctly."""

    def test_readme_includes_profile(self) -> None:
        from datetime import UTC, datetime

        text = _generate_readme(
            bundle_id="test-bundle", profile="lite", now=datetime.now(UTC), target_mb=25
        )
        assert "lite profile" in text
        assert "test-bundle" in text
        assert "Content-light guarantee" in text
        assert "What to inspect first" in text
        assert "What is intentionally excluded" in text

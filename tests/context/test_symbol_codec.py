"""Tests for the typed-namespace symbol replacement codec."""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.symbol_codec import (
    ManifestEntry,
    SymbolManifest,
    _classify_term,
    _has_symbol_collision,
    _typed_symbol_sequence,
    compress_with_manifest,
    decompress_symbols,
    expand_aliases,
    find_candidates,
)
from rig_relay.context.symbol_digest import CodebaseSymbolDigest, build_digest_from_repo
from rig_relay.context.symbol_manifest import build_codebase_symbol_manifest


class TestTypedSymbolSequence:
    def test_first_symbol_is_p001(self) -> None:
        seq = _typed_symbol_sequence(10)
        assert seq[0] == "§p001"

    def test_spans_namespaces(self) -> None:
        seq = _typed_symbol_sequence(6000)
        kinds = set(s[1] for s in seq)
        assert "p" in kinds and "t" in kinds and "s" in kinds
        assert "d" in kinds and "c" in kinds and "m" in kinds

    def test_all_unique(self) -> None:
        seq = _typed_symbol_sequence(2000)
        assert len(seq) == len(set(seq))

    def test_deterministic(self) -> None:
        assert _typed_symbol_sequence(50) == _typed_symbol_sequence(50)


class TestCollisionDetection:
    def test_detects_typed_symbol(self) -> None:
        assert _has_symbol_collision("use §p014 for the path")

    def test_ignores_plain_text(self) -> None:
        assert not _has_symbol_collision("plain text without aliases")

    def test_multiple_aliases(self) -> None:
        assert _has_symbol_collision("§p001 and §t002 are aliases")

    def test_detects_pua_chars(self) -> None:
        assert _has_symbol_collision("\ue000 already reserved")


class TestClassifyTerm:
    def test_path_with_slash(self) -> None:
        assert _classify_term("vibe/cli/dashboard.py") == "path"

    def test_type_uppercase(self) -> None:
        assert _classify_term("RuntimeSessionAdapter") == "type"

    def test_schema_docs(self) -> None:
        assert _classify_term("docs/schemas/rig.relay.foo.v1.schema.json") == "schema"

    def test_doctrine_md(self) -> None:
        assert _classify_term("CONTEXT.md") == "doctrine"

    def test_plain_module(self) -> None:
        assert _classify_term("dashboard") != ""
        assert _classify_term("__init__") != ""


class TestCompressWithManifest:
    def test_round_trip(self) -> None:
        text = (
            "vibe/cli/textual_ui/rig_console/screens/dashboard.py is the main screen. "
            "vibe/cli/textual_ui/rig_console/screens/dashboard.py has the turn loop. "
            "vibe/cli/textual_ui/rig_console/screens/dashboard.py is big."
        )
        result = compress_with_manifest(text)
        assert result.refused_reason is None
        assert result.manifest is not None
        assert len(result.manifest.entries) >= 1
        restored = decompress_symbols(result.compressed_text, result.manifest)
        assert restored == text

    def test_byte_for_byte(self) -> None:
        text = (
            "DashboardProjectionProvider builds projections. "
            "DashboardProjectionProvider has the data. "
            "DashboardProjectionProvider caches everything. "
            "DashboardProjectionProvider is deterministic."
        )
        result = compress_with_manifest(text)
        assert result.manifest is not None
        restored = decompress_symbols(result.compressed_text, result.manifest)
        assert restored.encode("utf-8") == text.encode("utf-8")

    def test_deterministic_output(self) -> None:
        text = (
            "RuntimeSessionAdapter runs. "
            "RuntimeSessionAdapter stores. "
            "RuntimeSessionAdapter bridges. "
            "RuntimeSessionAdapter connects."
        )
        r1 = compress_with_manifest(text)
        r2 = compress_with_manifest(text)
        assert r1.compressed_text == r2.compressed_text
        assert r1.manifest is not None
        assert r2.manifest is not None
        assert r1.manifest.manifest_sha256 == r2.manifest.manifest_sha256

    def test_round_trip_preserves_existing_section_symbols(self) -> None:
        text = (
            "§p001 is pre-existing. "
            "RuntimeSessionAdapter runs here. "
            "RuntimeSessionAdapter runs there. "
            "RuntimeSessionAdapter runs everywhere."
        )
        result = compress_with_manifest(text)
        assert result.refused_reason is None
        assert result.manifest is not None
        restored = decompress_symbols(result.compressed_text, result.manifest)
        assert restored == text
        assert "\\u00A7" in result.compressed_text

    def test_pua_alias_mode_round_trip(self) -> None:
        text = (
            "DashboardProjectionProvider builds projections. "
            "DashboardProjectionProvider builds projections. "
            "DashboardProjectionProvider builds projections."
        )
        result = compress_with_manifest(text, alias_mode="pua")
        assert result.refused_reason is None
        assert result.manifest is not None
        assert any("\ue000" <= ch <= "\uf8ff" for ch in result.compressed_text)
        restored = decompress_symbols(
            result.compressed_text, result.manifest, alias_mode="pua"
        )
        assert restored == text

    def test_no_candidates(self) -> None:
        result = compress_with_manifest("hello world")
        assert result.refused_reason == "No candidates found"

    def test_token_estimator_decreases_on_replacement(self) -> None:
        text = (
            "RuntimeSessionAdapter RuntimeSessionAdapter RuntimeSessionAdapter "
            "RuntimeSessionAdapter RuntimeSessionAdapter"
        )
        result = compress_with_manifest(text)
        assert result.receipt is not None
        assert (
            result.receipt.estimated_tokens_before
            > result.receipt.estimated_tokens_after
        )


class TestExpandAliases:
    def test_expands_path_aliases(self) -> None:
        text = "RuntimeSessionAdapter is here. " * 4
        result = compress_with_manifest(text)
        assert result.manifest is not None
        compressed = result.compressed_text
        expanded = expand_aliases(compressed, result.manifest)
        assert expanded == text
        assert "§" not in expanded

    def test_expand_then_decompress_identical(self) -> None:
        text = "DashboardProjectionProvider provides. " * 4
        result = compress_with_manifest(text)
        assert result.manifest is not None
        expanded = expand_aliases(result.compressed_text, result.manifest)
        decompressed = decompress_symbols(result.compressed_text, result.manifest)
        assert expanded == decompressed == text

    def test_expands_section_escape_marker_back_to_symbol(self) -> None:
        text = (
            "§p001 is pre-existing. "
            "DashboardProjectionProvider provides. "
            "DashboardProjectionProvider provides. "
            "DashboardProjectionProvider provides."
        )
        result = compress_with_manifest(text)
        assert result.manifest is not None
        restored = expand_aliases(result.compressed_text, result.manifest)
        assert restored == text

    def test_expands_pua_aliases_back_to_literal_text(self) -> None:
        text = (
            "DashboardProjectionProvider provides. "
            "DashboardProjectionProvider provides. "
            "DashboardProjectionProvider provides."
        )
        result = compress_with_manifest(text, alias_mode="pua")
        assert result.manifest is not None
        restored = expand_aliases(result.compressed_text, result.manifest)
        assert restored == text


class TestFindCandidates:
    def test_returns_measured_entries(self) -> None:
        text = (
            "RuntimeSessionAdapter is here. " * 3
            + "DashboardProjectionProvider is there. " * 2
        )
        entries = find_candidates(text)
        assert len(entries) >= 1
        assert entries[0].occurrences >= 2
        assert entries[0].net_savings > 0
        assert entries[0].alias.startswith("§")

    def test_no_short_terms(self) -> None:
        entries = find_candidates("foo bar baz")
        assert len(entries) == 0


class TestDigest:
    def test_build_from_text(self) -> None:
        digest = CodebaseSymbolDigest()
        digest.add_text(
            "RuntimeSessionAdapter handles streaming. " * 4
            + "DashboardProjectionProvider provides data. " * 3
        )
        manifest = digest.build()
        assert len(manifest.entries) >= 1
        assert manifest.total_net_savings > 0
        assert manifest.manifest_sha256 != ""

    def test_positive_net_savings_only(self) -> None:
        digest = CodebaseSymbolDigest()
        digest.add_text("RuntimeSessionAdapter. " * 3)
        manifest = digest.build()
        for e in manifest.entries:
            assert e.net_savings > 0

    def test_empty_corpus(self) -> None:
        manifest = CodebaseSymbolDigest().build()
        assert len(manifest.entries) == 0

    def test_add_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("RuntimeSessionAdapter " * 5)
        digest = CodebaseSymbolDigest()
        digest.add_file(f)
        manifest = digest.build(min_occurrences=3)
        assert len(manifest.entries) >= 1

    def test_build_digest_from_repo(self, tmp_path: Path) -> None:
        _init_git(tmp_path)
        (tmp_path / "core.py").write_text("RuntimeSessionAdapter " * 5)
        (tmp_path / "AGENTS.md").write_text("# Rules")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "guide.md").write_text(
            "DashboardProjectionProvider provides. " * 3
        )
        _git_add_all(tmp_path)

        manifest = build_digest_from_repo(tmp_path, min_occurrences=2)
        assert len(manifest.entries) >= 1
        assert manifest.total_net_savings > 0


class TestManifest:
    def test_to_table(self) -> None:
        entries = (ManifestEntry("§p001", "path", "foo.py", 3, 30, 6, 4, 20),)
        manifest = SymbolManifest(entries)
        table = manifest.to_table()
        assert len(table) == 1
        assert table[0]["alias"] == "§p001"
        assert table[0]["net_savings"] == 20

    def test_empty_manifest(self) -> None:
        manifest = SymbolManifest(())
        assert len(manifest.entries) == 0
        assert manifest.total_net_savings == 0
        assert manifest.manifest_sha256 == hashlib.sha256(b"").hexdigest()

    def test_total_calculation(self) -> None:
        entries = (
            ManifestEntry("§p001", "path", "a.py", 3, 30, 6, 4, 20),
            ManifestEntry("§t001", "type", "Foo", 5, 25, 10, 5, 10),
        )
        manifest = SymbolManifest(entries)
        assert manifest.total_source_tokens == 55
        assert manifest.total_alias_tokens == 16
        assert manifest.total_overhead == 9
        assert manifest.total_net_savings == 30

    def test_codebase_manifest_builder_is_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "vibe").mkdir()
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / "vibe" / name).write_text(
                "class RuntimeSessionAdapter:\n"
                "    pass\n\n"
                "class RuntimeSessionAdapter:\n"
                "    pass\n"
            )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "guide.md").write_text(
            "# DashboardProjectionProvider\n"
            "# DashboardProjectionProvider\n"
            "# DashboardProjectionProvider\n"
        )
        r1 = build_codebase_symbol_manifest(tmp_path)
        r2 = build_codebase_symbol_manifest(tmp_path)
        assert r1.manifest.manifest_sha256 == r2.manifest.manifest_sha256
        assert [entry.alias for entry in r1.manifest.entries] == [
            entry.alias for entry in r2.manifest.entries
        ]
        assert r1.alias_mode == "section"

    def test_codebase_manifest_changes_when_inputs_change(self, tmp_path: Path) -> None:
        (tmp_path / "vibe").mkdir()
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / "vibe" / name).write_text(
                "class RuntimeSessionAdapter:\n"
                "    pass\n\n"
                "class RuntimeSessionAdapter:\n"
                "    pass\n"
            )
        r1 = build_codebase_symbol_manifest(tmp_path)
        (tmp_path / "vibe" / "d.py").write_text(
            "class RuntimeSessionAdapter:\n"
            "    pass\n\n"
            "class RuntimeSessionAdapter:\n"
            "    pass\n"
        )
        r2 = build_codebase_symbol_manifest(tmp_path)
        assert r1.manifest.manifest_sha256 != r2.manifest.manifest_sha256
        assert r1.source_root_fingerprint == r2.source_root_fingerprint

    def test_codebase_manifest_uses_alias_mode(self, tmp_path: Path) -> None:
        (tmp_path / "vibe").mkdir()
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / "vibe" / name).write_text(
                "class RuntimeSessionAdapter:\n"
                "    pass\n\n"
                "class RuntimeSessionAdapter:\n"
                "    pass\n"
            )
        result = build_codebase_symbol_manifest(tmp_path, alias_mode="pua")
        assert result.alias_mode == "pua"
        assert result.manifest.entries == () or all(
            len(entry.alias) == 1 for entry in result.manifest.entries
        )


# ── Git helpers ──────────────────────────────────────────────────


import hashlib
import subprocess


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, capture_output=True
    )


def _git_add_all(path: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "test"], cwd=path, capture_output=True)

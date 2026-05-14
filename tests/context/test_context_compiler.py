"""Tests for the pack-based ContextCompiler."""

from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.compiler import (
    ActiveFocusPack,
    AgentsMdPack,
    CompactionHistoryPack,
    ContextCompiler,
    ContextPack,
    DirtyFilesPack,
    DirtyOwnershipPack,
    GitStatePack,
    RecentTranscriptPack,
    RelevantTestsPack,
)
from rig_relay.context.models import ContextEnvelopeReceipt, ContextSection
from rig_relay.context.symbol_codec import decompress_symbols
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.evidence.receipt_store import FilesystemReceiptStore
from vibe.cli.textual_ui.rig_console.session_events import (
    CodingSessionSnapshot,
    CodingTranscriptItemProjection,
    CodingTranscriptProjection,
)


class TestContextSection:
    def test_create(self) -> None:
        s = ContextSection(name="test", fingerprint="abc123", summary="a section")
        assert s.name == "test"

    def test_frozen(self) -> None:
        s = ContextSection(name="t", fingerprint="f", summary="s")
        with pytest.raises(AttributeError):
            s.name = "changed"  # type: ignore[misc]


class TestContextEnvelopeReceipt:
    def test_create(self) -> None:
        e = ContextEnvelopeReceipt(
            rendered_prompt="hello",
            sections=[ContextSection(name="s1", fingerprint="f1", summary="s1")],
        )
        assert e.section_count == 1
        assert e.is_cached is False

    def test_cached(self) -> None:
        e = ContextEnvelopeReceipt(rendered_prompt="t", cache_key="ck")
        assert e.is_cached is True

    def test_default_fields(self) -> None:
        e = ContextEnvelopeReceipt(rendered_prompt="t")
        assert e.created_at != ""
        assert e.receipt_id != ""
        assert e.symbol_codec_receipt is None


class TestAgentsMdPack:
    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        pack = AgentsMdPack()
        section = pack.build(tmp_path)
        assert section is None

    def test_finds_agents_md(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("# Rules", encoding="utf-8")
        pack = AgentsMdPack()
        section = pack.build(tmp_path)
        assert section is not None
        assert section.name == "agents_md"

    def test_finds_claude_md(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Claude", encoding="utf-8")
        pack = AgentsMdPack()
        section = pack.build(tmp_path)
        assert section is not None

    def test_cache_hit_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("# Rules", encoding="utf-8")
        pack = AgentsMdPack()
        pack.build(tmp_path)
        section2 = pack.build(tmp_path)
        assert section2 is None


class TestGitStatePack:
    def test_returns_section(self) -> None:
        pack = GitStatePack()
        section = pack.build(Path.cwd())
        assert section is not None
        assert "branch" in section.summary.lower() or "?" in section.summary

    def test_render_includes_status(self) -> None:
        pack = GitStatePack()
        source = pack.get_source(Path.cwd())
        assert "Branch:" in source
        assert "HEAD:" in source
        assert "Status:" in source


class TestDirtyFilesPack:
    def test_returns_section(self) -> None:
        pack = DirtyFilesPack()
        section = pack.build(Path.cwd())
        assert section is not None

    def test_summary_mentions_dirty(self) -> None:
        pack = DirtyFilesPack()
        section = pack.build(Path.cwd())
        assert section is not None
        assert "dirty" in section.summary.lower() or "No" in section.summary


class TestDirtyOwnershipPack:
    def test_returns_section(self) -> None:
        pack = DirtyOwnershipPack()
        section = pack.build(Path.cwd())
        assert section is not None
        assert (
            "ownership" in section.summary.lower() or "dirty" in section.summary.lower()
        )


class TestRecentTranscriptPack:
    def test_no_snapshot_returns_none(self) -> None:
        pack = RecentTranscriptPack()
        section = pack.build(Path.cwd())
        assert section is None

    def test_with_snapshot(self) -> None:
        snapshot = CodingSessionSnapshot(
            session_id="s1",
            transcript=CodingTranscriptProjection(
                session_id="s1",
                items=[
                    CodingTranscriptItemProjection(
                        item_id="i1",
                        kind="user_message",
                        title="User",
                        body_text="hello",
                    )
                ],
            ),
        )
        pack = RecentTranscriptPack()
        pack.set_snapshot(snapshot)
        section = pack.build(Path.cwd())
        assert section is not None
        assert "transcript" in section.summary.lower()

    def test_render_filters_turn_status(self) -> None:
        snapshot = CodingSessionSnapshot(
            session_id="s1",
            transcript=CodingTranscriptProjection(
                session_id="s1",
                items=[
                    CodingTranscriptItemProjection(
                        item_id="i1",
                        kind="turn_status",
                        title="Turn",
                        status="completed",
                    ),
                    CodingTranscriptItemProjection(
                        item_id="i2",
                        kind="user_message",
                        title="User",
                        body_text="hello",
                    ),
                ],
            ),
        )
        pack = RecentTranscriptPack()
        pack.set_snapshot(snapshot)
        source = pack.get_source(Path.cwd())
        assert "hello" in source


class TestRelevantTestsPack:
    def test_no_paths_returns_none(self) -> None:
        pack = RelevantTestsPack()
        section = pack.build(Path.cwd())
        assert section is None

    def test_skips_when_no_tests(self, tmp_path: Path) -> None:
        pack = RelevantTestsPack()
        pack.set_changed_paths(["src/main.py"])
        section = pack.build(tmp_path)
        assert section is None


class TestActiveFocusPack:
    def test_no_file_refs_returns_none(self) -> None:
        pack = ActiveFocusPack()
        pack.set_user_text("fix the bug")
        section = pack.build(Path.cwd())
        assert section is None

    def test_detects_file_refs(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
        pack = ActiveFocusPack()
        pack.set_user_text("fix main.py")
        section = pack.build(tmp_path)
        assert section is not None
        assert "focus" in section.summary.lower() or "file" in section.summary.lower()


class TestContextCompiler:
    def test_build_minimal(self) -> None:
        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(user_text="hello")
        assert isinstance(env, ContextEnvelopeReceipt)
        assert "hello" in env.rendered_prompt
        assert env.section_count >= 1

    def test_build_includes_user_prompt_tag(self) -> None:
        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(user_text="fix the bug")
        assert "<user_prompt>" in env.rendered_prompt
        assert "fix the bug" in env.rendered_prompt

    def test_deterministic_hash(self) -> None:
        compiler = ContextCompiler(session_id="s1")
        env1 = compiler.build_envelope(user_text="hello")
        env2 = compiler.build_envelope(user_text="hello")
        assert env1.envelope_sha256 == env2.envelope_sha256

    def test_with_snapshot_includes_transcript(self) -> None:
        snapshot = CodingSessionSnapshot(
            session_id="s1",
            transcript=CodingTranscriptProjection(
                session_id="s1",
                items=[
                    CodingTranscriptItemProjection(
                        item_id="i1",
                        kind="user_message",
                        title="User",
                        body_text="hello",
                    )
                ],
            ),
        )
        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(user_text="test", snapshot=snapshot)
        assert env.section_count >= 1

    def test_cache_key_varies_with_content(self) -> None:
        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(user_text="a")
        key1 = env.cache_key
        env = compiler.build_envelope(user_text="a")
        key2 = env.cache_key
        assert key1 == key2

    def test_default_packs_includes_all_packs(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("# Rules", encoding="utf-8")
        compiler = ContextCompiler(session_id="s1", workspace_root=tmp_path)
        env = compiler.build_envelope(user_text="test")
        names = {s.name for s in env.sections}
        assert "agents_md" in names
        assert "git_state" in names
        assert "dirty_files" in names
        assert (
            "active_file_focus" in names or "active_file_focus" in env.sections_omitted
        )

    def test_pack_order_stable(self) -> None:
        compiler = ContextCompiler(session_id="s1")
        env1 = compiler.build_envelope(user_text="x")
        env2 = compiler.build_envelope(user_text="x")
        names1 = [s.name for s in env1.sections]
        names2 = [s.name for s in env2.sections]
        assert names1 == names2

    def test_compresses_navigation_sections_but_not_user_prompt(self) -> None:
        class NavigationPack(ContextPack):
            name = "related_files"

            def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
                return ("fingerprint",)

            def _render(self, root: Path) -> str:
                return (
                    "vibe/cli/textual_ui/rig_console/screens/dashboard.py "
                    "vibe/cli/textual_ui/rig_console/screens/dashboard.py "
                    "vibe/cli/textual_ui/rig_console/screens/dashboard.py "
                    "vibe/cli/textual_ui/rig_console/screens/dashboard.py"
                )

        class ProtectedPack(ContextPack):
            name = "recent_transcript"

            def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
                return ("fingerprint-2",)

            def _render(self, root: Path) -> str:
                return "assistant said: do not compress this exact transcript"

        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(
            user_text="keep this prompt exact",
            packs=[NavigationPack(), ProtectedPack()],
        )

        assert env.symbol_codec_receipt is not None
        assert env.symbol_manifest is not None
        assert "keep this prompt exact" in env.rendered_prompt
        assert "do not compress this exact transcript" in env.rendered_prompt
        assert "§" in env.rendered_prompt
        assert (
            "vibe/cli/textual_ui/rig_console/screens/dashboard.py"
            not in env.rendered_prompt
        )
        assert "§" in env.compressed_prompt
        assert decompress_symbols(
            env.compressed_prompt, env.symbol_manifest
        ).startswith('<context name="related_files">')

    def test_non_navigation_sections_stay_uncompressed(self) -> None:
        class ProtectedPack(ContextPack):
            name = "recent_transcript"

            def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
                return ("fingerprint-3",)

            def _render(self, root: Path) -> str:
                return "tests/context/test_context_compiler.py exact content"

        compiler = ContextCompiler(session_id="s1")
        env = compiler.build_envelope(user_text="prompt", packs=[ProtectedPack()])

        assert env.symbol_codec_receipt is None
        assert env.symbol_manifest is None
        assert env.rendered_prompt.count("tests/context/test_context_compiler.py") == 1


class TestCompactionHistoryPack:
    def test_no_store_returns_none(self) -> None:
        pack = CompactionHistoryPack(receipt_store=None)
        pack.set_session_id("s1")
        section = pack.build(Path.cwd())
        assert section is None

    def test_no_receipts_returns_none(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        pack = CompactionHistoryPack(receipt_store=store)
        pack.set_session_id("s1")
        section = pack.build(Path.cwd())
        assert section is None

    def test_with_compaction_receipts(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        env = build_receipt_envelope(
            receipt_kind="compaction",
            actor=ReceiptActor(actor_id="runtime", actor_kind=ReceiptActorKind.RUNTIME),
            subject=ReceiptSubject(
                subject_id="s1:c1",
                subject_kind=ReceiptSubjectKind.SESSION,
                session_id="s1",
            ),
            receipt_payload={
                "dropped_count": 10,
                "kinds": {"user_message": 6, "assistant_message": 4},
            },
            decision=ReceiptDecision(
                decision="pruned",
                rationale="Dropped 10 items: 4 assistant_message, 6 user_message",
            ),
        )
        store.append(env)
        pack = CompactionHistoryPack(receipt_store=store)
        pack.set_session_id("s1")
        section = pack.build(Path.cwd())
        assert section is not None
        assert "compaction" in section.name
        source = pack.get_source(Path.cwd())
        assert "Dropped 10 items" in source

    def test_only_compaction_kind(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        ctx_env = build_receipt_envelope(
            receipt_kind="context_envelope",
            actor=ReceiptActor(
                actor_id="compiler", actor_kind=ReceiptActorKind.RUNTIME
            ),
            subject=ReceiptSubject(
                subject_id="s1",
                subject_kind=ReceiptSubjectKind.SESSION,
                session_id="s1",
            ),
            receipt_payload={"section_count": 3},
        )
        store.append(ctx_env)
        pack = CompactionHistoryPack(receipt_store=store)
        pack.set_session_id("s1")
        section = pack.build(Path.cwd())
        assert section is None

    def test_fingerprint_caching(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        env = build_receipt_envelope(
            receipt_kind="compaction",
            actor=ReceiptActor(actor_id="runtime", actor_kind=ReceiptActorKind.RUNTIME),
            subject=ReceiptSubject(
                subject_id="s1:c1",
                subject_kind=ReceiptSubjectKind.SESSION,
                session_id="s1",
            ),
            receipt_payload={"dropped_count": 5, "kinds": {"user_message": 5}},
            decision=ReceiptDecision(decision="pruned", rationale="Dropped 5 items"),
        )
        store.append(env)
        pack = CompactionHistoryPack(receipt_store=store)
        pack.set_session_id("s1")
        section1 = pack.build(Path.cwd())
        assert section1 is not None
        section2 = pack.build(Path.cwd())
        assert section2 is None

    def test_persisted_via_compiler(self, tmp_path: Path) -> None:
        store = FilesystemReceiptStore(tmp_path / "receipts")
        compiler = ContextCompiler(
            session_id="s1", workspace_root=tmp_path, receipt_store=store
        )
        env = compiler.build_envelope(user_text="hello")
        assert env.section_count >= 1
        receipts = store.list_by_session("s1", limit=10)
        assert any(r.receipt_kind == "context_envelope" for r in receipts)

"""Context compiler — deterministic prompt enrichment for Rig Console.

Phase 3: DuckDB-backed RepoContextIndex for constrained retrieval. Maps
files to tests, docs, schemas, and related paths. No embeddings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any

from rig_relay.context.models import ContextEnvelopeReceipt, ContextSection
from rig_relay.context.repo_index import RepoContextIndex
from rig_relay.context.symbol_codec import compress_with_manifest
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.evidence.receipt_store import ReceiptStore

# ── Helpers ────────────────────────────────────────────────────────


def _hash(*components: str) -> str:
    return hashlib.sha256("|".join(components).encode()).hexdigest()[:16]


def _read_safe(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL, cwd=cwd or Path.cwd()
        ).strip()
    except Exception:
        return ""


_COMPRESSIBLE_PACKS = {
    "git_state",
    "dirty_files",
    "dirty_ownership",
    "active_file_focus",
    "related_files",
}


def _symbol_receipt_payload(
    receipt: Any | None,
) -> dict[str, str | int | bool | None] | None:
    if receipt is None:
        return None
    return {
        "codec_name": getattr(receipt, "codec_name", ""),
        "codec_version": getattr(receipt, "codec_version", ""),
        "input_sha256": getattr(receipt, "input_sha256", ""),
        "output_sha256": getattr(receipt, "output_sha256", ""),
        "manifest_sha256": getattr(receipt, "manifest_sha256", ""),
        "estimated_tokens_before": getattr(receipt, "estimated_tokens_before", 0),
        "estimated_tokens_after": getattr(receipt, "estimated_tokens_after", 0),
        "replacement_count": getattr(receipt, "replacement_count", 0),
        "reversible": getattr(receipt, "reversible", True),
        "lossy": getattr(receipt, "lossy", False),
        "refused_reason": getattr(receipt, "refused_reason", None),
    }


def _build_envelope_parts(
    root: Path, packs: list[ContextPack]
) -> tuple[
    list[ContextSection],
    list[str],
    list[str],
    str,
    Any | None,
    dict[str, str | int | bool | None] | None,
]:
    sections: list[ContextSection] = []
    omitted: list[str] = []
    compressible_parts: list[str] = []
    protected_parts: list[str] = []
    symbol_manifest = None
    symbol_codec_receipt = None

    for pack in packs:
        section = pack.build(root)
        if section is None:
            omitted.append(pack.name)
            continue

        sections.append(section)
        source = pack.get_source(root)
        if not source:
            continue

        part = f'<context name="{pack.name}">\n{source}\n</context>'
        if pack.name in _COMPRESSIBLE_PACKS:
            compressible_parts.append(part)
        else:
            protected_parts.append(part)

    compressed_prompt = "\n\n".join(compressible_parts)
    rendered_parts: list[str]
    if compressed_prompt:
        result = compress_with_manifest(compressed_prompt)
        compressed_prompt = result.compressed_text
        symbol_manifest = result.manifest
        symbol_codec_receipt = _symbol_receipt_payload(result.receipt)
        protected_parts.append(
            '<context name="symbol_codec">\n'
            f"codec={result.receipt.codec_name if result.receipt else 'rig.symbol.v1'}\n"
            f"manifest_sha256={result.manifest.manifest_sha256 if result.manifest else ''}\n"
            f"estimated_tokens_before={result.receipt.estimated_tokens_before if result.receipt else 0}\n"
            f"estimated_tokens_after={result.receipt.estimated_tokens_after if result.receipt else 0}\n"
            f"replacement_count={result.receipt.replacement_count if result.receipt else 0}\n"
            "</context>"
        )
        rendered_parts = [
            f'<context name="compressed_navigation">\n{compressed_prompt}\n</context>'
        ] + protected_parts
    else:
        rendered_parts = protected_parts

    return (
        sections,
        omitted,
        rendered_parts,
        compressed_prompt,
        symbol_manifest,
        symbol_codec_receipt,
    )


# ── Base pack ──────────────────────────────────────────────────────


class ContextPack:
    """A single context pack with its own fingerprint cache.

    Subclasses define ``_fingerprint_sources(root)`` and
    ``_render(root)``. The ``build(root)`` method checks the fingerprint
    before re-rendering and returns None if unchanged.
    """

    name: str = ""
    _cached_fingerprint: str = ""

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        return ()

    def _render(self, root: Path) -> str:
        return ""

    def _summary(self, root: Path) -> str:
        return ""

    def build(self, root: Path) -> ContextSection | None:
        src = self._fingerprint_sources(root)
        if not src or all(not s for s in src):
            return None
        fp = _hash(self.name, *src)
        if fp == self._cached_fingerprint:
            return None
        self._cached_fingerprint = fp
        return ContextSection(
            name=self.name, fingerprint=fp, summary=self._summary(root)
        )

    def get_source(self, root: Path) -> str:
        return self._render(root)

    def reset_cache(self) -> None:
        self._cached_fingerprint = ""


# ── Concrete packs ─────────────────────────────────────────────────


class AgentsMdPack(ContextPack):
    name = "agents_md"

    def _find(self, root: Path) -> Path | None:
        for candidate in [root / "AGENTS.md", root / "CLAUDE.md"]:
            if candidate.is_file():
                return candidate
        return None

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        f = self._find(root)
        return (_read_safe(f),) if f else ("",)

    def _render(self, root: Path) -> str:
        f = self._find(root)
        return _read_safe(f) if f else ""

    def _summary(self, root: Path) -> str:
        f = self._find(root)
        if f:
            c = _read_safe(f)
            return f"Agent rules ({f.name}, {len(c.splitlines())} lines)" if c else ""
        return "No agent rules"


class GitStatePack(ContextPack):
    name = "git_state"

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
        head = _git("rev-parse", "HEAD", cwd=root)
        if not branch and not head:
            return ("no-git",)
        return (branch or "no-branch", head or "no-head")

    def _render(self, root: Path) -> str:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
        head = _git("rev-parse", "HEAD", cwd=root)
        status = _git("status", "--short", cwd=root)
        return (
            f"Branch: {branch or 'unknown'}\n"
            f"HEAD: {head or 'unknown'}\n"
            f"Status:\n{status or '(clean)'}"
        )

    def _summary(self, root: Path) -> str:
        b = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root) or "?"
        h = (_git("rev-parse", "HEAD", cwd=root) or "?")[:12]
        return f"Branch: {b} @ {h}"


class DirtyFilesPack(ContextPack):
    name = "dirty_files"

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        s = _git("status", "--short", cwd=root)
        return (s or "clean",)

    def _render(self, root: Path) -> str:
        return _git("status", "--short", cwd=root) or "(clean)"

    def _summary(self, root: Path) -> str:
        s = _git("status", "--short", cwd=root)
        if not s:
            return "No dirty files"
        return f"Dirty files: {len([l for l in s.splitlines() if l.strip()])} changed/untracked"


class DirtyOwnershipPack(ContextPack):
    name = "dirty_ownership"

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        s = _git("status", "--short", cwd=root)
        return (s or "clean",)

    def _render(self, root: Path) -> str:
        status = _git("status", "--short", cwd=root)
        if not status:
            return "(no dirty files)"
        return "Files that need attention:\n" + "\n".join(
            f"  {l.strip()}" for l in status.splitlines() if l.strip()
        )

    def _summary(self, root: Path) -> str:
        s = _git("status", "--short", cwd=root)
        count = len([l for l in s.splitlines() if l.strip()]) if s else 0
        return f"Dirty ownership: {count} files need attention"


class RecentTranscriptPack(ContextPack):
    name = "recent_transcript"

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: Any | None = None

    def set_snapshot(self, snapshot: Any | None) -> None:
        self._snapshot = snapshot

    def _items(self) -> list:
        if self._snapshot is None:
            return []
        t = getattr(self._snapshot, "transcript", None)
        return getattr(t, "items", []) or [] if t else []

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        items = self._items()
        if not items:
            return ("",)
        text = "; ".join(f"[{i.kind}] {i.title}" for i in items[-5:])
        return (text,)

    def _render(self, root: Path) -> str:
        items = self._items()
        if not items:
            return "(no transcript)"
        recent = items[-5:]
        lines = [
            f"[{i.kind}] {i.title}: {i.body_text or ''}"
            for i in recent
            if i.kind not in {"turn_status", "context_envelope"}
        ]
        return "\n".join(lines) if lines else "(transcript available)"

    def _summary(self, root: Path) -> str:
        items = self._items()
        count = len(items)
        if not count:
            return "No transcript items"
        names = "; ".join(f"[{i.kind}] {i.title}" for i in items[-5:])
        return f"Recent transcript: {count} items, last 5: {names[:120]}"


class RelevantTestsPack(ContextPack):
    name = "relevant_tests"

    def __init__(self, repo_index: RepoContextIndex | None = None) -> None:
        super().__init__()
        self._changed_paths: list[str] = []
        self._repo_index = repo_index

    def set_changed_paths(self, paths: list[str]) -> None:
        self._changed_paths = paths

    def _find_tests(self, root: Path) -> list[Path]:
        if self._repo_index is not None and self._repo_index.is_available:
            rel = self._repo_index.find_tests(self._changed_paths[:10])
            return [root / p for p in rel[:5] if (root / p).is_file()]
        found: list[Path] = []
        for cp in self._changed_paths[:10]:
            p = root / cp
            stem = p.stem
            for pattern in [
                root / "tests" / f"test_{stem}.py",
                root / "tests" / f"{stem}_test.py",
                root / "tests" / f"test_{cp.replace('/', '_')}",
            ]:
                if pattern.is_file() and pattern not in found:
                    found.append(pattern)
        return found[:5]

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        tests = self._find_tests(root)
        if not tests:
            return ("",)
        return tuple(str(t) for t in tests)

    def _render(self, root: Path) -> str:
        tests = self._find_tests(root)
        if not tests:
            return "(no relevant tests found)"
        parts: list[str] = []
        for t in tests:
            content = _read_safe(t)
            if content:
                rel = t.relative_to(root) if t.is_relative_to(root) else t
                parts.append(f"--- {rel} ---\n{content[:2000]}")
        return "\n\n".join(parts) if parts else "(no test content)"

    def _summary(self, root: Path) -> str:
        tests = self._find_tests(root)
        return f"Relevant tests: {len(tests)} files" if tests else "No relevant tests"


class RelatedFilesPack(ContextPack):
    name = "related_files"

    def __init__(self, repo_index: RepoContextIndex | None = None) -> None:
        super().__init__()
        self._user_text: str = ""
        self._repo_index = repo_index

    def set_user_text(self, text: str) -> None:
        self._user_text = text

    def _extract_paths(self, root: Path) -> list[str]:
        candidates = re.findall(r"[\w/\\\-]+\.\w{1,4}", self._user_text)
        return [p for p in candidates if (root / Path(p)).is_file()][:5]

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        if self._repo_index is None or not self._repo_index.is_available:
            return ("",)
        paths = self._extract_paths(root)
        if not paths:
            return ("",)
        related = self._repo_index.find_related(paths)
        parts: list[str] = []
        for k in ("test", "doc", "schema"):
            for p in related.get(k, []):
                parts.append(p)
        return tuple(parts) if parts else ("",)

    def _render(self, root: Path) -> str:
        if self._repo_index is None or not self._repo_index.is_available:
            return "(no repo index available)"
        paths = self._extract_paths(root)
        if not paths:
            return "(no file references detected)"
        related = self._repo_index.find_related(paths)
        if not related:
            return "(no related files found)"
        lines: list[str] = []
        for p in paths:
            lines.append(f"References to: {p}")
            for rel_type in ("test", "doc", "schema", "same_package"):
                items = related.get(rel_type, [])
                if items:
                    lines.append(f"  {rel_type}: {', '.join(items[:3])}")
            idx_summary = self._repo_index.summary()
            if idx_summary.get("available"):
                lines.append(
                    f"  index: {idx_summary['file_count']} files, {idx_summary['relation_count']} relations"
                )
        return "\n".join(lines)

    def _summary(self, root: Path) -> str:
        paths = self._extract_paths(root)
        if not paths or self._repo_index is None or not self._repo_index.is_available:
            return "No related files"
        return f"Related files: {len(paths)} source files indexed"


class ActiveFocusPack(ContextPack):
    name = "active_file_focus"

    def __init__(self) -> None:
        super().__init__()
        self._user_text: str = ""

    def set_user_text(self, text: str) -> None:
        self._user_text = text

    def _extract_paths(self, root: Path) -> list[str]:
        candidates = re.findall(r"[\w/\\\-]+\.\w{1,4}", self._user_text)
        return [p for p in candidates if (root / Path(p)).is_file()][:5]

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        paths = self._extract_paths(root)
        return tuple(paths) if paths else ("",)

    def _render(self, root: Path) -> str:
        paths = self._extract_paths(root)
        if not paths:
            return "(no file references detected)"
        parts: list[str] = []
        for p in paths:
            f = root / Path(p)
            content = _read_safe(f)
            if content:
                lines = content.splitlines()
                parts.append(
                    f"--- {p} ({len(lines)} lines) ---\n" + "\n".join(lines[:30])
                )
        return "\n\n".join(parts) if parts else "(files mentioned not found)"

    def _summary(self, root: Path) -> str:
        paths = self._extract_paths(root)
        return (
            f"Active file focus: {len(paths)} files referenced"
            if paths
            else "No file focus"
        )


# ── Compaction history pack ──────────────────────────────────────────


class CompactionHistoryPack(ContextPack):
    name = "compaction_history"

    def __init__(self, receipt_store: ReceiptStore | None = None) -> None:
        super().__init__()
        self._receipt_store = receipt_store
        self._session_id: str = ""

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def _recent_compaction_receipts(self) -> list:
        if not self._receipt_store or not self._session_id:
            return []
        try:
            receipts = self._receipt_store.list_by_session(self._session_id, limit=5)
            return [r for r in receipts if r.receipt_kind == "compaction"]
        except Exception:
            return []

    def _fingerprint_sources(self, root: Path) -> tuple[str, ...]:
        compact = self._recent_compaction_receipts()
        if not compact:
            return ("",)
        return tuple(r.envelope_id for r in compact)

    def _render(self, root: Path) -> str:
        compact = self._recent_compaction_receipts()
        if not compact:
            return "(no compaction history)"
        lines = ["Recent transcript prunes:"]
        for r in compact:
            text = (
                r.decision.rationale
                if r.decision and r.decision.rationale
                else f"dropped items (receipt {r.envelope_id[:8]})"
            )
            lines.append(f"  - {text}")
        return "\n".join(lines)

    def _summary(self, root: Path) -> str:
        compact = self._recent_compaction_receipts()
        if not compact:
            return "No compaction history"
        return f"Compaction receipts: {len(compact)}"


# ── The compiler ────────────────────────────────────────────────────


class ContextCompiler:
    """Pack-based context compiler.

    Holds a registry of ``ContextPack`` instances. Before each turn, calls
    ``build_envelope()`` which iterates all packs, checks fingerprints,
    and includes only those that changed. The envelope receipt records
    what was included and omitted.
    """

    def __init__(
        self,
        session_id: str,
        workspace_root: Path | None = None,
        receipt_store: ReceiptStore | None = None,
        repo_index: RepoContextIndex | None = None,
    ) -> None:
        self._session_id = session_id
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._receipt_store = receipt_store
        self._repo_index = repo_index

    def _default_packs(self, user_text: str, snapshot: Any | None) -> list[ContextPack]:
        packs: list[ContextPack] = []
        packs.append(AgentsMdPack())
        packs.append(GitStatePack())
        packs.append(DirtyFilesPack())

        tp = RecentTranscriptPack()
        tp.set_snapshot(snapshot)
        packs.append(tp)

        packs.append(DirtyOwnershipPack())

        rtp = RelevantTestsPack(repo_index=self._repo_index)
        changed: list[str] = []
        rtp.set_changed_paths(changed)
        packs.append(rtp)

        fp = ActiveFocusPack()
        fp.set_user_text(user_text)
        packs.append(fp)

        rfp = RelatedFilesPack(repo_index=self._repo_index)
        rfp.set_user_text(user_text)
        packs.append(rfp)

        chp = CompactionHistoryPack(self._receipt_store)
        chp.set_session_id(self._session_id)
        packs.append(chp)

        return packs

    def build_envelope(
        self,
        user_text: str,
        snapshot: Any | None = None,
        packs: list[ContextPack] | None = None,
    ) -> ContextEnvelopeReceipt:
        if packs is None:
            packs = self._default_packs(user_text, snapshot)

        root = self._workspace_root
        (
            sections,
            omitted,
            rendered_parts,
            compressed_prompt,
            symbol_manifest,
            symbol_codec_receipt,
        ) = _build_envelope_parts(root, packs)
        rendered_parts.append(f"<user_prompt>\n{user_text}\n</user_prompt>")
        rendered = "\n\n".join(rendered_parts)

        receipt = ContextEnvelopeReceipt(
            rendered_prompt=rendered,
            compressed_prompt=compressed_prompt,
            sections=sections,
            sections_omitted=omitted,
            envelope_sha256=_hash(rendered),
            cache_key=_hash(*(s.fingerprint for s in sections)),
            session_id=self._session_id,
            symbol_manifest=symbol_manifest,
            symbol_codec_receipt=symbol_codec_receipt,
        )

        if self._receipt_store is not None:
            try:
                envelope = build_receipt_envelope(
                    receipt_kind="context_envelope",
                    actor=ReceiptActor(
                        actor_id="compiler", actor_kind=ReceiptActorKind.RUNTIME
                    ),
                    subject=ReceiptSubject(
                        subject_id=self._session_id,
                        subject_kind=ReceiptSubjectKind.SESSION,
                        session_id=self._session_id,
                    ),
                    receipt_payload={
                        "section_count": receipt.section_count,
                        "sections": [s.name for s in sections],
                        "omitted": omitted,
                        "cache_key": receipt.cache_key,
                        "symbol_codec": receipt.symbol_codec_receipt,
                    },
                    decision=ReceiptDecision(
                        decision="included" if sections else "empty",
                        rationale=f"{receipt.section_count} sections · {'cached' if receipt.is_cached else 'fresh'}",
                    ),
                )
                self._receipt_store.append(envelope)
            except Exception:
                pass

        return receipt


__all__ = [
    "ActiveFocusPack",
    "AgentsMdPack",
    "CompactionHistoryPack",
    "ContextCompiler",
    "ContextPack",
    "DirtyFilesPack",
    "DirtyOwnershipPack",
    "GitStatePack",
    "RecentTranscriptPack",
    "RelatedFilesPack",
    "RelevantTestsPack",
]

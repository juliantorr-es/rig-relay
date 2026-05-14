"""CodebaseSymbolDigest — deterministic manifest builder for symbol codec.

Phase 5: scans repo files + docs + schemas, extracts repeated terms,
classifies by kind, measures token savings, emits a measured manifest.
The ContextCompiler uses this manifest when building envelopes.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.context.symbol_codec import SymbolManifest, _iter_candidates


class CodebaseSymbolDigest:
    """Deterministic, content-addressed symbol manifest builder.

    Scans a corpus of text (repo files, docs, schemas, mission packets),
    extracts repeated terms, classifies them by kind, measures token
    savings, and emits a SymbolManifest.

    The manifest includes only entries with positive net token savings
    after accounting for manifest header overhead.
    """

    def __init__(self, corpus: str = "") -> None:
        self._corpus = corpus

    def add_file(self, path: Path) -> None:
        """Read a file and append its text to the digest corpus."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            self._corpus += "\n" + text
        except Exception:
            pass

    def add_text(self, text: str) -> None:
        """Append raw text to the digest corpus."""
        self._corpus += "\n" + text

    def build(
        self,
        min_occurrences: int = 3,
        min_chars: int = 16,
    ) -> SymbolManifest:
        """Build a measured SymbolManifest from the accumulated corpus.

        Returns an empty manifest (no entries) if no candidates found.
        """
        candidates = _iter_candidates(self._corpus, min_occurrences, min_chars)
        if not candidates:
            return SymbolManifest(())
        return _build_manifest_from_candidates(candidates)


def build_digest_from_repo(
    repo_root: Path,
    extra_texts: list[str] | None = None,
    min_occurrences: int = 3,
    min_chars: int = 16,
) -> SymbolManifest:
    """Convenience: scan common repo paths and build a manifest.

    Scans:
    - All Python files under repo_root (top level + vibe/ + rig_relay/ + tests/)
    - docs/ directory
    - AGENTS.md or CLAUDE.md
    - pyproject.toml
    - Extra text strings (e.g. recent mission packets, receipts)
    """
    digest = CodebaseSymbolDigest()

    # Core source paths
    for subdir in ("", "vibe", "rig_relay", "tests"):
        d = repo_root / subdir
        if d.is_dir():
            for f in sorted(d.rglob("*.py")):
                digest.add_file(f)

    # Docs
    docs_root = repo_root / "docs"
    if docs_root.is_dir():
        for f in sorted(docs_root.rglob("*.md")):
            digest.add_file(f)
        schemas_root = docs_root / "schemas"
        if schemas_root.is_dir():
            for f in sorted(schemas_root.rglob("*.json")):
                digest.add_file(f)

    # Config
    for cfg in ("AGENTS.md", "CLAUDE.md", "pyproject.toml"):
        p = repo_root / cfg
        if p.is_file():
            digest.add_file(p)

    if extra_texts:
        for t in extra_texts:
            digest.add_text(t)

    return digest.build(min_occurrences, min_chars)


def _build_manifest_from_candidates(
    candidates: dict[str, int],
) -> SymbolManifest:
    """Build a measured, typed SymbolManifest from raw candidates."""
    from rig_relay.context.symbol_codec import _build_manifest
    return _build_manifest(candidates)


__all__ = [
    "CodebaseSymbolDigest",
    "build_digest_from_repo",
]

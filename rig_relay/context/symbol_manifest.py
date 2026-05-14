"""Deterministic symbol manifest helpers for context compression."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rig_relay.context.symbol_codec import (
    SymbolManifest,
    _build_manifest,
    _iter_candidates,
)


@dataclass(frozen=True, slots=True)
class SymbolManifestBuildResult:
    manifest: SymbolManifest
    source_root_fingerprint: str
    input_count: int
    alias_mode: str


def build_codebase_symbol_manifest(
    repo_root: Path,
    texts: list[str] | None = None,
    *,
    min_occurrences: int = 3,
    min_chars: int = 16,
) -> SymbolManifestBuildResult:
    corpus_parts: list[str] = []
    for subdir in ("vibe", "rig_relay", "tests", "docs"):
        root = repo_root / subdir
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    corpus_parts.append(str(path.relative_to(repo_root)))
    if texts:
        corpus_parts.extend(texts)

    corpus = "\n".join(corpus_parts)
    candidates = _iter_candidates(corpus, min_occurrences, min_chars)
    manifest = _build_manifest(candidates, corpus=corpus, alias_mode="section")
    return SymbolManifestBuildResult(
        manifest=manifest,
        source_root_fingerprint=str(repo_root.resolve()),
        input_count=len(corpus_parts),
        alias_mode="section",
    )

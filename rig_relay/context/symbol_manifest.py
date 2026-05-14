"""Deterministic symbol manifest helpers for context compression."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

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


_DOC_LABEL_PATTERN = re.compile(r"^#+\s+(.+)$", re.MULTILINE)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_python_symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    symbols: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id[:1].isupper():
                    symbols.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id[:1].isupper():
                symbols.append(node.target.id)
    return symbols


def _iter_doc_labels(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    labels = [match.group(1).strip() for match in _DOC_LABEL_PATTERN.finditer(text)]
    return [label for label in labels if label]


def build_codebase_symbol_manifest(
    repo_root: Path,
    texts: list[str] | None = None,
    *,
    min_occurrences: int = 3,
    min_chars: int = 16,
    alias_mode: str = "section",
) -> SymbolManifestBuildResult:
    corpus_parts: list[str] = []
    source_parts: list[str] = []
    for subdir in ("vibe", "rig_relay", "tests", "docs"):
        root = repo_root / subdir
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    relative = str(path.relative_to(repo_root))
                    source_parts.append(relative)
                    corpus_parts.append(relative)
                    if path.suffix == ".py":
                        corpus_parts.extend(_iter_python_symbols(path))
                    elif path.suffix in {".md", ".rst", ".txt"}:
                        corpus_parts.extend(_iter_doc_labels(path))
    if texts:
        corpus_parts.extend(texts)

    corpus = "\n".join(corpus_parts)
    candidates = _iter_candidates(corpus, min_occurrences, min_chars)
    manifest = _build_manifest(candidates, corpus=corpus, alias_mode=alias_mode)
    manifest = SymbolManifest(manifest.entries, seed=_fingerprint(corpus))
    return SymbolManifestBuildResult(
        manifest=manifest,
        source_root_fingerprint=_fingerprint(str(repo_root.resolve())),
        input_count=len(corpus_parts) + len(source_parts),
        alias_mode=alias_mode,
    )

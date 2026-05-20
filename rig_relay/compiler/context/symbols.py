"""SYMBOLS mode — symbol substitution packet compiler.

Wires the existing symbol codec pipeline:
  build_codebase_symbol_manifest() → compress_with_manifest()

Produces a content-light symbol packet with hash-stable manifest,
compressed example, and estimated token savings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rig_relay.context.symbol_codec import compress_with_manifest, estimate_tokens
from rig_relay.context.symbol_manifest import build_codebase_symbol_manifest


def _sample_text(repo_root: Path) -> str:
    """Read a representative file for compression demo."""
    candidates = [
        repo_root / "rig_relay" / "context" / "compiler.py",
        repo_root / "rig_relay" / "context" / "symbol_codec.py",
        repo_root / "rig_relay" / "context" / "models.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                continue
    return ""


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compile_symbol_packet(source_paths: list[str] | None = None) -> dict[str, Any]:
    repo_root = Path.cwd().resolve()

    build_result = build_codebase_symbol_manifest(
        repo_root, min_occurrences=3, min_chars=16
    )
    manifest = build_result.manifest

    symbol_map: dict[str, Any] = {"aliases": {}, "symbols": []}

    if manifest.entries:
        for entry in manifest.entries:
            symbol_map["aliases"][entry.value] = entry.alias
            symbol_map["symbols"].append({
                "id": entry.alias,
                "original": entry.value,
                "namespace": entry.kind,
                "replacement": entry.alias,
            })

    manifest_hash = hashlib.sha256(
        "\n".join(f"{e.alias} {e.kind} {e.value}" for e in manifest.entries).encode(
            "utf-8"
        )
    ).hexdigest()

    sample = _sample_text(repo_root)
    before_sha = _hash_text(sample)
    after_sha = before_sha
    compressed_sample = sample

    if manifest.entries and sample:
        result = compress_with_manifest(sample, manifest)
        compressed_sample = result.compressed_text
        if result.receipt:
            after_sha = _hash_text(result.compressed_text)

    estimated_token_savings = manifest.total_net_savings if manifest.entries else 0

    return {
        "symbol_map": symbol_map,
        "compressed_example": {
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "size_before": len(sample),
            "size_after": len(compressed_sample),
            "estimated_tokens_before": estimate_tokens(sample),
            "estimated_tokens_after": estimate_tokens(compressed_sample),
        },
        "estimated_token_savings": estimated_token_savings,
        "manifest_hash": manifest_hash,
        "manifest_entry_count": len(manifest.entries),
    }

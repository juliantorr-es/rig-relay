"""Deterministic reversible symbol replacement codec for context compression.

Phase 5: typed namespace (§p001, §t001, §s001, §d001, §c001, §m001),
manifest-backed measurement, and tool alias expansion.

Namespaces:
  §p001..§p999  path aliases
  §t001..§t999  type/class/function aliases
  §s001..§s999  schema aliases
  §d001..§d999  doctrine/governance phrase aliases
  §c001..§c999  command/check aliases
  §m001..§m999  mission/workstream aliases
"""

from __future__ import annotations

import hashlib
import re

_SECTION_ESCAPE = "\\u00A7"
_PUA_ESCAPE_PREFIX = "\\uP"
_PUA_BMP_START = 0xE000
_PUA_BMP_END = 0xF8FF
_PUA_SUPPLEMENTARY_START = 0xF0000
_PUA_SUPPLEMENTARY_END = 0xFFFFD
_PUA_SUPPLEMENTARY2_START = 0x100000
_PUA_SUPPLEMENTARY2_END = 0x10FFFD
_PUA_RANGES = [
    range(_PUA_BMP_START, _PUA_BMP_END + 1),
    range(_PUA_SUPPLEMENTARY_START, _PUA_SUPPLEMENTARY_END + 1),
    range(_PUA_SUPPLEMENTARY2_START, _PUA_SUPPLEMENTARY2_END + 1),
]

# ── Typed symbol namespace ─────────────────────────────────────────

_SYMBOL_NAMESPACES: list[tuple[str, str, int]] = [
    ("p", "path", 999),
    ("t", "type", 999),
    ("s", "schema", 999),
    ("d", "doctrine", 999),
    ("c", "command", 999),
    ("m", "mission", 999),
]


def _pua_codepoints() -> list[int]:
    points: list[int] = []
    for rng in _PUA_RANGES:
        points.extend(list(rng))
    return points


def _typed_symbol_sequence(count: int, *, alias_mode: str = "section") -> list[str]:
    """Generate deterministic typed symbol sequence: §p001, §p002, ..., §t001, ..."""
    symbols: list[str] = []
    pua_points = _pua_codepoints()
    for ns, _kind, limit in _SYMBOL_NAMESPACES:
        for i in range(1, min(limit + 1, count - len(symbols) + 1)):
            if alias_mode == "pua":
                symbols.append(chr(pua_points[len(symbols)]))
            else:
                symbols.append(f"§{ns}{i:03d}")
            if len(symbols) >= count:
                return symbols
    return symbols


_SYMBOL_PATTERN = re.compile(r"§[ptscdm]\d{3}")
_ESCAPED_SECTION_MARKER = "\\u00A7"


def _has_symbol_collision(text: str) -> bool:
    """Check if text already contains reserved typed symbols."""
    if _SYMBOL_PATTERN.search(text):
        return True
    return any(_is_pua(ch) for ch in text)


# ── Kind classifier ────────────────────────────────────────────────


def _classify_term(term: str) -> str:
    """Classify a term into a symbol kind.

    Returns one of: "path", "type", "schema", "doctrine", "command", "mission".
    """
    if term.startswith("docs/schemas/") or term.endswith(".schema.json"):
        return "schema"
    if term.startswith("docs/") or term.startswith("CONTEXT") or term.endswith(".md"):
        return "doctrine"
    if "/" in term and (
        "." in term or term.startswith("vibe/") or term.startswith("rig_relay/")
    ):
        return "path"
    if term.endswith((".py", ".js", ".ts", ".rs", ".go", ".java")):
        return "path"
    if term[0].isupper():
        return "type"
    return "doctrine"


def _kind_namespace(kind: str) -> str:
    mapping = {
        "path": "p",
        "type": "t",
        "schema": "s",
        "doctrine": "d",
        "command": "c",
        "mission": "m",
    }
    return mapping.get(kind, "d")


# ── Token estimator ────────────────────────────────────────────────


_CODE_RATIO_THRESHOLD = 0.15


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate. Always >= 1 for non-empty text."""
    if not text:
        return 0
    dense = sum(1 for c in text if c in " \t\n(){}[]<>;:=+-*/%&|!~^,") / max(
        len(text), 1
    )
    if dense > _CODE_RATIO_THRESHOLD:
        return max(1, len(text) // 2)
    return max(1, len(text) // 4)


# ── Public models ──────────────────────────────────────────────────


class ManifestEntry:
    """A single entry in the symbol manifest with measured token costs.

    Attributes:
        alias: The alias (e.g. "§p014").
        kind: Term kind ("path", "type", "schema", "doctrine", "command", "mission").
        value: The original text being aliased.
        occurrences: How many times the value appears.
        source_token_cost: Token cost of the original value × occurrences.
        alias_token_cost: Token cost of the alias × occurrences.
        manifest_overhead: Token cost of including this entry in the manifest header.
        net_savings: source_token_cost - alias_token_cost - manifest_overhead.
    """

    def __init__(
        self,
        alias: str,
        kind: str,
        value: str,
        occurrences: int,
        source_token_cost: int,
        alias_token_cost: int,
        manifest_overhead: int,
        net_savings: int,
    ) -> None:
        self.alias = alias
        self.kind = kind
        self.value = value
        self.occurrences = occurrences
        self.source_token_cost = source_token_cost
        self.alias_token_cost = alias_token_cost
        self.manifest_overhead = manifest_overhead
        self.net_savings = net_savings

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ManifestEntry):
            return NotImplemented
        return (self.alias, self.value) == (other.alias, other.value)

    def __hash__(self) -> int:
        return hash((self.alias, self.value))


class SymbolManifest:
    """A measured, typed symbol manifest.

    Attributes:
        entries: Ordered tuple of ManifestEntry with positive net_savings.
        manifest_sha256: SHA256 of the serialized manifest.
        total_source_tokens: Sum of source_token_cost across all entries.
        total_alias_tokens: Sum of alias_token_cost across all entries.
        total_overhead: Sum of manifest_overhead across all entries.
        total_net_savings: Sum of net_savings across all entries.
    """

    def __init__(self, entries: tuple[ManifestEntry, ...]) -> None:
        self.entries = entries
        serialized = "\n".join(f"{e.alias} {e.kind} {e.value}" for e in entries)
        self.manifest_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.total_source_tokens = sum(e.source_token_cost for e in entries)
        self.total_alias_tokens = sum(e.alias_token_cost for e in entries)
        self.total_overhead = sum(e.manifest_overhead for e in entries)
        self.total_net_savings = sum(e.net_savings for e in entries)

    def to_table(self) -> list[dict]:
        return [
            {
                "alias": e.alias,
                "kind": e.kind,
                "value": e.value,
                "occurrences": e.occurrences,
                "source_token_cost": e.source_token_cost,
                "alias_token_cost": e.alias_token_cost,
                "manifest_overhead": e.manifest_overhead,
                "net_savings": e.net_savings,
            }
            for e in self.entries
        ]


class SymbolCodecResult:
    def __init__(
        self,
        original_text: str,
        compressed_text: str,
        manifest: SymbolManifest | None = None,
        receipt: SymbolCodecReceipt | None = None,
        refused_reason: str | None = None,
    ) -> None:
        self.original_text = original_text
        self.compressed_text = compressed_text
        self.manifest = manifest
        self.receipt = receipt
        self.refused_reason = refused_reason


class SymbolCodecReceipt:
    def __init__(
        self,
        input_sha256: str = "",
        output_sha256: str = "",
        manifest_sha256: str = "",
        estimated_tokens_before: int = 0,
        estimated_tokens_after: int = 0,
        replacement_count: int = 0,
        refused_reason: str | None = None,
        codec_name: str = "rig.symbol.v1",
        codec_version: str = "1",
    ) -> None:
        self.codec_name = codec_name
        self.codec_version = codec_version
        self.input_sha256 = input_sha256
        self.output_sha256 = output_sha256
        self.manifest_sha256 = manifest_sha256
        self.estimated_tokens_before = estimated_tokens_before
        self.estimated_tokens_after = estimated_tokens_after
        self.replacement_count = replacement_count
        self.reversible = True
        self.lossy = False
        self.refused_reason = refused_reason


# ── Helpers ────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_candidates(
    text: str, min_occurrences: int = 3, min_chars: int = 16
) -> dict[str, int]:
    counts: dict[str, int] = {}
    term_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_.\\/]{7,}")
    for match in term_pattern.finditer(text):
        term = match.group(0)
        if len(term) < min_chars:
            continue
        counts[term] = counts.get(term, 0) + 1
    return {t: c for t, c in counts.items() if c >= min_occurrences}


def _sort_by_savings(candidates: dict[str, int]) -> list[tuple[str, int, int]]:
    scored: list[tuple[str, int, int]] = []
    for term, count in candidates.items():
        saved = max(0, (len(term) - 5)) * count  # alias is ~5 chars (§p001)
        scored.append((term, count, saved))
    scored.sort(key=lambda x: (-x[2], -x[1]))
    return scored


# ── Core codec functions ───────────────────────────────────────────


def compress_with_manifest(
    text: str, manifest: SymbolManifest | None = None, *, alias_mode: str = "section"
) -> SymbolCodecResult:
    """Compress text using a pre-built symbol manifest.

    If no manifest is provided, builds one on-the-fly from the text itself.
    """
    input_sha = _sha256(text)
    before = estimate_tokens(text)

    if manifest is None:
        candidates = _iter_candidates(text)
        if not candidates:
            return _refused(text, input_sha, before, "No candidates found")
        manifest = _build_manifest(candidates, text, alias_mode=alias_mode)

    if not manifest.entries:
        return _refused(text, input_sha, before, "No entries with positive net savings")

    entries = manifest.entries
    compressed = _escape_alias_chars(text, alias_mode)
    for entry in sorted(entries, key=lambda e: (-len(e.value), e.value)):
        compressed = compressed.replace(entry.value, entry.alias)

    after = estimate_tokens(compressed)
    receipt = SymbolCodecReceipt(
        input_sha256=input_sha,
        output_sha256=_sha256(compressed),
        manifest_sha256=manifest.manifest_sha256,
        estimated_tokens_before=before,
        estimated_tokens_after=after,
        replacement_count=sum(e.occurrences for e in entries),
    )
    return SymbolCodecResult(
        original_text=text,
        compressed_text=compressed,
        manifest=manifest,
        receipt=receipt,
    )


def _refused(text: str, input_sha: str, before: int, reason: str) -> SymbolCodecResult:
    return SymbolCodecResult(
        original_text=text,
        compressed_text=text,
        receipt=SymbolCodecReceipt(
            input_sha256=input_sha,
            output_sha256=input_sha,
            estimated_tokens_before=before,
            estimated_tokens_after=before,
            refused_reason=reason,
        ),
        refused_reason=reason,
    )


def _build_manifest(
    candidates: dict[str, int], corpus: str = "", *, alias_mode: str = "section"
) -> SymbolManifest:
    """Build a measured, typed SymbolManifest from raw candidates."""
    scored = _sort_by_savings(candidates)
    # Generate symbols across namespaces to cover all kinds
    symbols = _typed_symbol_sequence(
        max(len(scored) + len(_SYMBOL_NAMESPACES), 50), alias_mode=alias_mode
    )
    entries: list[ManifestEntry] = []

    for i, (term, count, _saved) in enumerate(scored):
        if i >= len(symbols):
            break
        kind = _classify_term(term)
        alias = symbols[i]

        source_cost = estimate_tokens(term) * count
        alias_cost = estimate_tokens(alias) * count
        overhead = estimate_tokens(f"{alias} {term}\n")
        net = source_cost - alias_cost - overhead
        if net <= 0:
            continue

        entries.append(
            ManifestEntry(
                alias=alias,
                kind=kind,
                value=term,
                occurrences=count,
                source_token_cost=source_cost,
                alias_token_cost=alias_cost,
                manifest_overhead=overhead,
                net_savings=net,
            )
        )

    return SymbolManifest(tuple(entries))


def decompress_symbols(
    compressed_text: str, manifest: SymbolManifest, *, alias_mode: str = "section"
) -> str:
    """Restore original text from compressed text and manifest.

    Sort by value length descending to avoid partial matches.
    """
    result = compressed_text
    for entry in sorted(manifest.entries, key=lambda e: (-len(e.value), e.value)):
        result = result.replace(entry.alias, entry.value)
    return _unescape_alias_chars(result, alias_mode)


def expand_aliases(text: str, manifest: SymbolManifest) -> str:
    """Expand all aliases in text back to their original values.

    Must be called before passing text to file system tools, bash,
    search_replace, or any tool that receives unresolved paths.
    """
    return decompress_symbols(text, manifest)


def _escape_alias_chars(text: str, alias_mode: str) -> str:
    if alias_mode == "pua":
        return "".join(
            f"{_PUA_ESCAPE_PREFIX}{ord(ch):04X}" if _is_pua(ch) else ch for ch in text
        )
    return text.replace("§", _SECTION_ESCAPE)


def _unescape_alias_chars(text: str, alias_mode: str) -> str:
    if alias_mode == "pua":

        def repl(match: re.Match[str]) -> str:
            return chr(int(match.group(1), 16))

        return re.sub(r"\\uP([0-9A-Fa-f]{4,6})", repl, text)
    return text.replace(_SECTION_ESCAPE, "§")


def _is_pua(ch: str) -> bool:
    codepoint = ord(ch)
    return (
        _PUA_BMP_START <= codepoint <= _PUA_BMP_END
        or _PUA_SUPPLEMENTARY_START <= codepoint <= _PUA_SUPPLEMENTARY_END
        or _PUA_SUPPLEMENTARY2_START <= codepoint <= _PUA_SUPPLEMENTARY2_END
    )


def find_candidates(
    text: str, min_occurrences: int = 3, min_chars: int = 16
) -> tuple[ManifestEntry, ...]:
    """Find candidate terms without modifying text. Returns measured entries."""
    candidates = _iter_candidates(text, min_occurrences, min_chars)
    if not candidates:
        return ()
    manifest = _build_manifest(candidates, text)
    return manifest.entries


__all__ = [
    "ManifestEntry",
    "SymbolCodecReceipt",
    "SymbolCodecResult",
    "SymbolManifest",
    "compress_with_manifest",
    "decompress_symbols",
    "estimate_tokens",
    "expand_aliases",
    "find_candidates",
]

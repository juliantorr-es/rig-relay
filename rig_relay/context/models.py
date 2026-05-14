"""Context envelope models for deterministic prompt compilation.

A ContextEnvelopeReceipt records what context was included (and omitted)
when a user prompt was compiled into a rendered prompt. It is itself a
receipt-backed artifact — content-light, deterministic, and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from rig_relay.context.symbol_codec import SymbolManifest


@dataclass(frozen=True, slots=True)
class ContextSection:
    """A single section of context included in the compiled prompt.

    Content-light: carries only the section name, a content fingerprint,
    and a human-readable summary of what was included.
    """

    name: str
    fingerprint: str
    summary: str


@dataclass(frozen=True, slots=True)
class ContextEnvelopeReceipt:
    """Receipt recording what context was compiled for a single turn.

    The ``rendered_prompt`` is what gets passed to AgentLoop.act().
    The ``sections`` list records what was included.
    The ``sections_omitted`` list records what was available but not included.
    The ``envelope_sha256`` fingerprints the rendered prompt for caching.
    """

    rendered_prompt: str
    compressed_prompt: str = ""
    sections: list[ContextSection] = field(default_factory=list)
    sections_omitted: list[str] = field(default_factory=list)
    envelope_sha256: str = ""
    cache_key: str | None = None
    session_id: str = ""
    symbol_manifest: SymbolManifest | None = None
    symbol_codec_receipt: dict[str, str | int | bool | None] | None = None
    receipt_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def is_cached(self) -> bool:
        return self.cache_key is not None


__all__ = ["ContextEnvelopeReceipt", "ContextSection"]

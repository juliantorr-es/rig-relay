"""Heuristic token estimator for context codec pipeline.

Phase 4: model-agnostic fallback. Uses character-based heuristics.
Future: model-specific estimators via tiktoken adapter.
"""

from __future__ import annotations


def estimate_tokens(text: str, model_hint: str | None = None) -> int:
    """Estimate token count for a text string.

    Uses heuristic character-based estimation when no model-specific
    tokenizer is available. Applies a weighted average: most text is
    ~3 chars/token; very code-dense text (more punctuation than
    alphanumeric) can approach ~2 chars/token.

    Args:
        text: The text to estimate.
        model_hint: Optional model identifier (e.g. "gpt-4", "claude-3").
            Currently unused; reserved for future tiktoken adapter.

    Returns:
        Estimated token count (always >= 1 for non-empty text).
    """
    if not text:
        return 0

    _ = model_hint  # reserved for future model-specific estimator

    alpha = sum(1 for c in text if c.isalnum() or c.isspace())
    punct = max(1, len(text) - alpha)
    _DENSE = 0.5
    _MIXED = 0.25
    ratio = punct / max(len(text), 1)
    if ratio > _DENSE:
        return max(1, len(text) // 2)
    if ratio > _MIXED:
        return max(1, int(len(text) / 2.5))
    return max(1, len(text) // 4)


__all__ = ["estimate_tokens"]

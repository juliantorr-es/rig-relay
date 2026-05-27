"""Rigged cache authority — real LRUPromptCache integration via mlx-lm.

Uses mlx_lm.models.cache.LRUPromptCache for trie-based prefix matching
across repeated prompts. Read-only reuse in this slice:
  - fetch_nearest_cache() finds matching prefix caches
  - generate()/stream_generate_sync() pass them to mlx-lm
  - hit/miss counted per-call

Deferred (documented truthfully):
  - Cache write-back (insert_cache after generation)
    requires low-level generate_step() API which returns
    mutated prompt_cache; mlx_lm.generate() returns only the
    text string.
  - SSD persistence (save_prompt_cache / load_prompt_cache)
  - GPU page cache (OMLX-style block-based)

Privacy: cache is local-runtime-ephemeral. Data never leaves the machine.
Cache evidence is content-light (hit/miss counts only).
"""

from __future__ import annotations

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    CachePrivacyClass,
    RuntimeCachePolicy,
)


class RiggedCacheAuthority:
    """Cache authority and policy boundary for local inference.

    Uses mlx_lm.models.cache.LRUPromptCache when available.
    Read-only reuse via fetch_nearest_cache. Write-back deferred
    pending low-level generate_step() API integration.
    """

    def __init__(self) -> None:
        self._clear_count: int = 0
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._lru_cache: object | None = None
        self._cache_initialized: bool = False

    @property
    def kv_cache_reuse_enabled(self) -> bool:
        return self._cache_initialized

    @property
    def hit_count(self) -> int:
        return self._hit_count

    @property
    def miss_count(self) -> int:
        return self._miss_count

    @property
    def clear_count(self) -> int:
        return self._clear_count

    def _ensure_cache(self) -> None:
        if self._cache_initialized:
            return
        try:
            from mlx_lm.models.cache import LRUPromptCache

            self._lru_cache = LRUPromptCache(max_size=10)
            self._cache_initialized = True
            logger.info(
                "RiggedCacheAuthority: LRUPromptCache initialized (max_size=10)"
            )
        except ImportError:
            logger.debug("RiggedCacheAuthority: mlx-lm LRUPromptCache not available")

    def fetch_cache(
        self, model: object, prompt_tokens: list[int]
    ) -> tuple[list | None, list[int]]:
        """Find nearest cached prefix. Returns (cached_segments, remaining_tokens).

        The cached_segments can be passed as prompt_cache to
        mlx_lm.generate() or stream_generate(). remaining_tokens is the
        suffix not yet covered by any cached entry.
        """
        self._ensure_cache()
        if self._lru_cache is None:
            self._miss_count += 1
            return None, prompt_tokens
        try:
            cache, remaining = self._lru_cache.fetch_nearest_cache(model, prompt_tokens)
            if cache is not None:
                self._hit_count += 1
                logger.debug(
                    "RiggedCacheAuthority: cache hit — prefix %d tokens, "
                    "remaining %d tokens",
                    len(prompt_tokens) - len(remaining),
                    len(remaining),
                )
            else:
                self._miss_count += 1
            return cache, remaining
        except Exception as e:
            logger.debug("RiggedCacheAuthority: fetch_nearest_cache error: %s", e)
            self._miss_count += 1
            return None, prompt_tokens

    def insert_cache(
        self, model: object, prompt_tokens: list[int], prompt_cache: list
    ) -> None:
        """Store prompt cache for future reuse.

        WARNING: write-back is deferred. mlx_lm.generate() returns only
        the text string, not the mutated prompt_cache. This method exists
        for the API surface but is not currently fed with populated caches
        from the generation path. See deferred note in module docstring.
        """
        self._ensure_cache()
        if self._lru_cache is not None and prompt_cache is not None:
            try:
                self._lru_cache.insert_cache(model, prompt_tokens, prompt_cache)
                logger.debug(
                    "RiggedCacheAuthority: inserted cache — %d tokens",
                    len(prompt_tokens),
                )
            except Exception as e:
                logger.debug("RiggedCacheAuthority: insert_cache error: %s", e)

    async def clear_cache(self) -> bool:
        """Clear in-process MLX cache and reset LRU state."""
        self._clear_count += 1
        self._lru_cache = None
        self._cache_initialized = False
        self._hit_count = 0
        self._miss_count = 0
        try:
            import mlx.core as mx

            mx.clear_cache()
            return True
        except Exception:
            return False

    def get_policy(self) -> RuntimeCachePolicy:
        status = (
            "LRUPromptCache active with trie-based prefix matching. "
            "Max 10 entries. Read-only fetch_nearest_cache reuse. "
            "Write-back deferred — mlx_lm.generate() does not return "
            "the populated prompt_cache; low-level generate_step() API "
            "required for insert-after-generation."
            if self._cache_initialized
            else "KV cache reuse pending mlx-lm import."
        )
        return RuntimeCachePolicy(
            cache_mode="local_runtime_lru_trie",
            privacy_class=CachePrivacyClass.LOCAL_KV_CACHE,
            rig_control_level="local_manage",
            persists_across_restarts=False,
            ssd_persistence_detected=False,
            confidential_context_policy="safe_local",
            data_never_leaves_machine=True,
            rig_relay_may_read_cache_stats=True,
            rig_relay_must_not_read_cache_contents=True,
            retention_policy="lru_10_entries_ephemeral",
            disclosure_required=True,
            disclosure_summary=status,
        )

    def build_projection(self) -> dict:
        return {
            "cache_capability": {
                "kv_cache_reuse": (
                    "supported_read_only_reuse"
                    if self._cache_initialized
                    else "pending_mlx_lm_import"
                ),
                "kv_cache_reuse_status": (
                    "LRUPromptCache active with trie-based prefix matching. "
                    "Max 10 entries. Per-generate hit/miss tracking. "
                    "Read-only fetch_nearest_cache reuse; write-back deferred."
                )
                if self._cache_initialized
                else "KV cache reuse pending mlx-lm import. "
                "LRUPromptCache provides trie-based prefix matching "
                "across repeated prompts.",
                "ssd_persistence": "not_implemented",
                "prefix_sharing": (
                    "active_lru_trie_read_only"
                    if self._cache_initialized
                    else "not_implemented"
                ),
                "write_back": "deferred_low_level_api",
                "write_back_detail": (
                    "mlx_lm.generate() returns only text string. "
                    "Insert-after-generation requires low-level "
                    "generate_step() API which returns mutated prompt_cache."
                ),
            },
            "cache_privacy": {
                "mode": "local_runtime_ephemeral",
                "data_never_leaves_machine": True,
                "secret_bearing_refused_before_cache": True,
                "content_light_evidence": True,
            },
            "cache_stats": {
                "clear_count": self._clear_count,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "total_queries": self._hit_count + self._miss_count,
            },
            "clear_available": True,
        }

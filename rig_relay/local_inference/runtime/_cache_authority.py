"""Rigged cache authority — LRUPromptCache + trie prefix matching + SSD persistence.

Primary: mlx_lm.models.cache.LRUPromptCache for trie-based prefix matching
across repeated prompts. Write-back uses local trie store fed by generation
results. SSD persistence via save_prompt_cache / load_prompt_cache.

Privacy: cache is local-runtime-ephemeral. Data never leaves the machine.
Cache evidence is content-light (hit/miss counts only).

OMLX-informed: LRUPromptCache usage, PromptTrie prefix matching (Apache 2.0).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    CachePrivacyClass,
    RuntimeCachePolicy,
    SSDCacheState,
)


class RiggedCacheAuthority:
    """Cache authority and policy boundary for local inference.

    Uses mlx_lm.models.cache.LRUPromptCache when available for read-only reuse.
    Local trie-based store for write-back cache management.
    SSD persistence via save_prompt_cache / load_prompt_cache.
    """

    def __init__(
        self,
        ssd_cache_dir: str = "",
        ssd_enabled: bool = False,
        max_ssd_entries: int = 50,
    ) -> None:
        self._clear_count: int = 0
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._write_back_count: int = 0
        self._lru_cache: object | None = None
        self._cache_initialized: bool = False
        self._cache_store: dict[str, list[object]] = {}
        self._prompt_hashes: dict[str, list[int]] = {}
        self._ssd_cache_dir: str = ssd_cache_dir
        self._ssd_enabled: bool = ssd_enabled
        self._max_ssd_entries: int = max_ssd_entries
        self._ssd_entries_count: int = 0
        self._ssd_total_size_mb: float = 0.0

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

    @property
    def write_back_count(self) -> int:
        return self._write_back_count

    @property
    def ssd_enabled(self) -> bool:
        return self._ssd_enabled and bool(self._ssd_cache_dir)

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

    def _model_key(self, model: object) -> str:
        return f"sha256:{hashlib.sha256(str(id(model)).encode()).hexdigest()[:16]}"

    def _prompt_prefix_hash(self, tokens: list[int]) -> str:
        return f"sha256:{hashlib.sha256(str(tokens).encode()).hexdigest()[:16]}"

    def fetch_cache(
        self, model: object, prompt_tokens: list[int]
    ) -> tuple[list | None, list[int]]:
        """Find nearest cached prefix. Returns (cached_segments, remaining_tokens).

        Tries LRUPromptCache first (real prefix matching). Falls back to local
        trie-based prefix matching.
        """
        self._ensure_cache()
        if self._lru_cache is not None:
            try:
                cache, remaining = self._lru_cache.fetch_nearest_cache(
                    model, prompt_tokens
                )
                if cache is not None:
                    self._hit_count += 1
                    logger.debug(
                        "RiggedCacheAuthority: LRU cache hit — prefix %d tokens, "
                        "remaining %d tokens",
                        len(prompt_tokens) - len(remaining),
                        len(remaining),
                    )
                    return cache, remaining
            except Exception as e:
                logger.debug("RiggedCacheAuthority: LRU fetch error: %s", e)

        model_key = self._model_key(model)
        if model_key in self._prompt_hashes:
            stored = self._prompt_hashes[model_key]
            match_len = 0
            for i, tok in enumerate(stored):
                if i < len(prompt_tokens) and tok == prompt_tokens[i]:
                    match_len = i + 1
                else:
                    break
            if match_len > 0 and model_key in self._cache_store:
                self._hit_count += 1
                logger.debug(
                    "RiggedCacheAuthority: trie cache hit — matched %d tokens",
                    match_len,
                )
                return (self._cache_store[model_key], prompt_tokens[match_len:])

        self._miss_count += 1
        return None, prompt_tokens

    def insert_cache(
        self,
        model: object,
        prompt_tokens: list[int],
        prompt_cache: list | object,
        privacy_class: str = "",
    ) -> None:
        """Store prompt cache for future reuse.

        Inserts into LRUPromptCache and local trie store. If SSD persistence
        is enabled, also writes to disk via save_prompt_cache.

        Refuses cache insertion for secret-bearing context — prompt tokens
        are reversible with the tokenizer and must not be persisted.
        """
        self._ensure_cache()
        if prompt_cache is None:
            return

        if privacy_class == "secret_bearing":
            logger.warning(
                "RiggedCacheAuthority: refusing cache insertion — "
                "privacy_class=secret_bearing. Token IDs are reversible "
                "with the tokenizer and must not be persisted."
            )
            return

        if isinstance(prompt_cache, list):
            cache_list = prompt_cache
        else:
            cache_list = [prompt_cache]

        if self._lru_cache is not None:
            try:
                self._lru_cache.insert_cache(model, prompt_tokens, cache_list)
                self._write_back_count += 1
                logger.debug(
                    "RiggedCacheAuthority: LRU insert — %d tokens", len(prompt_tokens)
                )
            except Exception as e:
                logger.debug("RiggedCacheAuthority: LRU insert error: %s", e)

        model_key = self._model_key(model)
        self._cache_store[model_key] = cache_list
        self._prompt_hashes[model_key] = prompt_tokens

        if self.ssd_enabled:
            self._save_to_disk(model_key, prompt_tokens, cache_list)

    def _save_to_disk(
        self, model_key: str, prompt_tokens: list[int], cache_list: list
    ) -> None:
        if not self._ssd_cache_dir:
            return
        try:
            from mlx_lm.models.cache import save_prompt_cache

            prompt_hash = self._prompt_prefix_hash(prompt_tokens)
            cache_dir = (
                Path(self._ssd_cache_dir) / model_key.replace("sha256:", "")[:16]
            )
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = (
                cache_dir / f"{prompt_hash.replace('sha256:', '')[:16]}.safetensors"
            )

            save_prompt_cache(str(cache_path), cache_list)
            self._ssd_entries_count += 1

            if cache_path.exists():
                self._ssd_total_size_mb += cache_path.stat().st_size / (1024 * 1024)

            self._evict_ssd_if_needed()

            logger.debug(
                "RiggedCacheAuthority: SSD cache saved — %s (%d bytes)",
                cache_path.name,
                cache_path.stat().st_size if cache_path.exists() else 0,
            )
        except Exception as e:
            logger.debug("RiggedCacheAuthority: SSD save error: %s", e)

    def _load_from_disk(self, model_key: str, prompt_tokens: list[int]) -> list | None:
        if not self._ssd_cache_dir:
            return None
        try:
            from mlx_lm.models.cache import load_prompt_cache

            prompt_hash = self._prompt_prefix_hash(prompt_tokens)
            cache_dir = (
                Path(self._ssd_cache_dir) / model_key.replace("sha256:", "")[:16]
            )
            cache_path = (
                cache_dir / f"{prompt_hash.replace('sha256:', '')[:16]}.safetensors"
            )

            if cache_path.exists():
                from typing import cast

                return cast(list, load_prompt_cache(str(cache_path)))
        except Exception as e:
            logger.debug("RiggedCacheAuthority: SSD load error: %s", e)
        return None

    def _evict_ssd_if_needed(self) -> None:
        if self._ssd_entries_count <= self._max_ssd_entries:
            return
        try:
            cache_root = Path(self._ssd_cache_dir)
            all_cache_files: list[tuple[float, Path]] = []
            for sf in cache_root.rglob("*.safetensors"):
                all_cache_files.append((sf.stat().st_mtime, sf))
            all_cache_files.sort()
            to_remove = max(0, len(all_cache_files) - self._max_ssd_entries)
            for _, sf in all_cache_files[:to_remove]:
                sf.unlink()
                self._ssd_entries_count -= 1
            self._recalc_ssd_size()
        except Exception:
            pass

    def _recalc_ssd_size(self) -> None:
        try:
            total = 0.0
            count = 0
            for sf in Path(self._ssd_cache_dir).rglob("*.safetensors"):
                total += sf.stat().st_size / (1024 * 1024)
                count += 1
            self._ssd_total_size_mb = total
            self._ssd_entries_count = count
        except Exception:
            pass

    async def clear_cache(self) -> bool:
        """Clear in-process MLX cache and reset LRU state.

        This is the corruption/recovery path: on detection of corrupt cache
        state (e.g., mismatched safetensors, stale PromptTrie entries,
        corrupted MLX array formats), call clear_cache() to wipe all cache
        entries and reset to a clean state. After clearing, the next
        generation will rebuild the cache from scratch.
        """
        self._clear_count += 1
        self._lru_cache = None
        self._cache_initialized = False
        self._hit_count = 0
        self._miss_count = 0
        self._write_back_count = 0
        self._cache_store.clear()
        self._prompt_hashes.clear()
        try:
            import mlx.core as mx

            mx.clear_cache()
            return True
        except Exception:
            return False

    def mark_corrupt_entry(self, model_id_hash: str) -> bool:
        """Mark a specific model's cache entries for removal.

        Intended as a targeted corruption recovery path. When a specific
        model's cache is detected as corrupt (e.g., checkpoint version
        mismatch, truncated safetensors), call this to remove that model's
        entries from the in-memory trie store without clearing the entire
        cache.

        Returns True if entries existed and were removed, False otherwise.

        Note: Cache store keys are derived from id(model) rather than
        model_id_hash, so this method cannot perform exact key matching.
        A future iteration will add a model_id_hash→cache_key reverse map.
        For now, clear_cache() is the only guaranteed recovery path.
        """
        _ = model_id_hash
        logger.warning(
            "RiggedCacheAuthority: mark_corrupt_entry is a scaffold — "
            "cache keys are object-id-based, not model_id_hash-based. "
            "Use clear_cache() for full recovery until reverse-key "
            "mapping is implemented."
        )
        return False

    def get_policy(self) -> RuntimeCachePolicy:
        lru_active = self._cache_initialized
        ssd_active = self.ssd_enabled
        wb_active = self._write_back_count > 0

        status_parts: list[str] = []
        if lru_active:
            status_parts.append(
                "LRUPromptCache active with trie-based prefix matching (max 10 entries)"
            )
        if ssd_active:
            status_parts.append(
                f"SSD persistence active ({self._ssd_entries_count} entries, "
                f"{self._ssd_total_size_mb:.1f} MB)"
            )
        if wb_active:
            status_parts.append("Write-back active via local trie cache store")
        if not lru_active:
            status_parts.append("KV cache reuse pending mlx-lm import")
        if not ssd_active:
            status_parts.append("SSD persistence disabled")
        if not wb_active and lru_active:
            status_parts.append(
                "Write-back pending — requires generation to feed prompt_cache "
                "into insertion path"
            )

        return RuntimeCachePolicy(
            cache_mode="local_runtime_lru_trie"
            if lru_active
            else "local_runtime_trie_only",
            privacy_class=(
                CachePrivacyClass.LOCAL_SSD_CACHE
                if ssd_active
                else CachePrivacyClass.LOCAL_KV_CACHE
            ),
            rig_control_level="local_manage",
            persists_across_restarts=ssd_active,
            ssd_persistence_detected=ssd_active,
            confidential_context_policy="safe_local",
            data_never_leaves_machine=True,
            rig_relay_may_read_cache_stats=True,
            rig_relay_must_not_read_cache_contents=True,
            retention_policy=(
                f"lru_10_entries_ephemeral + ssd_{self._max_ssd_entries}_entries"
                if ssd_active
                else "lru_10_entries_ephemeral"
            ),
            disclosure_required=True,
            disclosure_summary="; ".join(status_parts),
        )

    def get_ssd_state(self) -> SSDCacheState:
        return SSDCacheState(
            enabled=self.ssd_enabled,
            cache_dir=self._ssd_cache_dir,
            entries=self._ssd_entries_count,
            total_size_mb=round(self._ssd_total_size_mb, 2),
            max_entries=self._max_ssd_entries,
        )

    def build_projection(self) -> dict:
        lru_active = self._cache_initialized
        wb_count = self._write_back_count

        reuse_status = (
            "supported_read_only_reuse" if lru_active else "pending_mlx_lm_import"
        )

        return {
            "cache_capability": {
                "kv_cache_reuse": reuse_status,
                "kv_cache_reuse_status": (
                    "LRUPromptCache active with trie-based prefix matching. "
                    "Max 10 entries. Per-generate hit/miss tracking. "
                    "Write-back: "
                    + (
                        f"active ({wb_count} insertions)"
                        if wb_count > 0
                        else "deferred — requires generation feeding prompt_cache"
                    )
                )
                if lru_active
                else "KV cache reuse pending mlx-lm import. "
                "LRUPromptCache provides trie-based prefix matching "
                "across repeated prompts.",
                "ssd_persistence": (
                    "active" if self.ssd_enabled else "not_implemented"
                ),
                "ssd_persistence_detail": (
                    f"{self._ssd_entries_count} entries, "
                    f"{self._ssd_total_size_mb:.1f} MB, "
                    f"max {self._max_ssd_entries}"
                )
                if self.ssd_enabled
                else "SSD persistence disabled. Enable with ssd_cache_dir.",
                "prefix_sharing": (
                    "active_lru_trie_read_only" if lru_active else "not_implemented"
                ),
                "write_back": (
                    "active_local_trie" if wb_count > 0 else "deferred_low_level_api"
                ),
                "write_back_detail": (
                    f"Local trie cache store with {wb_count} insertions. "
                    "LRUPromptCache feed from generation result prompt_cache."
                )
                if wb_count > 0
                else (
                    "mlx_lm.generate()/stream_generate() return only text string "
                    "without the mutated prompt_cache. Insert-after-generation "
                    "requires prompt_cache from the generation path. "
                    "BatchGenerator.remove(return_prompt_caches=True) provides "
                    "this capability when batching is active."
                ),
            },
            "cache_privacy": {
                "mode": (
                    "local_runtime_ephemeral_with_ssd"
                    if self.ssd_enabled
                    else "local_runtime_ephemeral"
                ),
                "data_never_leaves_machine": True,
                "secret_bearing_refused_before_cache": True,
                "content_light_evidence": True,
            },
            "cache_stats": {
                "clear_count": self._clear_count,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "write_back_count": self._write_back_count,
                "total_queries": self._hit_count + self._miss_count,
            },
            "clear_available": True,
            "ssd_cache": {
                "enabled": self.ssd_enabled,
                "default": "disabled_opt_in_only",
                "privacy_posture": "token_ids_only_no_raw_text",
                "reversibility_warning": (
                    "Token IDs in cache are reversible with the tokenizer. "
                    "SSD persistence is opt-in only. Set ssd_enabled=True and "
                    "provide ssd_cache_dir to enable."
                ),
                "privacy_detail": (
                    "Cache stores KV state as MLX arrays (binary) and token IDs "
                    "in the PromptTrie. No raw prompt text is stored. However, "
                    "token IDs are reversible if the tokenizer is available."
                ),
                "entries": self._ssd_entries_count,
                "total_size_mb": round(self._ssd_total_size_mb, 2),
                "max_entries": self._max_ssd_entries,
                "cache_dir": self._ssd_cache_dir,
            },
        }

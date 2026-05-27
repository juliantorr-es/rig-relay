"""Rigged cache authority boundary for local inference runtime.

Truthful status: KV cache reuse not yet implemented. In-memory mlx-lm
generation uses per-call ephemeral cache (not reusable across requests).

Privacy: local cache is not cloud retention. Secret-bearing input is
refused before cache population. Cache evidence is content-light.

Future: OMLX-informed GPU page cache + SSD persistence + prefix sharing.
"""

from __future__ import annotations

from rig_relay.local_inference.runtime._models import (
    CachePrivacyClass,
    RuntimeCachePolicy,
)


class RiggedCacheAuthority:
    """Cache authority and policy boundary for local inference.

    Honest status reporting: KV cache reuse is pending.
    The mlx-lm runtime uses in-process ephemeral cache per generation
    call — strongest privacy but no reuse across requests.
    """

    def __init__(self) -> None:
        self._clear_count: int = 0
        self._kv_cache_reuse_enabled: bool = False

    @property
    def kv_cache_reuse_enabled(self) -> bool:
        return self._kv_cache_reuse_enabled

    @property
    def clear_count(self) -> int:
        return self._clear_count

    def get_policy(self) -> RuntimeCachePolicy:
        return RuntimeCachePolicy(
            cache_mode="local_runtime_ephemeral",
            privacy_class=CachePrivacyClass.LOCAL_KV_CACHE,
            rig_control_level="local_manage",
            persists_across_restarts=False,
            ssd_persistence_detected=False,
            confidential_context_policy="safe_local",
            data_never_leaves_machine=True,
            rig_relay_may_read_cache_stats=True,
            rig_relay_must_not_read_cache_contents=True,
            retention_policy="ephemeral_per_call",
            disclosure_required=True,
            disclosure_summary=(
                "mlx-lm uses in-process KV cache per generation call. "
                "Cache is not persisted and not reusable across requests. "
                "No SSD persistence. Data never leaves the machine. "
                "KV cache reuse (OMLX-informed GPU page cache + prefix "
                "sharing) is v1_required_pending_implementation."
            ),
        )

    async def clear_cache(self) -> bool:
        """Clear in-process MLX cache."""
        self._clear_count += 1
        try:
            import mlx.core as mx

            mx.clear_cache()
            return True
        except Exception:
            return False

    def build_projection(self) -> dict:
        return {
            "cache_capability": {
                "kv_cache_reuse": "not_implemented",
                "kv_cache_reuse_status": (
                    "KV cache reuse pending. OMLX architecture provides "
                    "GPU page cache + SSD safetensors + prefix sharing "
                    "reference implementation. See cache/paged_cache.py "
                    "and cache/prefix_cache.py."
                ),
                "ssd_persistence": "not_implemented",
                "prefix_sharing": "not_implemented",
                "in_memory_ephemeral": "active_per_call",
            },
            "cache_privacy": {
                "mode": "local_runtime_ephemeral",
                "data_never_leaves_machine": True,
                "secret_bearing_refused_before_cache": True,
                "content_light_evidence": True,
            },
            "clear_available": True,
            "clear_count": self._clear_count,
        }

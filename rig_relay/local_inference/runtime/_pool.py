"""ModelPoolManager — LRU-governed multi-model loading with memory awareness.

Manages loaded models, enforcing max_models and memory ceilings.
Unloads idle models after TTL, with active-generation settle-barrier.

OMLX-informed: pool management pattern, LRU eviction (Apache 2.0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import threading
import time
from typing import Any

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import PoolEvictionReason

_MEMORY_PRESSURE_WARN_RATIO: float = 0.85


@dataclass
class PooledModel:
    model_ref: Any
    model_id_hash: str
    model_path: str
    loaded_at: str
    last_accessed: float = 0.0
    active_count: int = 0


class ModelPoolManager:
    """LRU-governed model pool with memory ceiling and idle TTL eviction."""

    def __init__(
        self, max_models: int = 3, max_memory_mb: int = 0, idle_ttl_seconds: int = 300
    ) -> None:
        self._pool: dict[str, PooledModel] = {}
        self._max_models = max_models
        self._max_memory_mb = max_memory_mb
        self._idle_ttl_seconds = idle_ttl_seconds
        self._total_loads: int = 0
        self._total_evictions: int = 0
        self._last_eviction_reason: PoolEvictionReason | None = None
        self._lock = threading.RLock()

    @property
    def loaded_count(self) -> int:
        with self._lock:
            return len(self._pool)

    @property
    def active_generations(self) -> int:
        with self._lock:
            return sum(m.active_count for m in self._pool.values())

    @property
    def total_loads(self) -> int:
        return self._total_loads

    @property
    def total_evictions(self) -> int:
        return self._total_evictions

    def acquire(self, model_id_hash: str) -> Any | None:
        """Increment active count, update access time, return model ref."""
        with self._lock:
            pm = self._pool.get(model_id_hash)
            if pm is None:
                return None
            pm.active_count += 1
            pm.last_accessed = time.monotonic()
            return pm.model_ref

    def release(self, model_id_hash: str) -> None:
        """Decrement active count."""
        with self._lock:
            pm = self._pool.get(model_id_hash)
            if pm is None:
                return
            pm.active_count = max(0, pm.active_count - 1)

    def load(self, model_path: str, model_id_hash: str, model_ref: Any) -> None:
        """Register a newly loaded model. Evicts LRU if over limit."""
        with self._lock:
            if model_id_hash in self._pool:
                pm = self._pool[model_id_hash]
                pm.last_accessed = time.monotonic()
                return

            self._evict_if_needed()

            self._pool[model_id_hash] = PooledModel(
                model_ref=model_ref,
                model_id_hash=model_id_hash,
                model_path=model_path,
                loaded_at=_now_iso(),
                last_accessed=time.monotonic(),
            )
            self._total_loads += 1
            logger.info(
                "ModelPoolManager: loaded model_id_hash=%s (pool size=%d/%d)",
                model_id_hash[:16],
                len(self._pool),
                self._max_models,
            )

    def unload(self, model_id_hash: str) -> bool:
        """Unload a model. Refuses if model has active generations."""
        with self._lock:
            pm = self._pool.get(model_id_hash)
            if pm is None:
                return False
            if pm.active_count > 0:
                logger.warning(
                    "ModelPoolManager: refusing unload of %s — %d active generations",
                    model_id_hash[:16],
                    pm.active_count,
                )
                return False
            del self._pool[model_id_hash]
            self._total_evictions += 1
            self._last_eviction_reason = PoolEvictionReason.MANUAL
            return True

    def _evict_if_needed(self) -> None:
        """Evict LRU model if pool is full."""
        with self._lock:
            if len(self._pool) < self._max_models:
                return

            candidates = sorted(
                ((pm.last_accessed, mid) for mid, pm in self._pool.items())
            )
            for _, mid in candidates:
                pm = self._pool[mid]
                if pm.active_count == 0:
                    del self._pool[mid]
                    self._total_evictions += 1
                    self._last_eviction_reason = PoolEvictionReason.LRU_LIMIT
                    logger.info(
                        "ModelPoolManager: LRU evicted model_id_hash=%s", mid[:16]
                    )
                    return

            logger.warning(
                "ModelPoolManager: all %d models have active generations — cannot evict",
                len(self._pool),
            )

    def evict_idle(self) -> int:
        """Evict models idle beyond TTL. Returns count evicted."""
        with self._lock:
            now = time.monotonic()
            evicted = 0
            for mid in list(self._pool):
                pm = self._pool[mid]
                if pm.active_count > 0:
                    continue
                if now - pm.last_accessed > self._idle_ttl_seconds:
                    del self._pool[mid]
                    evicted += 1
                    self._total_evictions += 1
                    self._last_eviction_reason = PoolEvictionReason.IDLE_TTL
                    logger.info(
                        "ModelPoolManager: idle TTL evicted model_id_hash=%s", mid[:16]
                    )
            return evicted

    def _check_memory(self) -> str:
        """Estimate memory pressure. Returns 'ok', 'warn', or 'over'."""
        try:
            import mlx.core as mx

            mem_info = mx.metal.get_active_memory()
            peak = mx.metal.get_peak_memory()
            if self._max_memory_mb > 0 and peak / (1024 * 1024) > self._max_memory_mb:
                return "over"
            if peak > 0 and mem_info / max(peak, 1) > _MEMORY_PRESSURE_WARN_RATIO:
                return "warn"
            return "ok"
        except Exception:
            return "unknown"

    def get_model(self, model_id_hash: str) -> Any | None:
        with self._lock:
            pm = self._pool.get(model_id_hash)
            return pm.model_ref if pm else None

    def build_projection(self) -> dict:
        with self._lock:
            return {
                "pool_state": {
                    "loaded_count": len(self._pool),
                    "max_models": self._max_models,
                    "active_generations": sum(
                        m.active_count for m in self._pool.values()
                    ),
                    "total_loads": self._total_loads,
                    "total_evictions": self._total_evictions,
                    "last_eviction_reason": (
                        self._last_eviction_reason.value
                        if self._last_eviction_reason
                        else None
                    ),
                    "memory_pressure": self._check_memory(),
                    "idle_ttl_seconds": self._idle_ttl_seconds,
                },
                "pool_models": [
                    {
                        "model_id_hash": pm.model_id_hash,
                        "loaded_at": pm.loaded_at,
                        "active_count": pm.active_count,
                    }
                    for pm in self._pool.values()
                ],
            }

    def shutdown(self) -> None:
        """Unload all models during shutdown."""
        with self._lock:
            for mid in list(self._pool):
                pm = self._pool[mid]
                if pm.active_count == 0:
                    del self._pool[mid]
                    self._total_evictions += 1
                    self._last_eviction_reason = PoolEvictionReason.SHUTDOWN
            self._pool.clear()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

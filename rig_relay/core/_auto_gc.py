from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.core.logger import logger


async def maybe_auto_gc(config: Any, workspace_root: Path, stats: Any) -> None:
    """Passive GC: check storage budget and prune stale artifacts if over threshold.

    Args:
        config: VibeConfig (or any object with enable_local_observability attribute).
        workspace_root: Project root path.
        stats: AgentStats (or any object with gc_deleted_count attribute).
    """
    if not getattr(config, "enable_local_observability", False):
        return

    try:
        from rig_relay.evidence.storage_lifecycle import compute_storage_summary

        summary = compute_storage_summary(workspace_root / ".rig" / "relay")
        budget_status = summary.get("budget_status", "ok")

        if budget_status not in {"warn", "over_budget", "fleet_blocked"}:
            return

        try:
            from rig_relay.evidence.storage_lifecycle import run_artifact_gc

            result = run_artifact_gc(
                root=workspace_root / ".rig" / "relay", budget=summary, confirm=True
            )
            deleted = result.get("summary", {}).get("deleted", 0)
            freed_mb = result.get("summary", {}).get("freed_mb", 0.0)
            if deleted > 0:
                existing = getattr(stats, "gc_deleted_count", 0)
                stats.gc_deleted_count = existing + deleted
                logger.info(
                    "Auto-GC: removed %d artifacts (%.1f MB) after tool execution",
                    deleted,
                    freed_mb,
                )
        except ImportError:
            pass
    except Exception:
        logger.warning("Auto-GC failed", exc_info=True)

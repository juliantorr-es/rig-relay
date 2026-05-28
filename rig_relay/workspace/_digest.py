from __future__ import annotations

import hashlib
import json

from rig_relay.workspace.models import WorkspaceLifecycleEvent


def compute_event_digest(event: WorkspaceLifecycleEvent) -> str:
    data = event.model_dump(mode="json", exclude={"event_digest", "prior_event_digest"})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


__all__ = ["compute_event_digest"]

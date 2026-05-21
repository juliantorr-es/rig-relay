from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum, auto
from subprocess import Popen
from typing import Any


class BridgeInstanceState(StrEnum):
    STARTING = auto()
    HEALTHY = auto()
    DEGRADED = auto()
    DISCONNECTED = auto()
    FAILED = auto()
    STOPPED = auto()


class FleetHealthSummary(IntEnum):
    ALL_HEALTHY = 0
    DEGRADED_PRESENT = 1
    DISCONNECTED_PRESENT = 2
    FAILED_PRESENT = 3
    NO_INSTANCES = 4


@dataclass(slots=True)
class BridgeInstance:
    instance_id: str
    tenant_id: str
    state: BridgeInstanceState = BridgeInstanceState.STOPPED
    port: int = 0
    health_port: int = 0
    pid: int | None = None
    process: Popen[bytes] | None = field(default=None, repr=False)
    started_at: str = ""
    last_heartbeat: str = ""
    active_strands: int = 0
    event_count: int = 0
    health_metrics: dict[str, Any] = field(default_factory=dict)


__all__ = ["BridgeInstance", "BridgeInstanceState", "FleetHealthSummary"]

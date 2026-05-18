from __future__ import annotations

from enum import StrEnum, auto

# ── Canonical Lifecycle Step IDs ──────────────────────────────────────
# Corresponds one-to-one with the bridge lifecycle event contract.


class LifecycleStep(StrEnum):
    # Backend bridge startup probe ladder (pre-existing, bridge:01-bridge:18)
    BRIDGE_FRONTEND_DIR_RESOLVED = auto()  # bridge:01
    BRIDGE_INDEX_RESOLVED = auto()  # bridge:02
    BRIDGE_ASSETS_VERIFIED = auto()  # bridge:03
    BRIDGE_CONFIG_BUILT = auto()  # bridge:04
    BRIDGE_WEBSOCKET_SERVER_CREATED = auto()  # bridge:05
    BRIDGE_SERVER_BOUND = auto()  # bridge:06
    BRIDGE_HEALTH_PROBED = auto()  # bridge:07
    BRIDGE_INDEX_PROBED = auto()  # bridge:08
    BRIDGE_MODULE_PROBED = auto()  # bridge:09
    BRIDGE_ENTRYPOINT_PROBED = auto()  # bridge:09a
    BRIDGE_CSS_PROBED = auto()  # bridge:10
    BRIDGE_WINDOW_CREATED = auto()  # bridge:11
    BRIDGE_WINDOW_STARTED = auto()  # bridge:12
    BRIDGE_RUNTIME_CONFIG_SERVED = auto()  # bridge:13
    BRIDGE_WEBSOCKET_ACCEPTED = auto()  # bridge:14

    # Backend WebSocket server lifecycle
    BACKEND_WS_AUTH_RECEIVED = auto()  # bridge:15
    BACKEND_WS_AUTH_OK = auto()  # bridge:16

    # Backend projection lifecycle
    BACKEND_PROJECTION_BUILD_STARTED = auto()
    BACKEND_PROJECTION_BUILD_OK = auto()
    BACKEND_PROJECTION_SENT = auto()  # bridge:17

    # Frontend boot lifecycle
    FRONTEND_BOOT_STARTED = auto()
    FRONTEND_MODULE_GRAPH_LOADED = auto()
    FRONTEND_RUNTIME_CONFIG_REQUESTED = auto()
    FRONTEND_RUNTIME_CONFIG_LOADED = auto()

    # Frontend transport lifecycle
    FRONTEND_WEBSOCKET_CONSTRUCTED = auto()
    FRONTEND_SOCKET_OPEN = auto()
    FRONTEND_AUTH_SENT = auto()
    FRONTEND_AUTH_OK = auto()

    # Frontend projection lifecycle
    FRONTEND_PROJECTION_REQUESTED = auto()
    FRONTEND_PROJECTION_RECEIVED = auto()
    FRONTEND_PROJECTION_RENDER_STARTED = auto()
    FRONTEND_PROJECTION_RENDER_OK = auto()  # bridge:18

    # Frontend widget lifecycle
    FRONTEND_WIDGETS_MOUNT_STARTED = auto()
    FRONTEND_WIDGETS_MOUNT_OK = auto()

    # Terminal states
    FRONTEND_READY = auto()
    FRONTEND_FAILED = auto()


# ── Step Source Classification ─────────────────────────────────────────


class StepSource(StrEnum):
    BACKEND = auto()
    FRONTEND = auto()
    WEBSOCKET = auto()


STEP_SOURCE: dict[LifecycleStep, StepSource] = {
    LifecycleStep.BRIDGE_FRONTEND_DIR_RESOLVED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_INDEX_RESOLVED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_ASSETS_VERIFIED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_CONFIG_BUILT: StepSource.BACKEND,
    LifecycleStep.BRIDGE_WEBSOCKET_SERVER_CREATED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_SERVER_BOUND: StepSource.BACKEND,
    LifecycleStep.BRIDGE_HEALTH_PROBED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_INDEX_PROBED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_MODULE_PROBED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_ENTRYPOINT_PROBED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_CSS_PROBED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_WINDOW_CREATED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_WINDOW_STARTED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_RUNTIME_CONFIG_SERVED: StepSource.BACKEND,
    LifecycleStep.BRIDGE_WEBSOCKET_ACCEPTED: StepSource.BACKEND,
    LifecycleStep.BACKEND_WS_AUTH_RECEIVED: StepSource.WEBSOCKET,
    LifecycleStep.BACKEND_WS_AUTH_OK: StepSource.WEBSOCKET,
    LifecycleStep.BACKEND_PROJECTION_BUILD_STARTED: StepSource.WEBSOCKET,
    LifecycleStep.BACKEND_PROJECTION_BUILD_OK: StepSource.WEBSOCKET,
    LifecycleStep.BACKEND_PROJECTION_SENT: StepSource.WEBSOCKET,
    LifecycleStep.FRONTEND_BOOT_STARTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_MODULE_GRAPH_LOADED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_RUNTIME_CONFIG_REQUESTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_RUNTIME_CONFIG_LOADED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_WEBSOCKET_CONSTRUCTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_SOCKET_OPEN: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_AUTH_SENT: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_AUTH_OK: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_PROJECTION_REQUESTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_PROJECTION_RECEIVED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_PROJECTION_RENDER_STARTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_PROJECTION_RENDER_OK: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_WIDGETS_MOUNT_STARTED: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_WIDGETS_MOUNT_OK: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_READY: StepSource.FRONTEND,
    LifecycleStep.FRONTEND_FAILED: StepSource.FRONTEND,
}


# ── Step Ordering (sequence index) ─────────────────────────────────────


_STEP_ORDER: dict[LifecycleStep, int] = {
    # Backend bridge startup
    LifecycleStep.BRIDGE_FRONTEND_DIR_RESOLVED: 1,
    LifecycleStep.BRIDGE_INDEX_RESOLVED: 2,
    LifecycleStep.BRIDGE_ASSETS_VERIFIED: 3,
    LifecycleStep.BRIDGE_CONFIG_BUILT: 4,
    LifecycleStep.BRIDGE_WEBSOCKET_SERVER_CREATED: 5,
    LifecycleStep.BRIDGE_SERVER_BOUND: 6,
    LifecycleStep.BRIDGE_HEALTH_PROBED: 7,
    LifecycleStep.BRIDGE_INDEX_PROBED: 8,
    LifecycleStep.BRIDGE_MODULE_PROBED: 9,
    LifecycleStep.BRIDGE_ENTRYPOINT_PROBED: 10,
    LifecycleStep.BRIDGE_CSS_PROBED: 11,
    LifecycleStep.BRIDGE_WINDOW_CREATED: 12,
    LifecycleStep.BRIDGE_WINDOW_STARTED: 13,
    LifecycleStep.BRIDGE_RUNTIME_CONFIG_SERVED: 14,
    LifecycleStep.BRIDGE_WEBSOCKET_ACCEPTED: 15,
    # Frontend boot
    LifecycleStep.FRONTEND_BOOT_STARTED: 16,
    LifecycleStep.FRONTEND_MODULE_GRAPH_LOADED: 17,
    LifecycleStep.FRONTEND_RUNTIME_CONFIG_REQUESTED: 18,
    LifecycleStep.FRONTEND_RUNTIME_CONFIG_LOADED: 19,
    # Frontend transport
    LifecycleStep.FRONTEND_WEBSOCKET_CONSTRUCTED: 20,
    LifecycleStep.FRONTEND_SOCKET_OPEN: 21,
    LifecycleStep.FRONTEND_AUTH_SENT: 22,
    # Backend auth (handled by WS)
    LifecycleStep.BACKEND_WS_AUTH_RECEIVED: 23,
    LifecycleStep.BACKEND_WS_AUTH_OK: 24,
    # Frontend auth ok
    LifecycleStep.FRONTEND_AUTH_OK: 25,
    # Projection
    LifecycleStep.FRONTEND_PROJECTION_REQUESTED: 26,
    LifecycleStep.BACKEND_PROJECTION_BUILD_STARTED: 27,
    LifecycleStep.BACKEND_PROJECTION_BUILD_OK: 28,
    LifecycleStep.BACKEND_PROJECTION_SENT: 29,
    LifecycleStep.FRONTEND_PROJECTION_RECEIVED: 30,
    LifecycleStep.FRONTEND_PROJECTION_RENDER_STARTED: 31,
    LifecycleStep.FRONTEND_PROJECTION_RENDER_OK: 32,
    # Widgets
    LifecycleStep.FRONTEND_WIDGETS_MOUNT_STARTED: 33,
    LifecycleStep.FRONTEND_WIDGETS_MOUNT_OK: 34,
    # Terminal
    LifecycleStep.FRONTEND_READY: 35,
    LifecycleStep.FRONTEND_FAILED: 36,
}


# ── Required steps for READY status ────────────────────────────────────
# Static probes (bridge:01 through bridge:13) are NOT sufficient.
# Frontend projection and widget mount MUST complete.


REQUIRED_FOR_READY: frozenset[LifecycleStep] = frozenset({
    LifecycleStep.BRIDGE_SERVER_BOUND,
    LifecycleStep.BRIDGE_RUNTIME_CONFIG_SERVED,
    LifecycleStep.FRONTEND_RUNTIME_CONFIG_LOADED,
    LifecycleStep.FRONTEND_WEBSOCKET_CONSTRUCTED,
    LifecycleStep.FRONTEND_AUTH_OK,
    LifecycleStep.BACKEND_WS_AUTH_OK,
    LifecycleStep.FRONTEND_PROJECTION_RECEIVED,
    LifecycleStep.FRONTEND_PROJECTION_RENDER_OK,
    LifecycleStep.FRONTEND_WIDGETS_MOUNT_OK,
    LifecycleStep.FRONTEND_READY,
})


# ── Bridge step ID to LifecycleStep mapping ────────────────────────────


_BRIDGE_STEP_TO_LIFECYCLE: dict[str, LifecycleStep] = {
    "bridge:01": LifecycleStep.BRIDGE_FRONTEND_DIR_RESOLVED,
    "bridge:02": LifecycleStep.BRIDGE_INDEX_RESOLVED,
    "bridge:03": LifecycleStep.BRIDGE_ASSETS_VERIFIED,
    "bridge:04": LifecycleStep.BRIDGE_CONFIG_BUILT,
    "bridge:05": LifecycleStep.BRIDGE_WEBSOCKET_SERVER_CREATED,
    "bridge:06": LifecycleStep.BRIDGE_SERVER_BOUND,
    "bridge:07": LifecycleStep.BRIDGE_HEALTH_PROBED,
    "bridge:08": LifecycleStep.BRIDGE_INDEX_PROBED,
    "bridge:09": LifecycleStep.BRIDGE_MODULE_PROBED,
    "bridge:09a": LifecycleStep.BRIDGE_ENTRYPOINT_PROBED,
    "bridge:10": LifecycleStep.BRIDGE_CSS_PROBED,
    "bridge:11": LifecycleStep.BRIDGE_WINDOW_CREATED,
    "bridge:12": LifecycleStep.BRIDGE_WINDOW_STARTED,
    "bridge:13": LifecycleStep.BRIDGE_RUNTIME_CONFIG_SERVED,
    "bridge:14": LifecycleStep.BRIDGE_WEBSOCKET_ACCEPTED,
    "bridge:15": LifecycleStep.BACKEND_WS_AUTH_RECEIVED,
    "bridge:16": LifecycleStep.BACKEND_WS_AUTH_OK,
    "bridge:17": LifecycleStep.BACKEND_PROJECTION_SENT,
    "bridge:18": LifecycleStep.FRONTEND_PROJECTION_RENDER_OK,
}


# ── Validation ─────────────────────────────────────────────────────────


def validate_lifecycle_completeness(
    completed_steps: set[LifecycleStep],
) -> tuple[bool, list[LifecycleStep]]:
    """Return (is_ready, missing_steps)."""
    missing = [s for s in REQUIRED_FOR_READY if s not in completed_steps]
    if LifecycleStep.FRONTEND_FAILED in completed_steps:
        return False, [s for s in missing if s != LifecycleStep.FRONTEND_READY]
    return len(missing) == 0, missing


def step_order(step: LifecycleStep) -> int:
    return _STEP_ORDER.get(step, 999)


def lifecycle_step_from_bridge_id(bridge_id: str) -> LifecycleStep | None:
    return _BRIDGE_STEP_TO_LIFECYCLE.get(bridge_id)


__all__ = [
    "REQUIRED_FOR_READY",
    "STEP_SOURCE",
    "LifecycleStep",
    "StepSource",
    "lifecycle_step_from_bridge_id",
    "step_order",
    "validate_lifecycle_completeness",
]

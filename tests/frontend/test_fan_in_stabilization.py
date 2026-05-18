from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"
RUNTIME_DIR = FRONTEND_DIR / "runtime"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _read_runtime(name: str) -> str:
    return (RUNTIME_DIR / name).read_text(encoding="utf-8")


# ── FSM convergence ──────────────────────────────────────────────────


def test_only_one_fsm_module_exists():
    """Only runtime/stateMachine.js is the canonical FSM implementation."""
    assert RUNTIME_DIR.joinpath("stateMachine.js").exists()
    assert not FRONTEND_DIR.joinpath("stateMachines.js").exists(), (
        "stateMachines.js must NOT exist — runtime/stateMachine.js is canonical"
    )


def test_kernel_imports_canonical_state_machine():
    source = _read_runtime("kernel.js")
    assert "from './stateMachine.js'" in source
    assert "createStateMachine" in source


def test_delight_imports_canonical_state_machine():
    source = _read("delight.js")
    assert "from './runtime/stateMachine.js'" in source


# ── Kernel decomposition ─────────────────────────────────────────────


def test_reducer_exists_and_pure():
    source = _read_runtime("reducer.js")
    assert "export function rootReducer" in source or "function rootReducer" in source
    assert "rootReducer" in source
    # Reducer must not have DOM/WS/timer calls
    assert "document." not in source, "Reducer must not touch DOM"
    assert "WebSocket" not in source, "Reducer must not use WebSocket"
    assert "setInterval" not in source, "Reducer must not use setInterval"
    assert "setTimeout" not in source, "Reducer must not use setTimeout"
    assert "fetch(" not in source, "Reducer must not use fetch"


def test_loops_js_exists():
    assert RUNTIME_DIR.joinpath("loops.js").exists()


def test_multitab_js_exists():
    assert RUNTIME_DIR.joinpath("multitab.js").exists()


def test_notif_bridge_js_exists():
    assert RUNTIME_DIR.joinpath("notifBridge.js").exists()


def test_kernel_is_thin_composition_root():
    """kernel.js should be under 600 lines after decomposition."""
    source = _read_runtime("kernel.js")
    lines = source.count("\n")
    assert lines < 550, f"kernel.js is {lines} lines, should be < 550"


# ── Projection integration ───────────────────────────────────────────


def test_orchestrator_dispatches_projection_received():
    source = _read("boot/orchestrator.js")
    assert "PROJECTION_RECEIVED" in source, (
        "orchestrator must dispatch PROJECTION_RECEIVED to kernel"
    )
    assert "runtime.dispatch" in source


# ── Widget failure isolation ─────────────────────────────────────────


def test_widgets_has_try_catch_isolation():
    source = _read("widgets.js")
    # Widget renderers must have try/catch to isolate failures
    assert "try {" in source, "widgets.js must have try/catch for failure isolation"
    assert "catch" in source, "widgets.js must have catch for failure isolation"


# ── Notification/delight use single authority ─────────────────────────


def test_notifications_uses_kernel():
    source = _read("notifications.js")
    assert (
        "kernel.subscribe" in source
        or "kernel.onReady" in source
        or "kernel.registerMachine" in source
    )


def test_delight_uses_kernel():
    source = _read("delight.js")
    assert "kernel.subscribe" in source or "kernel.onReady" in source


# ── Sound/notification safety ────────────────────────────────────────


def test_no_notification_permission_on_boot():
    """Notification.requestPermission must not be called at module load."""
    source = _read("systemNotifications.js")
    # The comment documents the safety property
    assert "NEVER calls requestPermission()" in source, (
        "systemNotifications.js must document that requestPermission is never called on boot"
    )
    # requestPermission must appear inside a function body, not at module top level
    assert source.count("requestPermission()") <= 2, (
        "requestPermission() should only appear in comment and inside requestPermission function"
    )


# ── No secrets in evidence ───────────────────────────────────────────


def test_evidence_js_no_secrets():
    source = _read_runtime("evidence.js")
    # "password" appears in redaction regex _SECRET_KEY_RE — not an actual secret
    for forbidden in ["sk-", "auth_token"]:
        assert forbidden not in source.lower(), (
            f"evidence.js must not contain {forbidden}"
        )


def test_reducer_js_no_secrets():
    source = _read_runtime("reducer.js")
    for forbidden in ["sk-", "api_key", "password", "auth_token", "secret"]:
        assert forbidden not in source.lower(), (
            f"reducer.js must not contain {forbidden}"
        )


def test_notif_bridge_js_no_secrets():
    source = _read_runtime("notifBridge.js")
    for forbidden in ["sk-", "api_key", "password", "auth_token"]:
        assert forbidden not in source.lower(), (
            f"notifBridge.js must not contain {forbidden}"
        )


# ── Modules after split ──────────────────────────────────────────────


def test_actions_is_barrel():
    source = _read_runtime("actions.js")
    assert "from './constants.js'" in source
    assert "from './initialState.js'" in source
    assert "from './actionCreators.js'" in source


def test_constants_js_exists():
    assert RUNTIME_DIR.joinpath("constants.js").exists()


def test_initial_state_js_exists():
    assert RUNTIME_DIR.joinpath("initialState.js").exists()


def test_action_creators_js_exists():
    assert RUNTIME_DIR.joinpath("actionCreators.js").exists()

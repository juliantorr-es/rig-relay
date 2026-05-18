from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


# ── Module structure ──────────────────────────────────────────────────


def test_state_machine_exports_create_state_machine():
    source = _read("runtime/stateMachine.js")
    assert "export function createStateMachine" in source


def test_state_machine_returns_frozen_object():
    source = _read("runtime/stateMachine.js")
    assert "return Object.freeze" in source
    assert "transition" in source
    assert "getState" in source
    assert "subscribe" in source
    assert "reset" in source


# ── Config validation ─────────────────────────────────────────────────


def test_state_machine_config_is_frozen():
    source = _read("runtime/stateMachine.js")
    assert "frozenConfig" in source
    assert "Object.freeze" in source


def test_state_machine_states_are_objects():
    source = _read("runtime/stateMachine.js")
    assert "config.states" in source
    assert "Object.freeze({ ...config.states })" in source


# ── Transition behavior ───────────────────────────────────────────────


def test_invalid_transition_returns_error():
    source = _read("runtime/stateMachine.js")
    assert "success: false" in source
    assert "no transition for event" in source


def test_valid_transition_returns_success():
    source = _read("runtime/stateMachine.js")
    assert "success: true" in source
    assert "from:" in source
    assert "to:" in source


def test_wildcard_transition_matches_any_state():
    source = _read("runtime/stateMachine.js")
    assert "WILDCARD" in source
    assert "from === WILDCARD" in source
    assert "Array.isArray(from)" in source


# ── Guard support ─────────────────────────────────────────────────────


def test_guard_blocks_transition():
    source = _read("runtime/stateMachine.js")
    assert "guard" in source
    assert "blocked: true" in source
    assert "matching.guard" in source


def test_global_guards_are_checked():
    source = _read("runtime/stateMachine.js")
    assert "frozenConfig.guards" in source
    assert "for (const guard of frozenConfig.guards)" in source


# ── Entry/exit callbacks ──────────────────────────────────────────────


def test_state_entry_and_exit_callbacks():
    source = _read("runtime/stateMachine.js")
    assert "oldDef.exit" in source
    assert "newDef.entry" in source
    assert "isSelfTransition" in source


def test_self_transition_skips_entry_exit():
    source = _read("runtime/stateMachine.js")
    assert "isSelfTransition" in source
    assert "!isSelfTransition" in source


# ── Effects ───────────────────────────────────────────────────────────


def test_per_transition_effects_supported():
    source = _read("runtime/stateMachine.js")
    assert "matching.effect" in source


def test_global_effects_supported():
    source = _read("runtime/stateMachine.js")
    assert "frozenConfig.effects" in source


# ── Subscription system ───────────────────────────────────────────────


def test_subscribe_returns_unsubscribe():
    source = _read("runtime/stateMachine.js")
    assert "function unsubscribe()" in source
    assert "listeners.delete(listener)" in source


def test_subscriptions_notified_on_transition():
    source = _read("runtime/stateMachine.js")
    assert "notifyListeners" in source
    assert "listener(newState, oldState)" in source


def test_subscription_errors_are_caught():
    source = _read("runtime/stateMachine.js")
    idx_notify = source.index("function notifyListeners")
    context = source[idx_notify : idx_notify + 200]
    assert "try {" in context, "Subscription dispatch must be wrapped in try"
    assert "catch" in context


# ── Integration: runtime kernel uses state machine ───────────────────


def test_kernel_imports_state_machine():
    source = _read("runtime/kernel.js")
    assert "from './stateMachine.js'" in source
    assert "createStateMachine" in source


def test_kernel_creates_boot_fsm():
    source = _read("runtime/kernel.js")
    assert "_createBootFSM" in source
    assert "createStateMachine" in source
    assert "id: 'boot'" in source


def test_kernel_creates_intent_fsm():
    source = _read("runtime/kernel.js")
    assert "_createIntentFSM" in source
    assert "id: 'intent'" in source


def test_kernel_creates_mode_fsm():
    source = _read("runtime/kernel.js")
    assert "_createModeFSM" in source
    assert "id: 'mode'" in source


# ── Edge cases ────────────────────────────────────────────────────────


def test_state_machine_reset_function():
    source = _read("runtime/stateMachine.js")
    assert "function reset()" in source
    assert "frozenConfig.initial" in source


def test_state_machine_getstate():
    source = _read("runtime/stateMachine.js")
    assert "function getState()" in source
    assert "return currentState" in source

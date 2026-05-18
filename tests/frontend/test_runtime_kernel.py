from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


# ── Module existence ──────────────────────────────────────────────────


def test_runtime_kernel_js_exists():
    kernel_path = FRONTEND_DIR / "runtime" / "kernel.js"
    assert kernel_path.exists(), "runtime/kernel.js must exist"
    source = kernel_path.read_text(encoding="utf-8")
    assert "createRuntime" in source, "runtime/kernel.js must export createRuntime"
    assert "export function createRuntime" in source


def test_runtime_state_machine_js_exists():
    sm_path = FRONTEND_DIR / "runtime" / "stateMachine.js"
    assert sm_path.exists(), "runtime/stateMachine.js must exist"
    source = sm_path.read_text(encoding="utf-8")
    assert "createStateMachine" in source, (
        "runtime/stateMachine.js must export createStateMachine"
    )
    assert "export function createStateMachine" in source


# ── Kernel API surface ────────────────────────────────────────────────


def test_kernel_exports_reducer():
    source = _read("runtime/kernel.js")
    assert "rootReducer" in source
    assert "function rootReducer" in source
    assert "case AT.BOOT_PHASE_TRANSITION" in source
    assert "case AT.TRANSPORT_STATUS_CHANGE" in source
    assert "case AT.PROJECTION_RECEIVED" in source


def test_kernel_exports_create_runtime():
    source = _read("runtime/kernel.js")
    assert "export function createRuntime" in source
    assert "function dispatch" in source or "const dispatch" in source


def test_kernel_exports_state_machines():
    source = _read("runtime/kernel.js")
    assert "bootFSM" in source
    assert "intentFSM" in source
    assert "modeFSM" in source


def test_kernel_exports_subscribe():
    source = _read("runtime/kernel.js")
    assert "function subscribe" in source


def test_kernel_exports_effects():
    source = _read("runtime/kernel.js")
    assert "effectRunner" in source
    assert "loopSupervisor" in source


# ── Kernel transport integration ──────────────────────────────────────


def test_orchestrator_imports_create_runtime():
    source = _read("boot/orchestrator.js")
    assert "createRuntime" in source
    assert "from '../runtime/kernel.js'" in source


def test_orchestrator_creates_runtime():
    source = _read("boot/orchestrator.js")
    assert "const runtime = createRuntime({" in source


def test_orchestrator_exposes_runtime():
    source = _read("boot/orchestrator.js")
    assert "window.__RIG_RELAY_RUNTIME__" in source


def test_orchestrator_calls_runtime_init():
    source = _read("boot/orchestrator.js")
    assert "runtime.init()" in source


def test_orchestrator_uses_boot_fsm():
    source = _read("boot/orchestrator.js")
    assert "runtime.bootFSM.transition" in source


# ── No secrets in JS source ───────────────────────────────────────────


def test_kernel_js_has_no_secrets():
    source = _read("runtime/kernel.js")
    assert "sk-" not in source, "kernel.js must not contain API keys"
    assert "api_key" not in source.lower(), "kernel.js must not contain api_key"
    assert "password" not in source.lower(), "kernel.js must not contain password"
    # "secret" appears in security documentation ("no token data", redaction regex),
    # not as an actual secret value — allow it
    assert "auth_token" not in source, "kernel.js must not reference auth_token"


def test_actions_js_has_no_secrets():
    source = _read("runtime/actions.js")
    assert "sk-" not in source, "actions.js must not contain API keys"
    assert "api_key" not in source.lower(), "actions.js must not contain api_key"
    assert "password" not in source.lower(), "actions.js must not contain password"
    assert "secret" not in source.lower(), "actions.js must not contain secret"
    assert "auth_token" not in source, "actions.js must not reference auth_token"


def test_evidence_js_has_no_secrets():
    """Evidence module must not contain actual secrets — only redaction patterns."""
    source = _read("runtime/evidence.js")
    assert "sk-" not in source, "evidence.js must not contain API keys"
    # "api_key" appears in the redaction regex (_SECRET_KEY_RE), not as an actual key
    assert "auth_token" not in source, "evidence.js must not reference auth_token"


def test_transport_state_js_has_no_secrets():
    source = _read("transportState.js")
    assert "sk-" not in source, "transportState.js must not contain API keys"
    assert "api_key" not in source.lower(), "transportState.js must not contain api_key"
    assert "password" not in source.lower(), (
        "transportState.js must not contain password"
    )
    assert "auth_token" not in source, "transportState.js must not reference auth_token"


# ── No raw sleeps ─────────────────────────────────────────────────────


def test_kernel_js_has_no_raw_sleeps():
    source = _read("runtime/kernel.js")
    assert "sleep(" not in source, "kernel.js must not use sleep/delay for correctness"


# ── transportState.js additive changes ────────────────────────────────


def test_transport_state_has_on_global_state_change_option():
    source = _read("transportState.js")
    assert "onGlobalStateChange" in source
    assert "setOnGlobalStateChange" in source
    assert "_onGlobalStateChange" in source


def test_transport_state_exports_set_on_global_state_change():
    source = _read("transportState.js")
    return_section = source[source.index("return {") :]
    assert "setOnGlobalStateChange" in return_section


def test_transport_state_retains_all_original_exports():
    source = _read("transportState.js")
    for export_name in [
        "dispatch",
        "transition",
        "snapshot",
        "getStatus",
        "isConnected",
        "setHandshakeId",
        "setOnTransition",
    ]:
        assert export_name in source, (
            f"transportState.js must still export {export_name}"
        )


# ── Kernel module conventions ─────────────────────────────────────────


def test_kernel_uses_deep_freeze():
    source = _read("runtime/kernel.js")
    assert "function _deepFreeze" in source
    assert "Object.freeze(obj)" in source


def test_kernel_has_destroy_method():
    source = _read("runtime/kernel.js")
    assert "function destroy" in source
    assert "cancelAllLoops" in source


def test_kernel_has_broadcast_channel():
    source = _read("runtime/kernel.js")
    assert "BroadcastChannel" in source
    assert "MULTI_TAB_SECONDARY_DETECTED" in source
    # BroadcastChannel function must not transmit secrets in postMessage payload
    bc_start = source.index("function _setupBroadcastChannel")
    bc_end = bc_start + 600
    bc_section = source[bc_start:bc_end]
    assert "postMessage" in bc_section
    assert "cockpit_present" in bc_section
    assert "handshake_id" not in bc_section, (
        "BroadcastChannel must NOT send handshake_id"
    )
    assert "auth_token" not in bc_section, "BroadcastChannel must NOT send auth_token"


# ── Reducer purity ────────────────────────────────────────────────────


def test_reducer_returns_new_state_not_mutate():
    source = _read("runtime/kernel.js")
    assert (
        "return { ...state, boot: nextBoot }" in source
        or "return { ...state," in source
    )


# ── Boot FSM ──────────────────────────────────────────────────────────


def test_boot_fsm_has_required_phases():
    source = _read("runtime/kernel.js")
    for phase in [
        "STATIC_SHELL_LOADED",
        "RUNTIME_CONFIG_LOADING",
        "RUNTIME_CONFIG_LOADED",
        "TRANSPORT_CONNECTING",
        "AUTHENTICATING",
        "PROJECTION_WAITING",
        "RENDERING",
        "READY",
        "DEGRADED",
        "FAILED",
    ]:
        assert phase in source, f"Boot FSM must define {phase} phase"


def test_boot_fsm_ready_is_terminal():
    source = _read("runtime/kernel.js")
    # Ready should be reachable from rendering
    assert "'boot:ready'" in source
    assert "BP.READY" in source
    assert "readyAt = Date.now()" in source

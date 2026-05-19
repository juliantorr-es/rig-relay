from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"
TELEMETRY_DIR = FRONTEND_DIR / "telemetry"
RUNTIME_DIR = FRONTEND_DIR / "runtime"
PROTOCOL_DIR = FRONTEND_DIR / "protocol"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _read_telemetry(name: str) -> str:
    return (TELEMETRY_DIR / name).read_text(encoding="utf-8")


def _read_runtime(name: str) -> str:
    return (RUNTIME_DIR / name).read_text(encoding="utf-8")


def _read_protocol(name: str) -> str:
    return (PROTOCOL_DIR / name).read_text(encoding="utf-8")


# ── Module existence ──────────────────────────────────────────────────


def test_trace_context_exists():
    assert TELEMETRY_DIR.joinpath("traceContext.js").exists()


def test_sanitizer_exists():
    assert TELEMETRY_DIR.joinpath("sanitizer.js").exists()


# ── Trace context API ─────────────────────────────────────────────────


def test_trace_context_exports_initialize():
    source = _read_telemetry("traceContext.js")
    assert "export function initializeTraceContext" in source


def test_trace_context_exports_get():
    source = _read_telemetry("traceContext.js")
    assert "export function getTraceContext" in source


def test_trace_context_exports_next_sequence():
    source = _read_telemetry("traceContext.js")
    assert "export function nextFrontendSequence" in source


def test_trace_context_exports_annotate():
    source = _read_telemetry("traceContext.js")
    assert "export function annotate" in source


def test_trace_context_exports_set_handshake():
    source = _read_telemetry("traceContext.js")
    assert "export function setHandshakeId" in source


def test_trace_context_exports_record_ready():
    source = _read_telemetry("traceContext.js")
    assert "export function recordReady" in source


def test_trace_context_exports_is_ready_emitted():
    source = _read_telemetry("traceContext.js")
    assert "export function isReadyEmitted" in source


def test_trace_context_exports_record_heartbeat():
    source = _read_telemetry("traceContext.js")
    assert "export function recordHeartbeat" in source


def test_trace_context_exports_with_protocol_message():
    source = _read_telemetry("traceContext.js")
    assert "export function withProtocolMessage" in source


def test_trace_context_exports_set_boot_phase():
    source = _read_telemetry("traceContext.js")
    assert "export function setBootPhase" in source


def test_trace_context_exports_set_projection_seq():
    source = _read_telemetry("traceContext.js")
    assert "export function setProjectionSequence" in source


def test_trace_context_has_ready_duplicate_guard():
    source = _read_telemetry("traceContext.js")
    assert "_readyEmitted" in source
    assert "duplicate: true" in source


def test_trace_context_has_frontend_session_id():
    source = _read_telemetry("traceContext.js")
    assert "_frontendSessionId" in source
    assert "fs_" in source


# ── Sanitizer ─────────────────────────────────────────────────────────


def test_sanitizer_exports_sanitize():
    source = _read_telemetry("sanitizer.js")
    assert "export" in source
    assert "sanitize" in source


def test_sanitizer_has_secret_key_re():
    source = _read_telemetry("sanitizer.js")
    assert "_SECRET_KEY_RE" in source
    assert "token|secret|key|password" in source


def test_sanitizer_has_jwt_prefix():
    source = _read_telemetry("sanitizer.js")
    assert "_JWT_PREFIX" in source
    assert "eyJ" in source


def test_sanitizer_has_max_depth():
    source = _read_telemetry("sanitizer.js")
    assert "_MAX_SANITIZE_DEPTH" in source
    assert "10" in source


# ── frontendTrace.js unified ──────────────────────────────────────────


def test_frontend_trace_uses_shared_sequence():
    source = _read_telemetry("frontendTrace.js")
    assert "nextFrontendSequence" in source


def test_frontend_trace_uses_shared_context():
    source = _read_telemetry("frontendTrace.js")
    assert "getTraceContext" in source


def test_frontend_trace_uses_sanitizer():
    source = _read_telemetry("frontendTrace.js")
    assert "sanitize" in source


def test_frontend_trace_sanitizes_http_fallback():
    """HTTP GET fallback must sanitize before encoding."""
    source = _read_telemetry("frontendTrace.js")
    idx_fetch = source.index("fetch(") if "fetch(" in source else -1
    if idx_fetch >= 0:
        context = source[idx_fetch - 200 : idx_fetch + 300]
        assert "sanitize(" in context, (
            "HTTP fallback must call sanitize before encoding detail"
        )
    # Also check the encodeURIComponent line
    idx_encode = (
        source.index("encodeURIComponent") if "encodeURIComponent" in source else -1
    )
    if idx_encode >= 0:
        # There should be a sanitize call before the encodeURIComponent for detail
        enc_context = source[max(0, idx_encode - 100) : idx_encode + 100]
        assert "sanitize" in enc_context or "sanitized" in enc_context.lower()


def test_frontend_trace_no_internal_sequence():
    source = _read_telemetry("frontendTrace.js")
    # Should NOT have its own _frontendSequence incremented directly
    assert "_frontendSequence++" not in source, (
        "frontendTrace.js must use shared nextFrontendSequence()"
    )


# ── Runtime evidence unified ──────────────────────────────────────────


def test_evidence_uses_shared_context():
    source = _read_runtime("evidence.js")
    assert "getTraceContext" in source


def test_evidence_uses_shared_sanitizer():
    source = _read_runtime("evidence.js")
    assert "sanitizer" in source or "sanitize" in source


def test_evidence_no_duplicate_sanitizer():
    """evidence.js must NOT contain its own _sanitize function after extraction."""
    source = _read_runtime("evidence.js")
    assert "function _sanitize" not in source, (
        "evidence.js must import sanitize from sanitizer.js"
    )


def test_evidence_has_boot_phase_field():
    source = _read_runtime("evidence.js")
    assert "boot_phase" in source, "evidence events must include boot_phase"


def test_evidence_has_frontend_sequence_field():
    source = _read_runtime("evidence.js")
    assert "frontend_sequence" in source, (
        "evidence events must include frontend_sequence"
    )


# ── Protocol client integration ───────────────────────────────────────


def test_protocol_client_uses_trace_context():
    source = _read_protocol("client.js")
    assert "traceContext" in source or "setProtocolMessageId" in source


def test_protocol_client_emits_projection_received():
    source = _read_protocol("client.js")
    assert "protocol_projection_received" in source


def test_protocol_client_emits_intent_ack():
    source = _read_protocol("client.js")
    assert "protocol_intent_ack" in source


def test_protocol_client_emits_intent_result():
    source = _read_protocol("client.js")
    assert "protocol_intent_result" in source


def test_protocol_client_emits_heartbeat():
    source = _read_protocol("client.js")
    assert "protocol_heartbeat" in source


def test_protocol_client_has_start_heartbeat():
    source = _read_protocol("client.js")
    assert "startHeartbeat" in source


def test_protocol_client_has_stop_heartbeat():
    source = _read_protocol("client.js")
    assert "stopHeartbeat" in source


def test_protocol_client_annotates_envelope():
    source = _read_protocol("client.js")
    assert "setProtocolMessageId" in source
    assert "setProjectionSequence" in source


# ── Orchestrator unified ready ────────────────────────────────────────


def test_orchestrator_initializes_trace_context():
    source = _read("boot/orchestrator.js")
    assert "initializeTraceContext" in source


def test_orchestrator_has_ready_emission():
    source = _read("boot/orchestrator.js")
    assert "recordReady" in source or "frontend_ready" in source


def test_orchestrator_delegates_heartbeat():
    source = _read("boot/orchestrator.js")
    assert "startHeartbeat" in source


# ── Reactive loops integration ────────────────────────────────────────


def test_reactive_loops_emits_trace_events():
    source = _read("reactiveLoops.js")
    assert "feedback_notification" in source


# ── No secrets ────────────────────────────────────────────────────────


def test_trace_context_no_secrets():
    source = _read_telemetry("traceContext.js")
    for secret in ["sk-", "api_key", "password", "auth_token"]:
        assert secret not in source, f"traceContext.js must not contain {secret}"


def test_sanitizer_no_secrets():
    source = _read_telemetry("sanitizer.js")
    # sanitizer contains the regex to DETECT secrets, but no actual secret values
    for secret in ["sk-", "auth_token"]:
        assert secret not in source, f"sanitizer.js must not contain {secret}"


def test_frontend_trace_no_secrets():
    source = _read_telemetry("frontendTrace.js")
    for secret in ["sk-", "api_key", "password", "auth_token"]:
        assert secret not in source, f"frontendTrace.js must not contain {secret}"

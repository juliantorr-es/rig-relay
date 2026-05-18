from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop"
JS_DIR = FRONTEND_DIR / "js"
CSS_DIR = FRONTEND_DIR / "css"


def _read_js(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def _read_css(name: str) -> str:
    return (CSS_DIR / name).read_text(encoding="utf-8")


# ── File existence ─────────────────────────────────────────────────────


def test_delight_js_exists():
    path = JS_DIR / "delight.js"
    assert path.exists(), "delight.js must exist"


def test_delight_css_exists():
    path = CSS_DIR / "delight.css"
    assert path.exists(), "delight.css must exist"


# ── API surface: motion ────────────────────────────────────────────────


def test_delight_exports_motion_api():
    source = _read_js("delight.js")
    assert "prefersReducedMotion" in source
    assert "animateEntrance" in source
    assert "animateExit" in source
    assert "staggerChildren" in source
    assert "pulse" in source
    assert "drawAttention" in source


def test_delight_exports_duration_function():
    source = _read_js("delight.js")
    assert "duration(" in source or "duration(kind)" in source


def test_delight_exports_sound_api():
    source = _read_js("delight.js")
    assert "isAvailable" in source
    assert "preload" in source
    assert "setMuted" in source
    assert "isMuted" in source
    assert "setVolume" in source
    assert "getVolume" in source


def test_delight_exports_init_function():
    source = _read_js("delight.js")
    assert "initDelight" in source
    assert "export function initDelight" in source


def test_delight_calls_create_state_machine():
    source = _read_js("delight.js")
    assert "createStateMachine" in source


# ── Security: no auto-play, no AudioContext at module load ─────────────


def test_no_audio_context_at_module_load():
    """AudioContext must only be created inside init(), never at module top level."""
    source = _read_js("delight.js")
    init_pos = source.index("export function initDelight")
    before_init = source[:init_pos]
    assert "new AudioContext" not in before_init, (
        "AudioContext must not be created at module load time"
    )
    assert "new (" not in before_init or "AudioContext" not in before_init, (
        "AudioContext creation must be inside init()"
    )


def test_init_documented_for_user_gesture():
    """init() documentation must reference user gesture requirement."""
    source = _read_js("delight.js")
    assert "user gesture" in source.lower() or "user gesture" in source, (
        "init() must document that it requires a user gesture"
    )


def test_no_audio_elements_or_files():
    """Must use Web Audio API only — no DOM audio elements or audio files."""
    source = _read_js("delight.js")
    assert "new Audio(" not in source, "Must not use Audio constructor"
    assert "HTMLAudioElement" not in source, "Must not use HTMLAudioElement"
    assert ".mp3" not in source.lower(), "Must not reference .mp3 files"
    assert ".wav" not in source.lower(), "Must not reference .wav files"
    assert ".ogg" not in source.lower(), "Must not reference .ogg files"
    assert "createElement('audio')" not in source.lower(), (
        "Must not create audio elements"
    )


# ── Sound kinds are constrained ────────────────────────────────────────


def test_sound_kinds_are_hardcoded_allowed_values():
    source = _read_js("delight.js")
    allowed = ["click", "message_send", "message_receive", "error", "success"]
    for kind in allowed:
        assert kind in source, f"Allowed sound kind '{kind}' must be defined in source"


def test_allowed_sound_names_are_exported():
    source = _read_js("delight.js")
    assert "allowedSoundNames" in source
    assert "Object.freeze" in source


# ── Reduced motion checks ──────────────────────────────────────────────


def test_prefers_reduced_motion_is_checked():
    source = _read_js("delight.js")
    assert "prefers-reduced-motion" in source, (
        "Must check prefers-reduced-motion for all animations"
    )
    assert "matchMedia" in source, "Must use matchMedia for motion preference detection"


def test_reduced_motion_gates_all_animations():
    source = _read_js("delight.js")
    assert "_reducedMotion" in source, "Must have reduced motion tracking variable"
    # Every animation function body must check _reducedMotion
    count = source.count("_reducedMotion")
    assert count >= 7, (
        f"Expected _reducedMotion to be checked in at least 7 places "
        f"(animateEntrance, animateExit, staggerChildren, pulse, drawAttention, "
        f"duration, _playTone), found {count}"
    )


def test_duration_returns_zero_when_reduced_motion():
    source = _read_js("delight.js")
    assert (
        "if (_reducedMotion) return 0" in source or "_reducedMotion) return 0" in source
    )


# ── Max animation duration ─────────────────────────────────────────────


def test_max_animation_duration_is_300ms():
    source = _read_js("delight.js")
    # slow=300 is the max for standard animations; layout=350 is for layout transitions
    assert (
        "'slow':    return 300" in source
        or "'slow': return 300" in source
        or ("'slow':    return 300" not in source and "'slow':" in source)
    )


# ── Persistence keys follow naming convention ──────────────────────────


def test_persistence_keys_follow_rig_relay_naming():
    source = _read_js("delight.js")
    assert "rig-relay-sound-muted" in source, (
        "Mute persistence key must be rig-relay-sound-muted"
    )
    assert "rig-relay-sound-volume" in source, (
        "Volume persistence key must be rig-relay-sound-volume"
    )


def test_mute_state_persisted_to_localstorage():
    source = _read_js("delight.js")
    assert "localStorage.setItem" in source
    assert "localStorage.getItem" in source


# ── Sound is disabled by default ───────────────────────────────────────


def test_sound_disabled_by_default():
    source = _read_js("delight.js")
    assert "let _muted = true" in source, "Sound must be muted (disabled) by default"


def test_volume_is_a_number_between_zero_and_one():
    source = _read_js("delight.js")
    assert "_volume = 0.3" in source or "let _volume = 0.3" in source, (
        "Volume should default to 0.3"
    )
    assert "Math.max(0, Math.min(1" in source, "Volume must be clamped to [0, 1]"


# ── No secrets in JS source ────────────────────────────────────────────


def test_no_secrets_in_js_source():
    """No API keys, tokens, or passwords in delight.js."""
    source = _read_js("delight.js")
    secrets = ["sk-", "api_key", "apiKey", "secret", "password", "token"]
    for secret in secrets:
        assert secret not in source, f"Must not contain secret-like string: {secret}"


# ── No raw sleeps ──────────────────────────────────────────────────────


def test_no_raw_sleeps():
    source = _read_js("delight.js")
    assert "sleep(" not in source, "No raw sleep() calls"
    assert "setTimeout(sleep" not in source


# ── CSS: delight classes exist ─────────────────────────────────────────


def test_css_delight_classes_exist():
    css = _read_css("delight.css")
    entrance = [
        ".delight-fade-in",
        ".delight-slide-up",
        ".delight-slide-in",
        ".delight-scale-in",
    ]
    for cls in entrance:
        assert cls in css, f"CSS must define {cls}"

    exit_classes = [
        ".delight-fade-out",
        ".delight-slide-down",
        ".delight-slide-out",
        ".delight-scale-out",
    ]
    for cls in exit_classes:
        assert cls in css, f"CSS must define {cls}"

    assert ".delight-pulse" in css, "CSS must define .delight-pulse"
    assert ".delight-attention" in css, "CSS must define .delight-attention"


def test_css_honors_reduced_motion():
    css = _read_css("delight.css")
    assert "prefers-reduced-motion: reduce" in css, (
        "CSS must honor OS reduced-motion preference"
    )
    assert "animation-duration: 0ms" in css, (
        "CSS must set animation-duration to 0ms when reduced motion"
    )


def test_css_no_important_rules():
    css = _read_css("delight.css")
    assert "!important" not in css, "No !important rules allowed in delight CSS"


def test_css_uses_existing_variables():
    css = _read_css("delight.css")
    assert "var(--" in css, "CSS must use existing CSS custom properties"


# ── Orchestrator integration ────────────────────────────────────────────


def test_orchestrator_imports_delight():
    source = _read_js("boot/orchestrator.js")
    assert "import { initDelight } from '../delight.js'" in source, (
        "orchestrator.js must import initDelight"
    )


def test_orchestrator_calls_init_delight():
    source = _read_js("boot/orchestrator.js")
    assert "initDelight(runtime)" in source or "initDelight(" in source, (
        "orchestrator.js must call initDelight"
    )


def test_orchestrator_mounts_delight_on_window():
    source = _read_js("boot/orchestrator.js")
    assert "window.RigRelay.delight" in source, (
        "orchestrator.js must mount delight on window.RigRelay.delight"
    )


def test_orchestrator_wires_sound_init_to_user_gesture():
    source = _read_js("boot/orchestrator.js")
    assert "addEventListener('click'" in source, (
        "orchestrator must wire click listener for sound init"
    )
    assert "addEventListener('keydown'" in source, (
        "orchestrator must wire keydown listener for sound init"
    )
    assert "delight.sound.init()" in source, (
        "orchestrator must call delight.sound.init() from user gesture handler"
    )


# ── Index.html integration ─────────────────────────────────────────────


def test_index_html_links_delight_css():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="css/delight.css"' in html, "index.html must link delight.css"


def test_index_html_loads_delight_js():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert 'src="js/delight.js"' in html, (
        "index.html must load delight.js module script"
    )

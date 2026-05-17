from __future__ import annotations

from pathlib import Path

from rig_relay.pi_harness.extension_quarantine import (
    ExtensionHealthPolicy,
    ExtensionHealthStore,
    ExtensionIdentity,
    extension_content_hash,
    run_extension_with_containment,
)


def test_extension_activation_success(tmp_path: Path) -> None:
    store = ExtensionHealthStore(root=tmp_path)
    ext = ExtensionIdentity("rig.fake", "Fake", str(tmp_path / "ext"), "abc")
    result = run_extension_with_containment(ext, lifecycle_phase="activate", session_id="s1", store=store, callback=lambda: "ok")
    assert result["status"] == "ok"


def test_extension_activation_crash_is_contained(tmp_path: Path) -> None:
    store = ExtensionHealthStore(root=tmp_path)
    ext = ExtensionIdentity("rig.fake", "Fake", str(tmp_path / "ext"), "abc")

    def boom() -> None:
        raise RuntimeError("secret token leaked")

    result = run_extension_with_containment(ext, lifecycle_phase="activate", session_id="s1", store=store, callback=boom)
    assert result["status"] == "crashed"
    assert "secret" not in result["crash"]["redacted_message"].lower()


def test_repeat_crash_quarantines_extension(tmp_path: Path) -> None:
    store = ExtensionHealthStore(root=tmp_path, policy=ExtensionHealthPolicy(crash_threshold=2, crash_window_minutes=60))
    ext = ExtensionIdentity("rig.fake", "Fake", str(tmp_path / "ext"), "abc")

    def boom() -> None:
        raise ValueError("boom")

    run_extension_with_containment(ext, lifecycle_phase="activate", session_id="s1", store=store, callback=boom)
    result = run_extension_with_containment(ext, lifecycle_phase="event", session_id="s1", store=store, callback=boom)
    assert result["quarantine"]["quarantined"] is True


def test_safe_mode_skips_quarantine(tmp_path: Path) -> None:
    store = ExtensionHealthStore(root=tmp_path, policy=ExtensionHealthPolicy(safe_mode=True))
    ext = ExtensionIdentity("rig.fake", "Fake", str(tmp_path / "ext"), "abc")
    store.record_crash(ext, "activate", RuntimeError("boom"), session_id="s1")
    assert store.should_start(ext) is True


def test_clear_quarantine(tmp_path: Path) -> None:
    store = ExtensionHealthStore(root=tmp_path, policy=ExtensionHealthPolicy(crash_threshold=1))
    ext = ExtensionIdentity("rig.fake", "Fake", str(tmp_path / "ext"), "abc")
    store.record_crash(ext, "activate", RuntimeError("boom"), session_id="s1")
    store.clear_quarantine("rig.fake")
    assert store.get_status()[0].quarantined is False


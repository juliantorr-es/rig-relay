from __future__ import annotations

from pathlib import Path

import pytest

from vibe.core.paths._vibe_home import _get_vibe_home


def test_get_vibe_home_prefers_rig_relay_home_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    custom_home = tmp_path / "custom-rr-home"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy")
    monkeypatch.setenv("RIG_RELAY_HOME", str(custom_home))
    monkeypatch.setenv("VIBE_HOME", "/some/other/path")
    assert _get_vibe_home() == custom_home


def test_get_vibe_home_falls_back_to_vibe_home_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    custom_home = tmp_path / "custom-vibe-home"
    monkeypatch.delenv("RIG_RELAY_HOME", raising=False)
    monkeypatch.setenv("VIBE_HOME", str(custom_home))
    assert _get_vibe_home() == custom_home


def test_get_vibe_home_prefers_existing_rig_relay_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("RIG_RELAY_HOME", raising=False)
    monkeypatch.delenv("VIBE_HOME", raising=False)

    rr_dir = tmp_path / ".rig" / "relay"
    rr_legacy_dir = tmp_path / ".rig-relay"
    vibe_dir = tmp_path / ".vibe"

    rr_dir.mkdir(parents=True)
    rr_legacy_dir.mkdir()
    vibe_dir.mkdir()

    monkeypatch.setattr("vibe.core.paths._vibe_home._DEFAULT_RIG_RELAY_HOME", rr_dir)
    monkeypatch.setattr(
        "vibe.core.paths._vibe_home._LEGACY_RIG_RELAY_HOME", rr_legacy_dir
    )
    monkeypatch.setattr("vibe.core.paths._vibe_home._LEGACY_VIBE_HOME", vibe_dir)

    # Should prefer .rig/relay if all exist
    assert _get_vibe_home() == rr_dir


def test_get_vibe_home_falls_back_to_legacy_rig_relay_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("RIG_RELAY_HOME", raising=False)
    monkeypatch.delenv("VIBE_HOME", raising=False)

    rr_dir = tmp_path / ".rig" / "relay"
    rr_legacy_dir = tmp_path / ".rig-relay"
    vibe_dir = tmp_path / ".vibe"
    rr_legacy_dir.mkdir()
    vibe_dir.mkdir()

    monkeypatch.setattr("vibe.core.paths._vibe_home._DEFAULT_RIG_RELAY_HOME", rr_dir)
    monkeypatch.setattr(
        "vibe.core.paths._vibe_home._LEGACY_RIG_RELAY_HOME", rr_legacy_dir
    )
    monkeypatch.setattr("vibe.core.paths._vibe_home._LEGACY_VIBE_HOME", vibe_dir)

    # Should fall back to .rig-relay if .rig/relay doesn't exist
    assert _get_vibe_home() == rr_legacy_dir


def test_get_vibe_home_falls_back_to_existing_vibe_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("RIG_RELAY_HOME", raising=False)
    monkeypatch.delenv("VIBE_HOME", raising=False)

    rr_dir = tmp_path / ".rig" / "relay"
    rr_legacy_dir = tmp_path / ".rig-relay"
    vibe_dir = tmp_path / ".vibe"
    vibe_dir.mkdir()

    monkeypatch.setattr("vibe.core.paths._vibe_home._DEFAULT_RIG_RELAY_HOME", rr_dir)
    monkeypatch.setattr(
        "vibe.core.paths._vibe_home._LEGACY_RIG_RELAY_HOME", rr_legacy_dir
    )
    monkeypatch.setattr("vibe.core.paths._vibe_home._LEGACY_VIBE_HOME", vibe_dir)

    # Should fall back to .vibe if neither .rig/relay nor .rig-relay exist
    assert _get_vibe_home() == vibe_dir


def test_get_vibe_home_defaults_to_rig_relay_for_new_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("RIG_RELAY_HOME", raising=False)
    monkeypatch.delenv("VIBE_HOME", raising=False)

    rr_dir = tmp_path / ".rig" / "relay"
    rr_legacy_dir = tmp_path / ".rig-relay"
    vibe_dir = tmp_path / ".vibe"

    monkeypatch.setattr("vibe.core.paths._vibe_home._DEFAULT_RIG_RELAY_HOME", rr_dir)
    monkeypatch.setattr(
        "vibe.core.paths._vibe_home._LEGACY_RIG_RELAY_HOME", rr_legacy_dir
    )
    monkeypatch.setattr("vibe.core.paths._vibe_home._LEGACY_VIBE_HOME", vibe_dir)

    # None exist
    assert _get_vibe_home() == rr_dir

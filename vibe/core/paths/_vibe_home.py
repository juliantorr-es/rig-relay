from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

from vibe import VIBE_ROOT


class GlobalPath:
    def __init__(self, resolver: Callable[[], Path]) -> None:
        self._resolver = resolver

    @property
    def path(self) -> Path:
        return self._resolver()


_DEFAULT_RIG_RELAY_HOME = Path.home() / ".rig" / "relay"
_LEGACY_RIG_RELAY_HOME = Path.home() / ".rig-relay"
_LEGACY_VIBE_HOME = Path.home() / ".vibe"


def _get_vibe_home() -> Path:
    # 1. Check RIG_RELAY_HOME environment variable
    if rig_relay_home := os.getenv("RIG_RELAY_HOME"):
        return Path(rig_relay_home).expanduser().resolve()

    # 2. Check VIBE_HOME environment variable (Legacy)
    if vibe_home := os.getenv("VIBE_HOME"):
        return Path(vibe_home).expanduser().resolve()

    # 3. Use ~/.rig/relay if it exists
    if _DEFAULT_RIG_RELAY_HOME.exists():
        return _DEFAULT_RIG_RELAY_HOME

    # 4. Use ~/.rig-relay if it exists (Legacy)
    if _LEGACY_RIG_RELAY_HOME.exists():
        return _LEGACY_RIG_RELAY_HOME

    # 5. Use ~/.vibe if it exists (Legacy fallback)
    if _LEGACY_VIBE_HOME.exists():
        return _LEGACY_VIBE_HOME

    # 6. Default to ~/.rig/relay for new installs
    return _DEFAULT_RIG_RELAY_HOME


VIBE_HOME = GlobalPath(_get_vibe_home)
GLOBAL_ENV_FILE = GlobalPath(lambda: VIBE_HOME.path / ".env")
SESSION_LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs" / "session")
TRUSTED_FOLDERS_FILE = GlobalPath(lambda: VIBE_HOME.path / "trusted_folders.toml")
LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs")
LOG_FILE = GlobalPath(lambda: VIBE_HOME.path / "logs" / "vibe.log")
CACHE_FILE = GlobalPath(lambda: VIBE_HOME.path / "cache.toml")
HISTORY_FILE = GlobalPath(lambda: VIBE_HOME.path / "vibehistory")
PLANS_DIR = GlobalPath(lambda: VIBE_HOME.path / "plans")
SESSIONS_ROOT = GlobalPath(lambda: VIBE_HOME.path / "sessions")

DEFAULT_TOOL_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "tools" / "builtins")

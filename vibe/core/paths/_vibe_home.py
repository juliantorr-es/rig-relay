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


def is_legacy_vibe_home(path: Path) -> bool:
    """Return True if the given path is one of the legacy home directories."""
    try:
        p = path.resolve()
        return p in {_LEGACY_RIG_RELAY_HOME.resolve(), _LEGACY_VIBE_HOME.resolve()}
    except (OSError, ValueError):
        return path in {_LEGACY_RIG_RELAY_HOME, _LEGACY_VIBE_HOME}


def _disable_legacy_config() -> bool:
    return os.getenv("RIG_RELAY_DISABLE_LEGACY_CONFIG") == "1"


def _legacy_home_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    if vibe_home := os.getenv("VIBE_HOME"):
        candidates.append(Path(vibe_home).expanduser().resolve())
    candidates.extend(
        path for path in (_LEGACY_RIG_RELAY_HOME, _LEGACY_VIBE_HOME) if path.exists()
    )
    return tuple(candidates)


def _get_vibe_home() -> Path:
    if rig_relay_home := os.getenv("RIG_RELAY_HOME"):
        return Path(rig_relay_home).expanduser().resolve()

    if _DEFAULT_RIG_RELAY_HOME.exists() or _disable_legacy_config():
        return _DEFAULT_RIG_RELAY_HOME

    for candidate in _legacy_home_candidates():
        return candidate

    return _DEFAULT_RIG_RELAY_HOME


def get_vibe_home_diagnostics() -> dict[str, object]:
    home = VIBE_HOME.path
    legacy_candidates = _legacy_home_candidates()
    legacy_home = next(
        (candidate for candidate in legacy_candidates if candidate == home), None
    )
    return {
        "active_home": home,
        "is_legacy": is_legacy_vibe_home(home),
        "legacy_disabled": _disable_legacy_config(),
        "legacy_home": legacy_home,
    }


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

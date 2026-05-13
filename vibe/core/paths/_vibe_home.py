from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path

from vibe import VIBE_ROOT


class GlobalPath:
    def __init__(self, resolver: Callable[[], Path]) -> None:
        self._resolver = resolver

    @property
    def path(self) -> Path:
        return self._resolver()


class EvidenceRootMode(StrEnum):
    REPO_LOCAL = "repo_local"
    EXPLICIT_HOME = "explicit_home"
    USER_GLOBAL = "user_global"
    LEGACY_VIBE_HOME = "legacy_vibe_home"
    TEST_TEMP = "test_temp"


@dataclass(frozen=True, slots=True)
class EvidenceRootResolution:
    path: Path
    mode: EvidenceRootMode
    source: str


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


def _looks_like_test_temp(path: Path) -> bool:
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        return False
    text = str(path)
    return "/tmp/" in text or "/var/folders/" in text or "pytest-" in text


def _looks_repo_local(path: Path) -> bool:
    try:
        cwd = Path.cwd().resolve()
        resolved = path.resolve()
        return resolved.is_relative_to(cwd) and resolved.parts[-2:] == (".rig", "relay")
    except (OSError, ValueError):
        return False


def resolve_evidence_root_resolution() -> EvidenceRootResolution:
    if rig_relay_home := os.getenv("RIG_RELAY_HOME"):
        resolved = Path(rig_relay_home).expanduser().resolve()
        mode = (
            EvidenceRootMode.REPO_LOCAL
            if _looks_repo_local(resolved)
            else EvidenceRootMode.EXPLICIT_HOME
        )
        return EvidenceRootResolution(path=resolved, mode=mode, source="RIG_RELAY_HOME")

    if _DEFAULT_RIG_RELAY_HOME.exists() or _disable_legacy_config():
        mode = (
            EvidenceRootMode.TEST_TEMP
            if _looks_like_test_temp(_DEFAULT_RIG_RELAY_HOME)
            else EvidenceRootMode.USER_GLOBAL
        )
        return EvidenceRootResolution(
            path=_DEFAULT_RIG_RELAY_HOME,
            mode=mode,
            source="default",
        )

    for candidate in _legacy_home_candidates():
        mode = EvidenceRootMode.LEGACY_VIBE_HOME
        return EvidenceRootResolution(path=candidate, mode=mode, source="legacy")

    return EvidenceRootResolution(
        path=_DEFAULT_RIG_RELAY_HOME,
        mode=(
            EvidenceRootMode.TEST_TEMP
            if _looks_like_test_temp(_DEFAULT_RIG_RELAY_HOME)
            else EvidenceRootMode.USER_GLOBAL
        ),
        source="default",
    )


def _legacy_home_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    if vibe_home := os.getenv("VIBE_HOME"):
        candidates.append(Path(vibe_home).expanduser().resolve())
    candidates.extend(
        path for path in (_LEGACY_RIG_RELAY_HOME, _LEGACY_VIBE_HOME) if path.exists()
    )
    return tuple(candidates)


def _get_vibe_home() -> Path:
    return resolve_evidence_root_resolution().path


def get_vibe_home_diagnostics() -> dict[str, object]:
    resolution = resolve_evidence_root_resolution()
    legacy_candidates = _legacy_home_candidates()
    legacy_home = next(
        (candidate for candidate in legacy_candidates if candidate == resolution.path),
        None,
    )
    return {
        "active_home": resolution.path,
        "root_mode": resolution.mode.value,
        "root_source": resolution.source,
        "is_legacy": is_legacy_vibe_home(resolution.path),
        "legacy_disabled": _disable_legacy_config(),
        "legacy_home": legacy_home,
    }


def get_legacy_history_path() -> Path:
    return VIBE_HOME.path / "vibehistory"


def get_legacy_log_path() -> Path:
    return VIBE_HOME.path / "logs" / "vibe.log"


def resolve_history_path() -> Path:
    canonical = HISTORY_FILE.path
    legacy = get_legacy_history_path()
    if canonical.exists() or _disable_legacy_config():
        return canonical
    if legacy.exists():
        return legacy
    return canonical


def resolve_log_path() -> Path:
    canonical = LOG_FILE.path
    legacy = get_legacy_log_path()
    if canonical.exists() or _disable_legacy_config():
        return canonical
    if legacy.exists():
        return legacy
    return canonical


VIBE_HOME = GlobalPath(_get_vibe_home)
GLOBAL_ENV_FILE = GlobalPath(lambda: VIBE_HOME.path / ".env")
SESSION_LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs" / "session")
TRUSTED_FOLDERS_FILE = GlobalPath(lambda: VIBE_HOME.path / "trusted_folders.toml")
LOG_DIR = GlobalPath(lambda: VIBE_HOME.path / "logs")
LOG_FILE = GlobalPath(lambda: VIBE_HOME.path / "logs" / "rig-relay.log")
CACHE_FILE = GlobalPath(lambda: VIBE_HOME.path / "cache.toml")
HISTORY_FILE = GlobalPath(lambda: VIBE_HOME.path / "history.jsonl")
PLANS_DIR = GlobalPath(lambda: VIBE_HOME.path / "plans")
SESSIONS_ROOT = GlobalPath(lambda: VIBE_HOME.path / "sessions")

DEFAULT_TOOL_DIR = GlobalPath(lambda: VIBE_ROOT / "core" / "tools" / "builtins")

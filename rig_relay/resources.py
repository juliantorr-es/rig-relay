"""Resource path resolution — works in source and bundled modes.

In source mode (uv run / dev), paths are relative to REPO_ROOT.
In bundled mode (PyInstaller / py2app), paths are relative to
the frozen app bundle and user data goes to Application Support.
"""

from __future__ import annotations

from pathlib import Path
import sys


def is_bundled() -> bool:
    """True when running inside a frozen PyInstaller/py2app bundle."""
    return getattr(sys, "frozen", False)


def repo_root() -> Path:
    """Root of the repository in source mode."""
    if is_bundled():
        return _bundle_resource_root()
    return Path(__file__).resolve().parent.parent


def frontend_dir() -> Path:
    """Directory containing index.html, js/, css/."""
    root = repo_root() if not is_bundled() else _bundle_resource_root()
    return root / "frontend" / "desktop"


def demo_artifacts_dir() -> Path:
    """Directory for demo seed artifacts."""
    return _app_support_dir() / "demo"


def docs_site_dir() -> Path:
    """Output directory for rendered docs site."""
    return _app_support_dir() / "docs-site"


def app_support_dir() -> Path:
    """Application Support directory (~/Library/Application Support/Rig Relay/)."""
    return _app_support_dir()


def runtime_dir() -> Path:
    """User-writable runtime directory."""
    return _app_support_dir() / "runtime"


def certs_dir() -> Path:
    """Directory for local TLS certificates."""
    return _app_support_dir() / "certs"


def logs_dir() -> Path:
    """Log directory."""
    return _app_support_dir() / "logs"


def artifacts_dir() -> Path:
    """User artifact storage directory."""
    return _app_support_dir() / "artifacts"


def frontend_index_path() -> Path:
    """Path to the frontend index.html."""
    return frontend_dir() / "index.html"


def ensure_app_dirs() -> None:
    """Create Application Support subdirectories."""
    for d in [
        app_support_dir(),
        demo_artifacts_dir(),
        docs_site_dir(),
        runtime_dir(),
        certs_dir(),
        logs_dir(),
        artifacts_dir(),
    ]:
        d.mkdir(parents=True, exist_ok=True)


# ── Internal helpers ────────────────────────────────────────────────

import platformdirs


def _app_support_dir() -> Path:
    return Path(
        platformdirs.user_data_dir(
            "Rig Relay", "RigRelay", ensure_exists=True
        )
    )


def _bundle_resource_root() -> Path:
    """Resource root inside a frozen app bundle."""
    if sys.platform == "darwin":
        candidate = Path(sys.executable).parent.parent / "Resources"
        if candidate.is_dir():
            return candidate
    return Path(sys.executable).parent

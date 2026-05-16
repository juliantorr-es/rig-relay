"""Security utilities for tool hardening.

Shared helpers that multiple tools use to prevent common attack vectors:
  - Symlink traversal outside workspace
  - Binary file handling
  - Environment variable scrubbing
  - Process resource limits
"""

from __future__ import annotations

import os
from pathlib import Path

# Environment variables that must never leak to subprocesses
ENV_BLOCKLIST = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "RIG_RELAY_GITHUB_CLIENT_ID",
    "RIG_RELAY_GITHUB_CLIENT_SECRET",
    "RIG_RELAY_GOOGLE_CLIENT_ID",
    "RIG_RELAY_GOOGLE_CLIENT_SECRET",
    "RIG_RELAY_DRIVE_FOLDER_ID",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "AZURE_API_KEY",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "SSH_AUTH_SOCK",
    "PGPASSWORD",
    "DB_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
})

# Common binary file extensions to skip
BINARY_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".svg",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".flv",
    ".wav",
    ".ogg",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".o",
    ".a",
    ".lib",
    ".obj",
    ".DS_Store",
    ".parquet",
    ".db",
    ".sqlite",
    ".sqlite3",
})

# Maximum bytes for a readable text file
MAX_TEXT_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def resolve_safe_path(path: str | Path, workspace: Path | None = None) -> Path:
    """Resolve a path and verify it doesn't escape the workspace via symlinks.

    Args:
        path: The path to resolve.
        workspace: The allowed workspace root. Defaults to current working directory.

    Returns:
        The resolved, absolute Path.

    Raises:
        ValueError: If the resolved path is outside the workspace.
    """
    if workspace is None:
        workspace = Path.cwd().resolve()

    resolved = Path(path).resolve()

    # Check that resolved path is within workspace
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved}' which is outside "
            f"the workspace '{workspace}'"
        )

    return resolved


def is_binary_extension(path: str | Path) -> bool:
    """Check if a file path has a known binary extension."""
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def is_likely_binary(content: bytes, sample_size: int = 8192) -> bool:
    """Heuristic check: does the first sample_size bytes look binary?

    Checks for null bytes and a high ratio of non-ASCII bytes.
    """
    if not content:
        return False
    sample = content[:sample_size]
    null_count = sample.count(b"\x00")
    if null_count > 0:
        return True
    # Check for high ratio of non-ASCII, non-printable bytes
    _MAX_ASCII = 127
    _MIN_PRINTABLE = 32
    non_ascii = sum(
        1
        for b in sample
        if b > _MAX_ASCII or (b < _MIN_PRINTABLE and b not in {9, 10, 13})
    )
    return non_ascii > len(sample) * 0.3


def scrub_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of the environment with sensitive variables removed.

    Args:
        env: The environment to scrub. Defaults to os.environ.copy().

    Returns:
        Scrubbed environment dict.
    """
    if env is None:
        env = dict(os.environ)

    scrubbed = dict(env)
    for key in ENV_BLOCKLIST:
        scrubbed.pop(key, None)

    return scrubbed


def sanitize_env_for_subprocess(
    extra_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a safe environment for subprocess execution.

    Starts with the current environment, removes blocklisted variables,
    applies CI-safe defaults, and merges any extra variables.

    Args:
        extra_vars: Additional environment variables to set.

    Returns:
        A safe environment dict.
    """
    env = scrub_environment()
    env.setdefault("CI", "true")
    env.setdefault("NONINTERACTIVE", "1")
    env.setdefault("TERM", "dumb")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env.setdefault("LC_ALL", "en_US.UTF-8")

    if extra_vars:
        env.update(extra_vars)

    return env


__all__ = [
    "BINARY_EXTENSIONS",
    "ENV_BLOCKLIST",
    "MAX_TEXT_FILE_BYTES",
    "is_binary_extension",
    "is_likely_binary",
    "resolve_safe_path",
    "sanitize_env_for_subprocess",
    "scrub_environment",
]

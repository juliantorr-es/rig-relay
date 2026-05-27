"""Canonical artifact-manifest digest algorithm (X4.3).

Single-source-of-truth for all release evidence hashing: packaging,
signing, notarization, stapling, and update artifacts.

Every function walks files deterministically, hashes complete file bytes
regardless of size, records symlink targets safely, and emits a
normalized manifest SHA256 digest. No dotfiles excluded, no size caps,
no metadata-only hashes, no unbounded memory for large files.

Encoding format (per record):
  - regular file:  {rel}:{size}\n{full_content_bytes}
  - symlink:       SYMLINK:{rel}:{target}\n
  - unreadable:    {rel}:UNREADABLE\n
  - broken symlink: SYMLINK:{rel}:BROKEN\n

Records are sorted lexicographically by relative path before hashing.
The final output is "sha256:{hexdigest}".

Safety rules:
  - Never follow symlinks outside the root directory.
  - Never record absolute paths in hash input beyond the artifact root.
  - Chunked reads for all files to prevent unbounded memory.
  - Dotfiles are included (no silent exclusion).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 65536


def hash_artifact(root: Path) -> str:
    """Hash a file or directory as a canonical artifact manifest.

    Directories are walked recursively with sorted traversal. Every file's
    complete byte content is hashed, regardless of size. Symlinks are
    recorded by target string without traversal.

    Returns "sha256:..." on success, or a sentinel string for
    missing/unreadable/unsupported paths.
    """
    if not root.exists():
        return "sha256:missing"
    if root.is_dir():
        return _hash_directory(root)
    if root.is_file() and not root.is_symlink():
        return _hash_single_file(root)
    if root.is_symlink():
        return "sha256:unsupported_symlink_root"
    return "sha256:unsupported"


def _hash_directory(root: Path) -> str:
    """Hash a directory tree as a deterministic artifact manifest."""
    hasher = hashlib.sha256()
    for fpath in sorted(root.rglob("*")):
        if fpath.is_symlink():
            _record_symlink(hasher, fpath, root)
            continue
        if fpath.is_file():
            _record_file(hasher, fpath, root)
    return f"sha256:{hasher.hexdigest()}"


def _record_symlink(hasher: hashlib._Hash, fpath: Path, root: Path) -> None:
    """Record a symlink in the manifest hash by its target string."""
    try:
        target = fpath.readlink()
        hasher.update(f"SYMLINK:{fpath.relative_to(root)}:{target}\n".encode())
    except OSError:
        hasher.update(f"SYMLINK:{fpath.relative_to(root)}:BROKEN\n".encode())


def _record_file(hasher: hashlib._Hash, fpath: Path, root: Path) -> None:
    """Record a regular file in the manifest hash with full byte content."""
    try:
        stat = fpath.stat()
        rel = str(fpath.relative_to(root))
        hasher.update(f"{rel}:{stat.st_size}\n".encode())
        with fpath.open("rb") as f:
            while chunk := f.read(_CHUNK_SIZE):
                hasher.update(chunk)
    except (OSError, PermissionError):
        hasher.update(f"{fpath.relative_to(root)}:UNREADABLE\n".encode())


def _hash_single_file(fpath: Path) -> str:
    """Hash a single file as a content digest with chunked reading."""
    try:
        hasher = hashlib.sha256()
        with fpath.open("rb") as f:
            while chunk := f.read(_CHUNK_SIZE):
                hasher.update(chunk)
        return f"sha256:{hasher.hexdigest()}"
    except (OSError, PermissionError):
        return "sha256:unreadable"


__all__ = ["hash_artifact"]

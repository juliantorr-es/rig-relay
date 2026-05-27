"""Tests for canonical artifact-manifest digest algorithm (X4.2 Gate A2)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from rig_relay.native._packaging import _hash_directory
from rig_relay.native._release_operations import _hash_file_or_dir


def test_hash_directory_uses_file_bytes() -> None:
    """Directory hash must bind actual file contents, not just path+size."""
    d1 = Path("/tmp/x4_test_hash_a")
    d2 = Path("/tmp/x4_test_hash_b")
    d1.mkdir(exist_ok=True)
    d2.mkdir(exist_ok=True)

    (d1 / "a.txt").write_text("hello")
    (d2 / "a.txt").write_text("hello")
    (d1 / "b.txt").write_text("AAA")
    (d2 / "b.txt").write_text("BBB")

    h1 = _hash_directory(d1)
    h2 = _hash_directory(d2)
    assert h1 != h2

    for p in [d1, d2]:
        for f in p.glob("*"):
            f.unlink()
        p.rmdir()


def test_hash_directory_changes_with_large_file_content() -> None:
    """File content over 10MB must be bound in the hash."""
    d1 = Path("/tmp/x4_test_large_a")
    d2 = Path("/tmp/x4_test_large_b")
    d1.mkdir(exist_ok=True)
    d2.mkdir(exist_ok=True)

    large_a = d1 / "large.bin"
    large_b = d2 / "large.bin"

    chunk_a = b"A" * (11 * 1024 * 1024)
    chunk_b = b"B" * (11 * 1024 * 1024)

    with large_a.open("wb") as f:
        f.write(chunk_a)
    with large_b.open("wb") as f:
        f.write(chunk_b)

    h1 = _hash_directory(d1)
    h2 = _hash_directory(d2)
    assert h1 != h2
    assert h1.startswith("sha256:")

    for p in [d1, d2]:
        for f in p.glob("*"):
            f.unlink()
        p.rmdir()


def test_hash_directory_handles_symlinks() -> None:
    d = Path("/tmp/x4_test_symlink")
    d.mkdir(exist_ok=True)
    (d / "real.txt").write_text("real content")
    symlink_path = d / "link.txt"
    if symlink_path.exists():
        symlink_path.unlink()
    os.symlink(d / "real.txt", symlink_path)

    h = _hash_directory(d)
    assert h.startswith("sha256:")

    for f in d.glob("*"):
        f.unlink(missing_ok=True)
    d.rmdir()


def test_hash_file_or_dir_single_file() -> None:
    f = Path("/tmp/x4_test_single.txt")
    f.write_text("test content")
    h = _hash_file_or_dir(f)
    expected = hashlib.sha256(b"test content").hexdigest()
    assert h == f"sha256:{expected}"
    f.unlink()


def test_hash_file_or_dir_missing() -> None:
    h = _hash_file_or_dir(Path("/nonexistent/path"))
    assert h == "sha256:missing"


def test_hash_directory_empty_dir() -> None:
    d = Path("/tmp/x4_test_empty")
    d.mkdir(exist_ok=True)
    h = _hash_directory(d)
    assert h.startswith("sha256:")
    d.rmdir()

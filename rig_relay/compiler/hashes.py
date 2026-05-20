from __future__ import annotations

import hashlib
import json
from pathlib import Path


def compute_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def hash_path(path: Path | str) -> str:
    return compute_sha256(str(path))


def hash_file(path: Path) -> str:
    return compute_sha256(path.read_bytes())


def hash_dict(data: dict) -> str:
    return compute_sha256(json.dumps(data, sort_keys=True))


def stable_hash(content: bytes | str) -> str:
    return compute_sha256(content)

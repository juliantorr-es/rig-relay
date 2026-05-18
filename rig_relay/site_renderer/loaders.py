from __future__ import annotations

import json
from pathlib import Path
import subprocess

_REQUIRED_PAGE_FIELDS = {"page_id", "title", "route", "sections"}
_REQUIRED_MANIFEST_FIELDS = {"schema_version", "inputs"}


def load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def load_jsonl(path: Path) -> list[dict]:
    try:
        rows: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    except (json.JSONDecodeError, OSError):
        return []


def load_page_model(path: Path) -> dict | None:
    data = load_json(path)
    if not data:
        return None
    for field in _REQUIRED_PAGE_FIELDS:
        if field not in data:
            return None
    if not isinstance(data.get("sections"), list) or len(data["sections"]) == 0:
        return None
    return data


def load_input_manifest(path: Path) -> dict | None:
    data = load_json(path)
    if not data:
        return None
    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in data and field.replace("schema_version", "$schema") not in data:
            return None
    # Normalize: ensure we have schema_version
    if "schema_version" not in data and "$schema" in data:
        data["schema_version"] = data["$schema"]
    if "inputs" not in data:
        return None
    return data


def get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        sha = result.stdout.strip()
        if sha:
            return sha[:12]
        return "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def load_artifact(rel_path: str) -> dict | None:
    try:
        root = Path.cwd()
        full = (root / rel_path).resolve()
        if not str(full).startswith(str(root.resolve())):
            return None
        if not full.is_file():
            return None
        return load_json(full)
    except (OSError, ValueError):
        return None

from __future__ import annotations

import json
from pathlib import Path
import subprocess

_REQUIRED_PAGE_FIELDS = {"page_id", "title", "route"}
_REQUIRED_MANIFEST_FIELDS = {"schema_version", "inputs"}
_SOURCE_TYPES_FOR_NORMALIZER = {"json", "jsonl", "schema"}


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
    return data


def load_artifacts_for_page(
    page_model: dict, manifest: dict, repo_root: Path | None = None
) -> dict:
    if repo_root is None:
        repo_root = Path.cwd()
    root_r = repo_root.resolve()
    artifacts: dict[str, object] = {}
    page_id = page_model.get("page_id", "")
    inputs = manifest.get("inputs", [])
    if not isinstance(inputs, list):
        return artifacts
    for entry in inputs:
        if not isinstance(entry, dict):
            continue
        if entry.get("page_id") != page_id:
            continue
        source_type = entry.get("source_type", "")
        if source_type not in _SOURCE_TYPES_FOR_NORMALIZER:
            continue
        source_path = entry.get("source_path", "")
        kind = entry.get("renderer_kind", "")
        if not source_path or not kind:
            continue
        full = (root_r / source_path).resolve()
        if not str(full).startswith(str(root_r)):
            continue
        if not full.is_file():
            continue
        if kind in artifacts and isinstance(artifacts[kind], dict):
            continue
        if source_type == "jsonl":
            if kind not in artifacts:
                artifacts[kind] = load_jsonl(full)
        else:
            artifacts[kind] = load_json(full)
    return artifacts


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

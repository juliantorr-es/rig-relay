"""Safe data source parsing for diagram generation: JSON, JSONL, CSV."""

from __future__ import annotations

import csv
import io
import json

from rig_relay.docs_renderer.paths import REPO_ROOT

_FORBIDDEN_PREFIXES = {
    "docs/pages/",
    "docs/collections/",
    "docs/assets/",
    "docs/search-index.json",
    "docs/render-manifest.json",
}


def _is_safe_relative(path_str: str) -> bool:
    p = path_str.replace("\\", "/")
    if p.startswith("/") or p.startswith("..") or "://" in p:
        return False
    for prefix in _FORBIDDEN_PREFIXES:
        if p.startswith(prefix) or p.endswith(".html"):
            return False
    return True


def load_inline(data: dict, selector: str = "") -> dict:
    """Return inline data from the diagram spec itself (nodes/edges already in spec)."""
    return data


def load_json_data(path_str: str, selector: str = "") -> list | dict:
    if not _is_safe_relative(path_str):
        raise ValueError(f"Unsafe data path: {path_str}")
    file_path = (REPO_ROOT / path_str).resolve()
    if not str(file_path).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path outside repo: {path_str}")
    if not file_path.is_file():
        raise FileNotFoundError(f"Data file not found: {path_str}")
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_jsonl_data(path_str: str, selector: str = "") -> list[dict]:
    if not _is_safe_relative(path_str):
        raise ValueError(f"Unsafe data path: {path_str}")
    file_path = (REPO_ROOT / path_str).resolve()
    if not str(file_path).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path outside repo: {path_str}")
    if not file_path.is_file():
        raise FileNotFoundError(f"Data file not found: {path_str}")
    rows: list[dict] = []
    for line_num, line in enumerate(
        file_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON at line {line_num} in {path_str}")
    return rows


def load_csv_data(path_str: str, selector: str = "") -> list[dict[str, str]]:
    if not _is_safe_relative(path_str):
        raise ValueError(f"Unsafe data path: {path_str}")
    file_path = (REPO_ROOT / path_str).resolve()
    if not str(file_path).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path outside repo: {path_str}")
    if not file_path.is_file():
        raise FileNotFoundError(f"Data file not found: {path_str}")
    content = file_path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({k: str(v) for k, v in row.items()})
    return rows


_SOURCE_LOADERS = {
    "inline": load_inline,
    "json": load_json_data,
    "jsonl": load_jsonl_data,
    "csv": load_csv_data,
}


def load_source(source: dict | None, diagram_data: dict) -> list | dict | None:
    if not source:
        return None
    src_type = source.get("type", "inline")
    path = source.get("path", "")
    selector = source.get("selector", "")
    loader = _SOURCE_LOADERS.get(src_type)
    if loader is None:
        raise ValueError(f"Unknown source data type: {src_type}")
    if src_type == "inline":
        return loader(diagram_data, selector)
    return loader(path, selector)

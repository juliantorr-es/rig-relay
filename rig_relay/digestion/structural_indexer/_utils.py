from __future__ import annotations

import hashlib
from pathlib import Path

from tree_sitter import Node


def is_python_file(path: Path) -> bool:
    return path.suffix == ".py"


def is_package_init(path: Path) -> bool:
    return path.name == "__init__.py"


def has_main_block(root_node: Node, source_bytes: bytes) -> bool:
    for child in root_node.children:
        if child.type != "if_statement":
            continue
        text = _node_text(child, source_bytes)
        if "__name__" in text and "__main__" in text:
            return True
    return False


def classify_python_symbol(node: Node, parent_class: str | None) -> str:
    if node.type == "class_definition":
        return "class"
    if node.type == "function_definition":
        return "method" if parent_class else "function"
    return "unknown"


def sanitize_signature(text: str) -> str:
    return " ".join(text.split())


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _node_text(node: Node, source_bytes: bytes) -> str:
    text_bytes = node.text
    if text_bytes is None:
        return ""
    return text_bytes.decode("utf-8", errors="replace")


def _extract_identifier(node: Node, source_bytes: bytes) -> str:
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source_bytes)
    return ""


def _find_field(node: Node, field: str) -> Node | None:
    return node.child_by_field_name(field)

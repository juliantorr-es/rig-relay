from __future__ import annotations

from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython

from rig_relay.digestion.structural_indexer._utils import (
    _extract_identifier,
    _node_text,
    compute_sha256,
    sanitize_signature,
)
from rig_relay.digestion.structural_indexer.models import SymbolEntry, SymbolKind


class PythonStructuralParser:
    def __init__(self) -> None:
        self._parser = Parser(Language(tspython.language()))

    def check_main_block(self, source_bytes: bytes) -> bool:
        tree = self._parser.parse(source_bytes)
        return _detect_main_block(tree.root_node, source_bytes)

    def parse_file(
        self, source_bytes: bytes, rel_path: str, parent_module: str | None = None
    ) -> tuple[list[SymbolEntry], list[str]]:
        tree = self._parser.parse(source_bytes)
        root = tree.root_node

        exported_names = self._extract_all_exports(root, source_bytes)
        symbols: list[SymbolEntry] = []
        imports: list[str] = []
        self._walk_block(
            root,
            source_bytes,
            rel_path,
            parent_module,
            exported_names,
            symbols,
            imports,
        )
        return symbols, imports

    def _walk_block(
        self,
        node: Node,
        source_bytes: bytes,
        rel_path: str,
        parent_module: str | None,
        exported_names: set[str] | None,
        symbols: list[SymbolEntry],
        imports: list[str],
        parent_class_name: str | None = None,
    ) -> None:
        for child in node.children:
            match child.type:
                case "class_definition":
                    self._handle_class(
                        child,
                        source_bytes,
                        rel_path,
                        parent_module,
                        exported_names,
                        symbols,
                        imports,
                    )
                case "function_definition":
                    self._handle_function(
                        child,
                        source_bytes,
                        rel_path,
                        parent_module,
                        exported_names,
                        symbols,
                        parent_class_name,
                    )
                case "decorated_definition":
                    inner = self._unwrap_decorated(child)
                    if inner is None:
                        continue
                    if inner.type == "class_definition":
                        self._handle_class(
                            inner,
                            source_bytes,
                            rel_path,
                            parent_module,
                            exported_names,
                            symbols,
                            imports,
                        )
                    elif inner.type == "function_definition":
                        self._handle_function(
                            inner,
                            source_bytes,
                            rel_path,
                            parent_module,
                            exported_names,
                            symbols,
                            parent_class_name,
                        )
                case "import_statement" if parent_class_name is None:
                    imports.extend(self._extract_simple_imports(child, source_bytes))
                case "import_from_statement" if parent_class_name is None:
                    imports.extend(self._extract_from_imports(child, source_bytes))
                case "expression_statement" if parent_class_name is None:
                    self._handle_top_level_assignment(
                        child,
                        source_bytes,
                        rel_path,
                        parent_module,
                        exported_names,
                        symbols,
                    )
                case "type_alias_statement" if parent_class_name is None:
                    self._handle_type_alias(
                        child,
                        source_bytes,
                        rel_path,
                        parent_module,
                        exported_names,
                        symbols,
                    )

    def _handle_class(
        self,
        node: Node,
        source_bytes: bytes,
        rel_path: str,
        parent_module: str | None,
        exported_names: set[str] | None,
        symbols: list[SymbolEntry],
        imports: list[str],
    ) -> None:
        name = _extract_identifier(node, source_bytes)
        if not name:
            return
        is_exported = _is_exported_name(name, exported_names)
        line_number = node.start_point[0] + 1
        signature = self._extract_definition_signature(node, source_bytes)
        doc_text = self._extract_docstring(node, source_bytes)
        doc_digest = compute_sha256(doc_text) if doc_text else None

        symbols.append(
            SymbolEntry(
                name=name,
                kind=SymbolKind.CLASS,
                location=rel_path,
                line_number=line_number,
                signature=signature,
                docstring_digest=doc_digest,
                is_exported=is_exported,
                parent_module=parent_module,
            )
        )

        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_block(
                body,
                source_bytes,
                rel_path,
                parent_module,
                exported_names,
                symbols,
                imports,
                parent_class_name=name,
            )

    def _handle_function(
        self,
        node: Node,
        source_bytes: bytes,
        rel_path: str,
        parent_module: str | None,
        exported_names: set[str] | None,
        symbols: list[SymbolEntry],
        parent_class_name: str | None,
    ) -> None:
        name = _extract_identifier(node, source_bytes)
        if not name:
            return
        is_method = parent_class_name is not None
        is_exported = _is_exported_name(name, exported_names)
        line_number = node.start_point[0] + 1
        signature = self._extract_definition_signature(node, source_bytes)
        doc_text = self._extract_docstring(node, source_bytes)
        doc_digest = compute_sha256(doc_text) if doc_text else None
        kind = SymbolKind.METHOD if is_method else SymbolKind.FUNCTION

        symbols.append(
            SymbolEntry(
                name=name,
                kind=kind,
                location=rel_path,
                line_number=line_number,
                signature=signature,
                docstring_digest=doc_digest,
                is_exported=is_exported,
                parent_module=parent_module,
            )
        )

    def _handle_top_level_assignment(
        self,
        node: Node,
        source_bytes: bytes,
        rel_path: str,
        parent_module: str | None,
        exported_names: set[str] | None,
        symbols: list[SymbolEntry],
    ) -> None:
        assignment = next((c for c in node.children if c.type == "assignment"), None)
        if assignment is None:
            return
        if not assignment.children:
            return
        if assignment.children[0].type == "identifier":
            name = _node_text(assignment.children[0], source_bytes)
        else:
            return
        if name == "__all__":
            return

        is_const = name.isupper() or (name[0] == "_" and name[1:].isupper())
        line_number = node.start_point[0] + 1
        is_exported = _is_exported_name(name, exported_names)

        symbols.append(
            SymbolEntry(
                name=name,
                kind=SymbolKind.CONSTANT if is_const else SymbolKind.VARIABLE,
                location=rel_path,
                line_number=line_number,
                signature=None,
                docstring_digest=None,
                is_exported=is_exported,
                parent_module=parent_module,
            )
        )

    def _handle_type_alias(
        self,
        node: Node,
        source_bytes: bytes,
        rel_path: str,
        parent_module: str | None,
        exported_names: set[str] | None,
        symbols: list[SymbolEntry],
    ) -> None:
        name = _extract_identifier(node, source_bytes)
        if not name:
            return
        line_number = node.start_point[0] + 1
        is_exported = _is_exported_name(name, exported_names)
        signature = sanitize_signature(_node_text(node, source_bytes))

        symbols.append(
            SymbolEntry(
                name=name,
                kind=SymbolKind.TYPE_ALIAS,
                location=rel_path,
                line_number=line_number,
                signature=signature,
                docstring_digest=None,
                is_exported=is_exported,
                parent_module=parent_module,
            )
        )

    def _extract_definition_signature(self, node: Node, source_bytes: bytes) -> str:
        colon_idx = next(
            (i for i, c in enumerate(node.children) if c.type == ":"), None
        )
        if colon_idx is None:
            return sanitize_signature(_node_text(node, source_bytes))
        end_byte = node.children[colon_idx].end_byte
        sig_bytes = source_bytes[node.start_byte : end_byte]
        return sanitize_signature(sig_bytes.decode("utf-8", errors="replace"))

    def _extract_simple_imports(self, node: Node, source_bytes: bytes) -> list[str]:
        imports: list[str] = []
        for child in node.children:
            if child.type == "dotted_name":
                imports.append(_node_text(child, source_bytes))
        return imports

    def _extract_from_imports(self, node: Node, source_bytes: bytes) -> list[str]:
        imports: list[str] = []
        source_module = ""
        for child in node.children:
            if child.type == "dotted_name":
                text = _node_text(child, source_bytes)
                if not source_module:
                    source_module = text
                else:
                    imports.append(f"{source_module}.{text}")
        return imports

    def _extract_all_exports(
        self, root_node: Node, source_bytes: bytes
    ) -> set[str] | None:
        for child in root_node.children:
            if child.type != "expression_statement":
                continue
            for sub in child.children:
                if sub.type != "assignment":
                    continue
                identifiers = [c for c in sub.children if c.type == "identifier"]
                if not identifiers:
                    continue
                if _node_text(identifiers[0], source_bytes) == "__all__":
                    return self._parse_dunder_all_list(sub, source_bytes)
        return None

    def _parse_dunder_all_list(
        self, assignment_node: Node, source_bytes: bytes
    ) -> set[str]:
        names: set[str] = set()
        for child in assignment_node.children:
            if child.type in {"list", "tuple"}:
                for item in child.children:
                    if item.type == "string":
                        text = _node_text(item, source_bytes).strip("\"'")
                        names.add(text)
        return names

    def _unwrap_decorated(self, node: Node) -> Node | None:
        for child in node.children:
            if child.type in {"class_definition", "function_definition"}:
                return child
        return None

    def _extract_docstring(self, node: Node, source_bytes: bytes) -> str | None:
        body = node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        return _node_text(sub, source_bytes).strip("\"'")
            break
        return None


def _detect_main_block(root_node: Node, source_bytes: bytes) -> bool:
    for child in root_node.children:
        if child.type != "if_statement":
            continue
        text = _node_text(child, source_bytes)
        if "__name__" in text and "__main__" in text:
            return True
    return False


def _is_exported_name(name: str, exported_names: set[str] | None) -> bool:
    if exported_names is not None:
        return name in exported_names
    return not name.startswith("_")

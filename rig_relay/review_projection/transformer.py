from __future__ import annotations

import ast
import io
import tokenize
from typing import Any


class OpaqueIdentifierGenerator:
    def __init__(self):
        self.counters = {"C": 1, "F": 1, "M": 1, "V": 1, "S": 1}
        self.mapping: dict[str, str] = {}

    def get_or_create(self, prefix: str, original: str) -> str:
        if original in self.mapping:
            return self.mapping[original]
        idx = self.counters.get(prefix, 1)
        self.counters[prefix] = idx + 1
        new_id = f"{prefix}_{idx:04d}"
        self.mapping[original] = new_id
        return new_id


class _AstTransformer(ast.NodeTransformer):
    def __init__(self, id_gen: OpaqueIdentifierGenerator):
        self.id_gen = id_gen
        self.reserved_names = {
            "__init__",
            "self",
            "cls",
            "args",
            "kwargs",
            "True",
            "False",
            "None",
            "Exception",
            "ValueError",
            "TypeError",
            "dict",
            "list",
            "str",
            "int",
            "bool",
            "print",
            "super",
            "len",
            "isinstance",
            "getattr",
            "setattr",
            "hasattr",
            "staticmethod",
            "classmethod",
            "property",
        }

    def _should_transform(self, name: str) -> bool:
        if name.startswith("__") and name.endswith("__"):
            return False
        if name in self.reserved_names:
            return False
        return True

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        if self._should_transform(node.name):
            node.name = self.id_gen.get_or_create("C", node.name)
        self.generic_visit(node)
        # Remove docstring
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        if self._should_transform(node.name):
            prefix = "M" if "self" in [a.arg for a in node.args.args] else "F"
            if node.name.startswith("test_"):
                # Semantic leakage in test names
                node.name = self.id_gen.get_or_create("T", node.name)
            else:
                node.name = self.id_gen.get_or_create(prefix, node.name)
        self.generic_visit(node)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        if self._should_transform(node.name):
            prefix = "M" if "self" in [a.arg for a in node.args.args] else "F"
            node.name = self.id_gen.get_or_create(prefix, node.name)
        self.generic_visit(node)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return node

    def visit_Name(self, node: ast.Name) -> Any:
        if isinstance(node.ctx, (ast.Store, ast.Load)):
            if self._should_transform(node.id):
                node.id = self.id_gen.get_or_create("V", node.id)
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> Any:
        if self._should_transform(node.arg):
            node.arg = self.id_gen.get_or_create("V", node.arg)
        self.generic_visit(node)
        return node

    def visit_Constant(self, node: ast.Constant) -> Any:
        # Transform string literals to prevent semantic leakage
        if isinstance(node.value, str):
            node.value = self.id_gen.get_or_create("S", node.value)
        return node

    def visit_Module(self, node: ast.Module) -> Any:
        self.generic_visit(node)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return node


class PythonTransformer:
    def __init__(self):
        self.id_gen = OpaqueIdentifierGenerator()

    def _strip_comments(self, source: str) -> str:
        io_obj = io.StringIO(source)
        out = []
        try:
            for tok in tokenize.generate_tokens(io_obj.readline):
                if tok.type == tokenize.COMMENT:
                    continue
                out.append((tok.type, tok.string))
            return tokenize.untokenize(out)
        except tokenize.TokenError:
            # If tokenization fails (e.g. invalid syntax), return original for AST parser to fail properly
            return source

    def transform(self, source: str) -> tuple[str, dict[str, str]]:
        # 1. Strip comments using tokenize
        source_no_comments = self._strip_comments(source)

        # 2. Parse AST
        try:
            tree = ast.parse(source_no_comments)
        except SyntaxError:
            raise ValueError("Failed to parse Python source")

        # 3. Transform AST (removes docstrings, renames symbols, sanitizes strings)
        transformer = _AstTransformer(self.id_gen)
        transformed_tree = transformer.visit(tree)
        ast.fix_missing_locations(transformed_tree)

        # 4. Unparse
        transformed_source = ast.unparse(transformed_tree)

        return transformed_source, self.id_gen.mapping

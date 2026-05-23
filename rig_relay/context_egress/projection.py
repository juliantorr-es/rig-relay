from __future__ import annotations

import ast
import builtins
import hashlib


def get_opaque_id(original: str) -> str:
    h = hashlib.sha256(original.encode()).hexdigest()[:8]
    return f"OPAQUE_{h}"


class StructuralProjector(ast.NodeTransformer):
    def __init__(self) -> None:
        super().__init__()
        self.crosswalk = {}
        self.builtins_set = set(dir(builtins))
        self.refused = False

    def _obfuscate(self, name: str) -> str:
        if name in self.builtins_set or name.startswith("__"):
            return name
        opaque = get_opaque_id(name)
        self.crosswalk[name] = opaque
        return opaque

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = self._obfuscate(node.id)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = self._obfuscate(node.name)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = self._obfuscate(node.name)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = self._obfuscate(node.name)
        if ast.get_docstring(node):
            node.body = node.body[1:]
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._obfuscate(node.arg)
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node.attr = self._obfuscate(node.attr)
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, (str, bytes)):
            node.value = "<REDACTED>"
        return self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        # f-strings become a redacted string
        return ast.Constant(value="<REDACTED>")


def project_python_source(source: str) -> tuple[str, dict[str, str], bool]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "", {}, True

    # Strip module docstring
    if ast.get_docstring(tree):
        tree.body = tree.body[1:]

    projector = StructuralProjector()
    projector.visit(tree)

    if projector.refused:
        return "", {}, True

    minimized = ast.unparse(tree)
    return minimized, projector.crosswalk, False

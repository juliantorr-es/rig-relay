from __future__ import annotations

import ast
from dataclasses import dataclass, field

_DANGEROUS_CALLS: frozenset[str] = frozenset({"eval", "exec", "compile", "__import__"})

_DANGEROUS_MODULE_ROOTS: frozenset[str] = frozenset({
    "os",
    "subprocess",
    "socket",
    "shutil",
    "sys",
    "ctypes",
    "signal",
    "multiprocessing",
    "threading",
    "pdb",
    "code",
    "codeop",
    "pty",
    "fcntl",
    "posix",
    "nt",
})

_DANGEROUS_BUILTINS: frozenset[str] = frozenset({"open", "input", "breakpoint"})

_SANCTIONED_IMPORTS: frozenset[str] = frozenset({
    "from __future__ import annotations",
    "from pydantic import BaseModel",
    "from pydantic import BaseModel, Field",
})

_UNRESTRICTED = "unrestricted"


@dataclass
class ASTSafetyResult:
    safe: bool
    violations: list[str] = field(default_factory=list)


def check_ast_safety(source_code: str) -> ASTSafetyResult:
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return ASTSafetyResult(
            safe=False, violations=[f"Syntax error in candidate code: {e}"]
        )

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _check_call(node, violations)

        if isinstance(node, ast.Import):
            _check_import(node, violations)

        if isinstance(node, ast.ImportFrom):
            _check_import_from(node, violations)

    return ASTSafetyResult(safe=len(violations) == 0, violations=violations)


def _check_call(node: ast.Call, violations: list[str]) -> None:
    match node.func:
        case ast.Name(id=name) if name in _DANGEROUS_CALLS:
            violations.append(f"Dangerous call: {name}() at line {node.lineno}")
        case ast.Name(id=name) if name in _DANGEROUS_BUILTINS:
            violations.append(f"Dangerous builtin call: {name}() at line {node.lineno}")
        case ast.Attribute(value=ast.Name(id=mod), attr=attr) if (
            mod in _DANGEROUS_MODULE_ROOTS
        ):
            violations.append(
                f"Dangerous call on {mod}: {mod}.{attr}() at line {node.lineno}"
            )
        case ast.Attribute(
            value=ast.Call(func=ast.Attribute(value=ast.Call(), attr=_)), attr=attr
        ):
            _check_chained_call(node.func, violations, node.lineno)
        case ast.Attribute(value=ast.Call(func=ast.Name(id=name)), attr=attr) if (
            name in _DANGEROUS_BUILTINS
        ):
            violations.append(
                f"Chained call from dangerous builtin: {name}().{attr}() at line {node.lineno}"
            )
        case ast.Attribute(value=ast.Call(func=ast.Attribute()), attr=_):
            _check_chained_call(node.func, violations, node.lineno)
        case ast.Call():
            pass


def _check_chained_call(
    node: ast.Call | ast.Attribute, violations: list[str], lineno: int
) -> None:
    """Walk a chain of attribute accesses and calls to find dangerous patterns."""
    parts: list[str] = []
    current: ast.expr = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        if current.id in _DANGEROUS_BUILTINS:
            violations.append(
                f"Dangerous chained call: {_UNRESTRICTED}().{' .'.join(reversed(parts))}() at line {lineno}"
            )
    elif isinstance(current, ast.Call):
        if (
            isinstance(current.func, ast.Name)
            and current.func.id in _DANGEROUS_BUILTINS
        ):
            violations.append(f"Dangerous chained call from builtin at line {lineno}")


def _check_import(node: ast.Import, violations: list[str]) -> None:
    for alias in node.names:
        root = alias.name.split(".")[0]
        if root in _DANGEROUS_MODULE_ROOTS:
            violations.append(
                f"Dangerous import: import {alias.name} at line {node.lineno}"
            )


def _check_import_from(node: ast.ImportFrom, violations: list[str]) -> None:
    if node.module is None:
        return
    root = node.module.split(".")[0]
    if root in _DANGEROUS_MODULE_ROOTS:
        violations.append(
            f"Dangerous import: from {node.module} import ... at line {node.lineno}"
        )

    import_stmt = ast.unparse(node)
    if import_stmt not in _SANCTIONED_IMPORTS and root != _DANGEROUS_MODULE_ROOTS:
        pass

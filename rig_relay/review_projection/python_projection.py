from __future__ import annotations

import ast
from symtable import SymbolTable, symtable


class BindingKind:
    LOCAL = "local"
    PARAMETER = "parameter"
    IMPORTED = "imported"
    GLOBAL = "global"
    NONLOCAL = "nonlocal"
    FREE = "free"
    NAMESPACE = "namespace"
    UNKNOWN = "unknown"


# Scope types from symtable — used to skip class scopes in FREE resolution
# and to refuse unsupported annotation/type-parameter scopes.
_SCOPE_TYPE_FUNCTION = "function"
_SCOPE_TYPE_CLASS = "class"
_SCOPE_TYPE_MODULE = "module"


_SUPPORTED_SCOPE_TYPES: frozenset[str] = frozenset({
    _SCOPE_TYPE_MODULE,
    _SCOPE_TYPE_FUNCTION,
    _SCOPE_TYPE_CLASS,
})


_SYMTABLE_TYPE_MAP: dict[str, str] = {
    "module": _SCOPE_TYPE_MODULE,
    "function": _SCOPE_TYPE_FUNCTION,
    "class": _SCOPE_TYPE_CLASS,
}


class ScopeNode:
    """A node in the lexical scope tree, built from symtable."""

    __slots__ = ("name", "scope_type", "lineno", "symbols", "parent", "children")

    def __init__(
        self, name: str, scope_type: str, lineno: int, parent: ScopeNode | None = None
    ) -> None:
        self.name = name
        self.scope_type = scope_type
        self.lineno = lineno
        self.symbols: dict[str, str] = {}  # name -> BindingKind
        self.parent = parent
        self.children: list[ScopeNode] = []

    @property
    def owner_identity(self) -> str:
        """Stable identity for the owner scope: type:qualified_path:lineno."""
        return f"{self.scope_type}:{self.name}:{self.lineno}"

    def is_function_scope(self) -> bool:
        return self.scope_type == _SCOPE_TYPE_FUNCTION

    def is_class_scope(self) -> bool:
        return self.scope_type == _SCOPE_TYPE_CLASS

    def is_module_scope(self) -> bool:
        return self.scope_type == _SCOPE_TYPE_MODULE


class ScopeIdentity:
    """Compound identity for a symbol in lexical context.

    scope_name now stores the OWNER scope identity (not the occurrence scope),
    so a FREE reference and its LOCAL binding in an outer function share the
    same pseudonym.
    """

    __slots__ = (
        "language",
        "file_path",
        "scope_name",
        "binding_kind",
        "original_spelling",
    )

    def __init__(
        self,
        language: str,
        file_path: str,
        scope_name: str,
        binding_kind: str,
        original_spelling: str,
    ) -> None:
        self.language = language
        self.file_path = file_path
        self.scope_name = scope_name
        self.binding_kind = binding_kind
        self.original_spelling = original_spelling

    def __hash__(self) -> int:
        return hash((
            self.language,
            self.file_path,
            self.scope_name,
            self.binding_kind,
            self.original_spelling,
        ))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScopeIdentity):
            return NotImplemented
        return (
            self.language == other.language
            and self.file_path == other.file_path
            and self.scope_name == other.scope_name
            and self.binding_kind == other.binding_kind
            and self.original_spelling == other.original_spelling
        )

    def __repr__(self) -> str:
        return (
            f"ScopeIdentity(lang={self.language}, file={self.file_path!r}, "
            f"scope={self.scope_name!r}, kind={self.binding_kind}, "
            f"name={self.original_spelling!r})"
        )


# ---------------------------------------------------------------------------
# Reserved names that must never be pseudonymized
# ---------------------------------------------------------------------------
_RESERVED_NAMES: frozenset[str] = frozenset({
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
    "KeyError",
    "OSError",
    "RuntimeError",
    "NotImplementedError",
    "StopIteration",
    "dict",
    "list",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "set",
    "tuple",
    "frozenset",
    "object",
    "type",
    "super",
    "len",
    "isinstance",
    "getattr",
    "setattr",
    "hasattr",
    "delattr",
    "staticmethod",
    "classmethod",
    "property",
    "print",
    "range",
    "enumerate",
    "zip",
    "map",
    "filter",
    "iter",
    "any",
    "all",
    "sorted",
    "reversed",
    "min",
    "max",
    "sum",
    "open",
    "abs",
    "round",
    "ord",
    "chr",
    "repr",
    "hash",
    "id",
    "__name__",
    "__file__",
    "__doc__",
    "__all__",
    "__future__",
})


# Only pseudonymize these binding kinds — but only when the owner is
# a function scope (class-body LOCALS are retained in v1).
_PSEUDONYMIZE_KINDS: frozenset[str] = frozenset({
    BindingKind.LOCAL,
    BindingKind.PARAMETER,
    BindingKind.FREE,
})


class SymbolEntry:
    """A single symbol occurrence with source span."""

    __slots__ = ("identity", "start_byte", "end_byte", "line")

    def __init__(
        self, identity: ScopeIdentity, start_byte: int, end_byte: int, line: int
    ) -> None:
        self.identity = identity
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.line = line


class ReplacementLedger:
    """Maps compound ScopeIdentity objects to deterministic pseudonyms.

    The same identity always gets the same pseudonym, ensuring the same symbol
    in baseline and dirty versions receives the same replacement.
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._mapping: dict[ScopeIdentity, str] = {}
        self._reverse: dict[str, ScopeIdentity] = {}
        self._counter = 1

    def register(self, identity: ScopeIdentity) -> str:
        if identity in self._mapping:
            return self._mapping[identity]
        pseudonym = f"P_{self._counter:04d}"
        self._counter += 1
        self._mapping[identity] = pseudonym
        self._reverse[pseudonym] = identity
        return pseudonym

    def get(self, identity: ScopeIdentity) -> str | None:
        return self._mapping.get(identity)

    def __contains__(self, identity: ScopeIdentity) -> bool:
        return identity in self._mapping

    @property
    def mapping(self) -> dict[str, str]:
        return {
            ident.original_spelling: pseudo for ident, pseudo in self._mapping.items()
        }

    def __len__(self) -> int:
        return len(self._mapping)


# ---------------------------------------------------------------------------
# Scope tree builder: walks symtable → ScopeNode tree with parent links
# ---------------------------------------------------------------------------


def _build_scope_tree(table: SymbolTable) -> ScopeNode:
    """Build a tree of ScopeNode from symtable, with parent links."""
    return _build_node(table, None, "")


def _build_node(
    table: SymbolTable, parent: ScopeNode | None, parent_path: str
) -> ScopeNode:
    table_name = table.get_name()
    qualified = f"{parent_path}.{table_name}" if parent_path else table_name
    if not qualified:
        qualified = "top"

    scope_type = _SYMTABLE_TYPE_MAP.get(table.get_type(), "unsupported")
    lineno = table.get_lineno()
    node = ScopeNode(
        name=qualified, scope_type=scope_type, lineno=lineno, parent=parent
    )

    for sym in table.get_symbols():
        name = sym.get_name()
        if sym.is_parameter():
            kind = BindingKind.PARAMETER
        elif sym.is_imported():
            kind = BindingKind.IMPORTED
        elif sym.is_global():
            kind = BindingKind.GLOBAL
        elif sym.is_nonlocal():
            kind = BindingKind.NONLOCAL
        elif sym.is_free():
            kind = BindingKind.FREE
        elif sym.is_namespace():
            kind = BindingKind.NAMESPACE
        elif sym.is_local():
            kind = BindingKind.LOCAL
        else:
            kind = BindingKind.UNKNOWN
        node.symbols[name] = kind

    for child_table in table.get_children():
        child_node = _build_node(child_table, node, qualified)
        node.children.append(child_node)

    return node


def _find_scope_node(root: ScopeNode, dotted_path: str) -> ScopeNode | None:
    """Find a scope node by its dotted path."""
    if root.name == dotted_path:
        return root
    for child in root.children:
        found = _find_scope_node(child, dotted_path)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# Binding-owner resolver
# ---------------------------------------------------------------------------


def _resolve_owner(current_scope: ScopeNode, name: str) -> tuple[str, ScopeNode | None]:
    """Resolve the binding kind and owner scope for a name.

    Returns (binding_kind, owner_scope_or_None).

    - LOCAL/PARAMETER in a function scope → owner = current scope
    - LOCAL in a class or module scope → retained (owner = None)
    - FREE → walk up parent chain, SKIPPING class scopes, find function binding
    - NONLOCAL → walk up, skip class scopes, find first function binding
    - GLOBAL, IMPORTED, NAMESPACE → retained (owner = None)
    - In unsupported scope → retained (owner = None)
    """
    kind = current_scope.symbols.get(name, BindingKind.UNKNOWN)

    # Unsupported scope types → retain all identifiers
    if current_scope.scope_type not in _SUPPORTED_SCOPE_TYPES:
        return kind, None

    if kind == BindingKind.IMPORTED:
        return kind, None

    if kind == BindingKind.GLOBAL:
        return kind, None

    if kind == BindingKind.NAMESPACE:
        return kind, None

    if kind == BindingKind.UNKNOWN:
        return kind, None

    if kind in (BindingKind.LOCAL, BindingKind.PARAMETER):
        # Pseudonymize only in function scopes; retain in class/module scopes
        if current_scope.is_function_scope():
            return kind, current_scope
        return kind, None

    if kind == BindingKind.FREE:
        owner = _find_free_owner(current_scope.parent, name)
        if owner is not None:
            source_kind = owner.symbols.get(name, BindingKind.LOCAL)
            return source_kind, owner
        return kind, None  # unresolved free variable → retain

    if kind == BindingKind.NONLOCAL:
        owner = _find_nonlocal_owner(current_scope.parent, name)
        if owner is not None:
            source_kind = owner.symbols.get(name, BindingKind.LOCAL)
            return source_kind, owner
        return kind, None  # unresolved nonlocal → retain

    return kind, None


def _find_free_owner(start: ScopeNode | None, name: str) -> ScopeNode | None:
    """Walk parent chain to find the function scope that binds `name`.

    Skips class scopes — class-body names are not closure parents.
    """
    cursor = start
    while cursor is not None:
        if cursor.is_function_scope():
            if name in cursor.symbols:
                kind = cursor.symbols[name]
                if kind in (BindingKind.LOCAL, BindingKind.PARAMETER):
                    return cursor
        elif cursor.is_module_scope():
            if name in cursor.symbols:
                return cursor
        cursor = cursor.parent
    return None


def _find_nonlocal_owner(start: ScopeNode | None, name: str) -> ScopeNode | None:
    """Walk parent chain for NONLOCAL — skip class scopes, find function binding."""
    cursor = start
    while cursor is not None:
        if cursor.is_function_scope():
            if name in cursor.symbols:
                kind = cursor.symbols[name]
                if kind in (BindingKind.LOCAL, BindingKind.PARAMETER):
                    return cursor
        elif cursor.is_module_scope():
            # nonlocal cannot bind to module scope; stop here
            break
        cursor = cursor.parent
    return None


# ---------------------------------------------------------------------------
# Symbol collector: walks AST + scope tree to build ScopeIdentity entries
# ---------------------------------------------------------------------------


def _tree_has_unsupported_scopes(root: ScopeNode) -> bool:
    """Check whether any scope in the tree is an unsupported type
    (annotation, type_parameters, lambda, comprehension, etc.) AND
    contains symbols that would be affected by pseudonymization.
    """
    if root.scope_type not in _SUPPORTED_SCOPE_TYPES:
        # Only count if there are actually symbols that matter
        if root.symbols:
            return True
    for child in root.children:
        if _tree_has_unsupported_scopes(child):
            return True
    return False


_MIN_DYNAMIC_ACCESS_NAME_LENGTH: int = 3

_DYNAMIC_ACCESS_PATTERNS: list[str] = [
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bhasattr\s*\(",
    r"\bdelattr\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bglobals\s*\(\s*\)",
    r"\blocals\s*\(\s*\)",
]


def _detect_dynamic_access_risk(
    source: str, pseudonymized_names: set[str]
) -> list[str]:
    """Return names of pseudonymized identifiers that appear in dynamic-access
    patterns. These cannot be safely renamed because string-based access
    (getattr, setattr, dispatch dicts, etc.) may still reference the original
    name, producing a misleading projected artifact.
    """
    import re

    risky: list[str] = []
    for name in sorted(pseudonymized_names, key=len, reverse=True):
        if len(name) < _MIN_DYNAMIC_ACCESS_NAME_LENGTH:
            continue
        for pattern in _DYNAMIC_ACCESS_PATTERNS:
            # Search for pattern followed by the name within reasonable distance
            combined = pattern + r".{0,80}?" + re.escape(name)
            if re.search(combined, source):
                risky.append(name)
                break
    return risky


def _collect_symbols(
    source: str, file_path: str, source_bytes: bytes, line_offsets: list[int]
) -> tuple[list[SymbolEntry], bool]:
    """Collect all symbols with binding classification and byte spans."""
    entries: list[SymbolEntry] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return entries, False

    try:
        table = symtable(source, "<projection>", "exec")
    except SyntaxError:
        return entries, False

    scope_root = _build_scope_tree(table)

    class _NameCollector(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope_nodes: list[ScopeNode] = [scope_root]

        def _current_scope(self) -> ScopeNode:
            return self._scope_nodes[-1]

        def _enter_scope(self, name: str) -> ScopeNode | None:
            """Find and enter a child scope by name. Returns the node or None."""
            current = self._current_scope()
            # Build the expected dotted path for the child
            expected = f"{current.name}.{name}"
            for child in current.children:
                if child.name == expected:
                    self._scope_nodes.append(child)
                    return child
            # Scope not found in tree — push a placeholder
            placeholder = ScopeNode(
                name=expected, scope_type="unsupported", lineno=0, parent=current
            )
            self._scope_nodes.append(placeholder)
            return placeholder

        def _byte_offset(self, lineno: int, col_offset: int) -> int:
            if lineno < 1 or lineno > len(line_offsets):
                return 0
            return line_offsets[lineno - 1] + col_offset

        def _is_private_name(self, name: str) -> bool:
            return name.startswith("_") and not name.startswith("__")

        def _should_entry_be_pseudonymized(
            self, kind: str, owner: ScopeNode | None
        ) -> bool:
            return kind in _PSEUDONYMIZE_KINDS and owner is not None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._record_def(
                node.name, node.lineno, node.col_offset + 4, _SCOPE_TYPE_FUNCTION
            )
            self._enter_scope(node.name)
            self.generic_visit(node)
            self._scope_nodes.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._record_def(
                node.name, node.lineno, node.col_offset + 10, _SCOPE_TYPE_FUNCTION
            )
            self._enter_scope(node.name)
            self.generic_visit(node)
            self._scope_nodes.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._enter_scope(node.name)
            self.generic_visit(node)
            self._scope_nodes.pop()

        def _record_def(
            self, name: str, lineno: int, col_offset: int, _scope_type: str
        ) -> None:
            if name in _RESERVED_NAMES:
                return
            if name.startswith("__") and name.endswith("__"):
                return
            kind = (
                BindingKind.LOCAL
                if self._is_private_name(name)
                else BindingKind.UNKNOWN
            )
            scope = self._current_scope()
            start = self._byte_offset(lineno, col_offset)
            end = start + len(name.encode("utf-8"))
            entries.append(
                SymbolEntry(
                    identity=ScopeIdentity(
                        language="python",
                        file_path=file_path,
                        scope_name=scope.owner_identity
                        if kind in _PSEUDONYMIZE_KINDS and scope.is_function_scope()
                        else "retained",
                        binding_kind=kind,
                        original_spelling=name,
                    ),
                    start_byte=start,
                    end_byte=end,
                    line=lineno,
                )
            )

        def visit_arg(self, node: ast.arg) -> None:
            name = node.arg
            if name in _RESERVED_NAMES:
                self.generic_visit(node)
                return
            if name.startswith("__") and name.endswith("__"):
                self.generic_visit(node)
                return
            scope = self._current_scope()
            owner_ident = (
                scope.owner_identity if scope.is_function_scope() else "retained"
            )
            start = self._byte_offset(node.lineno, node.col_offset)
            end = start + len(name.encode("utf-8"))
            entries.append(
                SymbolEntry(
                    identity=ScopeIdentity(
                        language="python",
                        file_path=file_path,
                        scope_name=owner_ident,
                        binding_kind=BindingKind.PARAMETER,
                        original_spelling=name,
                    ),
                    start_byte=start,
                    end_byte=end,
                    line=node.lineno,
                )
            )
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            name = node.id
            if name in _RESERVED_NAMES:
                self.generic_visit(node)
                return
            if name.startswith("__") and name.endswith("__"):
                self.generic_visit(node)
                return

            current_scope = self._current_scope()
            kind, owner = _resolve_owner(current_scope, name)

            if owner is not None and self._should_entry_be_pseudonymized(kind, owner):
                scope_ident = owner.owner_identity
            else:
                scope_ident = "retained"

            start = self._byte_offset(node.lineno, node.col_offset)
            end = start + len(name.encode("utf-8"))

            entries.append(
                SymbolEntry(
                    identity=ScopeIdentity(
                        language="python",
                        file_path=file_path,
                        scope_name=scope_ident,
                        binding_kind=kind,
                        original_spelling=name,
                    ),
                    start_byte=start,
                    end_byte=end,
                    line=node.lineno,
                )
            )
            self.generic_visit(node)

    _NameCollector().visit(tree)

    # Detect any unsupported scope types in the tree
    has_unsupported = _tree_has_unsupported_scopes(scope_root)

    return entries, has_unsupported


# ---------------------------------------------------------------------------
# Source-preserving renderer: backward byte-span edits
# ---------------------------------------------------------------------------


class _Edit:
    __slots__ = ("start_byte", "end_byte", "replacement")

    def __init__(self, start_byte: int, end_byte: int, replacement: str) -> None:
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.replacement = replacement


def render_with_ledger(
    source: str,
    source_bytes: bytes,
    line_offsets: list[int],
    entries: list[SymbolEntry],
    ledger: ReplacementLedger,
) -> str:
    """Apply pseudonymization edits to original source, largest offset first."""
    edits: list[_Edit] = []
    for entry in entries:
        if entry.identity.binding_kind not in _PSEUDONYMIZE_KINDS:
            continue
        pseudo = ledger.get(entry.identity)
        if pseudo is None:
            continue
        edits.append(_Edit(entry.start_byte, entry.end_byte, pseudo))

    edits.sort(key=lambda e: e.start_byte, reverse=True)

    result_bytes = bytearray(source_bytes)
    for edit in edits:
        replacement_bytes = edit.replacement.encode("utf-8")
        result_bytes[edit.start_byte : edit.end_byte] = replacement_bytes

    return result_bytes.decode("utf-8")


def build_line_offsets(source_bytes: bytes) -> list[int]:
    """Build prefix-sum byte-offset array for each line start."""
    offsets = [0]
    pos = 0
    for byte in source_bytes:
        if byte == 0x0A:
            offsets.append(pos + 1)
        pos += 1
    if len(source_bytes) > 0 and source_bytes[-1] != 0x0A:
        offsets.append(len(source_bytes))
    return offsets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PythonPseudonymizer:
    """Source-preserving Python pseudonymizer using ast + symtable.

    Uses binding-owner resolution so that FREE variable references
    in closures receive the same pseudonym as their LOCAL binding
    in the outer function scope.
    """

    def __init__(self) -> None:
        self._ledger: ReplacementLedger | None = None
        self._has_unsupported_scope: bool = False

    def inventory(
        self, source: str, file_path: str
    ) -> tuple[list[SymbolEntry], bytes, list[int]]:
        source_bytes = source.encode("utf-8")
        line_offsets = build_line_offsets(source_bytes)
        entries, has_unsup = _collect_symbols(
            source, file_path, source_bytes, line_offsets
        )
        if has_unsup:
            self._has_unsupported_scope = True
        return entries, source_bytes, line_offsets

    def build_ledger(
        self,
        file_path: str,
        baseline_entries: list[SymbolEntry],
        dirty_entries: list[SymbolEntry],
    ) -> ReplacementLedger:
        ledger = ReplacementLedger(file_path)
        for entry in baseline_entries:
            if entry.identity.binding_kind in _PSEUDONYMIZE_KINDS:
                ledger.register(entry.identity)
        for entry in dirty_entries:
            if entry.identity.binding_kind in _PSEUDONYMIZE_KINDS:
                ledger.register(entry.identity)
        self._ledger = ledger
        return ledger

    def render(
        self,
        source: str,
        source_bytes: bytes,
        line_offsets: list[int],
        entries: list[SymbolEntry],
        ledger: ReplacementLedger,
    ) -> str:
        return render_with_ledger(source, source_bytes, line_offsets, entries, ledger)

    @property
    def ledger(self) -> ReplacementLedger | None:
        return self._ledger

    @property
    def has_unsupported_scope(self) -> bool:
        return self._has_unsupported_scope

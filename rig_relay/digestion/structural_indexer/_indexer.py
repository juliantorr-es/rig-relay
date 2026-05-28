from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.core.logger import logger
from rig_relay.digestion.structural_indexer._python_parser import PythonStructuralParser
from rig_relay.digestion.structural_indexer._utils import is_package_init
from rig_relay.digestion.structural_indexer.models import (
    ModuleEntry,
    StructuralIndex,
    StructuralIndexConfig,
    StructuralIndexKind,
)


class StructuralIndexer:
    def __init__(self, config: StructuralIndexConfig) -> None:
        self._config = config
        self._python_parser: PythonStructuralParser | None = None
        if StructuralIndexKind.PYTHON in config.parsers:
            self._python_parser = PythonStructuralParser()

    def build_index(self, repository_root: Path) -> StructuralIndex:
        root = repository_root.resolve()

        modules: list[ModuleEntry] = []
        parser_errors: dict[str, str] = {}
        python_files = self._discover_python_files(root)

        for file_path in python_files:
            module = self._index_file(file_path, root, parser_errors)
            if module is not None:
                modules.append(module)

        return self._assemble_index(root, modules, parser_errors)

    def refresh_index(
        self, existing: StructuralIndex, changed_files: list[Path]
    ) -> StructuralIndex:
        root = Path(existing.repository_root)
        changed_rel: set[str] = set()
        for cf in changed_files:
            try:
                changed_rel.add(str(cf.resolve().relative_to(root)))
            except ValueError:
                continue

        python_key = StructuralIndexKind.PYTHON.value
        existing_modules = existing.language_indices.get(python_key, [])

        unchanged: list[ModuleEntry] = []
        refreshed_modules: list[ModuleEntry] = []
        parser_errors: dict[str, str] = {}

        for mod in existing_modules:
            if mod.path not in changed_rel:
                unchanged.append(mod)
                continue

            file_path = root / mod.path
            if not file_path.is_file():
                continue
            module = self._index_file(file_path, root, parser_errors)
            if module is not None:
                refreshed_modules.append(module)

        all_modules = unchanged + refreshed_modules

        index = self._assemble_index(root, all_modules, parser_errors)
        return index

    def _discover_python_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        exclude = set(self._config.exclude_patterns)

        for py_file in root.rglob("*.py"):
            if self._is_excluded(py_file, root, exclude):
                continue
            files.append(py_file)
        return sorted(files)

    def _is_excluded(self, path: Path, root: Path, exclude_patterns: set[str]) -> bool:
        try:
            rel = path.relative_to(root)
        except ValueError:
            return True
        parts = rel.parts
        return any(part in exclude_patterns for part in parts)

    def _index_file(
        self, file_path: Path, root: Path, parser_errors: dict[str, str]
    ) -> ModuleEntry | None:
        rel_path = str(file_path.relative_to(root))

        try:
            file_size = file_path.stat().st_size
        except OSError as exc:
            parser_errors[rel_path] = f"stat_error: {exc}"
            return None

        if file_size > self._config.max_file_bytes:
            return None

        try:
            source_bytes = file_path.read_bytes()
        except OSError as exc:
            parser_errors[rel_path] = f"read_error: {exc}"
            return None

        if self._python_parser is None:
            return None

        try:
            symbols, imports = self._python_parser.parse_file(source_bytes, rel_path)
        except Exception as exc:
            logger.warning("Failed to parse Python file %s: %s", rel_path, exc)
            parser_errors[rel_path] = str(exc)
            return None

        pkg_init = is_package_init(file_path)
        main_block = self._python_parser.check_main_block(source_bytes)

        return ModuleEntry(
            path=rel_path,
            language=StructuralIndexKind.PYTHON,
            symbols=symbols,
            imports=imports,
            is_package_init=pkg_init,
            has_main_block=main_block,
        )

    def _assemble_index(
        self, root: Path, modules: list[ModuleEntry], parser_errors: dict[str, str]
    ) -> StructuralIndex:
        symbol_count = 0
        exported_count = 0
        for mod in modules:
            symbol_count += len(mod.symbols)
            exported_count += sum(1 for s in mod.symbols if s.is_exported)

        python_key = StructuralIndexKind.PYTHON.value
        language_indices: dict[str, list[ModuleEntry]] = {}
        if modules:
            language_indices[python_key] = modules

        index = StructuralIndex(
            repository_root=str(root),
            language_indices=language_indices,
            parser_versions={python_key: version("tree-sitter-python")},
            module_count=len(modules),
            symbol_count=symbol_count,
            exported_symbol_count=exported_count,
            parser_errors=parser_errors,
            index_digest="",
        )

        canonical = _to_canonical_json(index)
        index.index_digest = hashlib.sha256(canonical).hexdigest()
        return index


def _to_canonical_json(index: StructuralIndex) -> bytes:
    data = index.model_dump(exclude={"index_digest", "indexed_at"})
    return dump_canonical_json(data).encode("utf-8")

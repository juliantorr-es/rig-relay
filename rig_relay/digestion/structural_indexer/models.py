from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict, Field


class StructuralIndexKind(StrEnum):
    PYTHON = auto()
    TYPESCRIPT = auto()
    RUST = auto()
    UNSUPPORTED = auto()


class SymbolKind(StrEnum):
    FUNCTION = auto()
    CLASS = auto()
    METHOD = auto()
    VARIABLE = auto()
    MODULE = auto()
    INTERFACE = auto()
    TYPE_ALIAS = auto()
    ENUM = auto()
    CONSTANT = auto()
    EXPORT = auto()


class SymbolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Symbol name.")
    kind: SymbolKind = Field(description="Symbol kind classification.")
    location: str = Field(description="File path relative to repository root.")
    line_number: int = Field(
        description="1-indexed line number where the symbol is defined."
    )
    signature: str | None = Field(
        default=None, description="Symbol signature text, or None if unavailable."
    )
    docstring_digest: str | None = Field(
        default=None, description="SHA256 hex digest of the symbol docstring, or None."
    )
    is_exported: bool = Field(
        default=False,
        description="Whether the symbol is part of the module public API.",
    )
    parent_module: str | None = Field(
        default=None, description="Parent module path, or None for top-level symbols."
    )


class ModuleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Module file path relative to repository root.")
    language: StructuralIndexKind = Field(
        description="Programming language of this module."
    )
    symbols: list[SymbolEntry] = Field(
        default_factory=list, description="Symbols extracted from this module."
    )
    imports: list[str] = Field(
        default_factory=list, description="Module paths imported by this module."
    )
    is_package_init: bool = Field(
        default=False, description="True if this is an __init__.py file."
    )
    has_main_block: bool = Field(
        default=False,
        description="True if the module has an if __name__ == '__main__' guard.",
    )


class StructuralIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_root: str = Field(description="Absolute path to the repository root.")
    indexed_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp of index generation.",
    )
    language_indices: dict[str, list[ModuleEntry]] = Field(
        default_factory=dict, description="Module entries grouped by language kind."
    )
    index_digest: str = Field(
        default="",
        description="SHA256 hex digest of the canonical JSON representation.",
    )
    parser_versions: dict[str, str] = Field(
        default_factory=dict, description="Tree-sitter library version per language."
    )
    module_count: int = Field(default=0, description="Total number of modules indexed.")
    symbol_count: int = Field(default=0, description="Total number of symbols indexed.")
    exported_symbol_count: int = Field(
        default=0, description="Total number of exported symbols."
    )
    parser_errors: dict[str, str] = Field(
        default_factory=dict,
        description="Map of module path to error message for files that failed to parse.",
    )


class StructuralIndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parsers: list[StructuralIndexKind] = Field(
        default_factory=list, description="Language parsers to enable."
    )
    max_file_bytes: int = Field(
        default=1_048_576,
        description="Maximum file size in bytes to process (default 1 MiB).",
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "dist",
            "build",
            "target",
        ],
        description="Directory or file name patterns to exclude from file discovery.",
    )

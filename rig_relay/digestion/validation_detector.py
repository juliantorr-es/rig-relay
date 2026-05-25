"""Validation command candidate detection from manifests and conventions.

Slice 1A: Desktop Repository Preview Intake v1.
Detects commands from pyproject.toml, package.json, Cargo.toml, and
conventional config files. CI workflow parsing is deferred.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.digestion.models import DetectedCommand, DetectedEcosystem


def detect_validation_candidates(
    repo_root: Path, ecosystems: list[DetectedEcosystem]
) -> list[DetectedCommand]:
    """Detect validation command candidates from manifest files.

    Extracts test, lint, typecheck, format, and build commands from
    pyproject.toml, package.json, Cargo.toml, and conventional configs.

    Does NOT parse CI workflows in Phase 1A.
    """
    commands: list[DetectedCommand] = []

    for eco in ecosystems:
        lang = eco.language
        if lang == "python":
            commands.extend(_python_commands(repo_root, eco))
        elif lang in {"typescript", "javascript"}:
            commands.extend(_typescript_commands(repo_root))
        elif lang == "rust":
            commands.extend(_rust_commands(eco))

    return commands


def _python_commands(repo_root: Path, eco: DetectedEcosystem) -> list[DetectedCommand]:
    """Detect Python validation commands."""
    from rig_relay.digestion.models import (
        CommandKind,
        ConfidenceLevel,
        DetectedCommand,
        ProvenanceClass,
        SafetyClassification,
    )

    commands: list[DetectedCommand] = []

    pkg_manager = eco.package_manager or "uv"

    # Test command
    if eco.test_frameworks:
        test_fw = eco.test_frameworks[0]
        if test_fw == "pytest":
            commands.append(
                DetectedCommand(
                    command=f"{pkg_manager} run pytest",
                    kind=CommandKind.TEST,
                    safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
                    provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                    confidence=ConfidenceLevel.DEFINITE,
                )
            )

    # Lint command
    if eco.lint_tools:
        lint_tool = eco.lint_tools[0]
        if lint_tool == "ruff":
            commands.append(
                DetectedCommand(
                    command=f"{pkg_manager} run ruff check .",
                    kind=CommandKind.LINT,
                    safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
                    provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                    confidence=ConfidenceLevel.DEFINITE,
                )
            )

    # Type check command
    if eco.type_checkers:
        tc = eco.type_checkers[0]
        if tc == "pyright":
            commands.append(
                DetectedCommand(
                    command=f"{pkg_manager} run pyright",
                    kind=CommandKind.TYPECHECK,
                    safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
                    provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                    confidence=ConfidenceLevel.DEFINITE,
                )
            )
        elif tc == "mypy":
            commands.append(
                DetectedCommand(
                    command=f"{pkg_manager} run mypy .",
                    kind=CommandKind.TYPECHECK,
                    safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
                    provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                    confidence=ConfidenceLevel.DEFINITE,
                )
            )

    # Format command (mutating — needs confirmation)
    if eco.formatters:
        fmt = eco.formatters[0]
        if fmt == "ruff-format":
            commands.append(
                DetectedCommand(
                    command=f"{pkg_manager} run ruff format .",
                    kind=CommandKind.FORMAT,
                    safety_classification=SafetyClassification.WRITES_WORKSPACE,
                    provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                    confidence=ConfidenceLevel.DEFINITE,
                )
            )

    return commands


def _typescript_commands(repo_root: Path) -> list[DetectedCommand]:
    """Detect TypeScript/Node validation commands from package.json scripts."""
    from rig_relay.digestion.models import (
        CommandKind,
        ConfidenceLevel,
        DetectedCommand,
        ProvenanceClass,
        SafetyClassification,
    )

    commands: list[DetectedCommand] = []
    pkg_json = _read_json(repo_root / "package.json")
    if pkg_json is None:
        return commands

    scripts = pkg_json.get("scripts", {})
    if not isinstance(scripts, dict):
        return commands

    # Map script names to command kinds
    script_kind_map = {
        "test": CommandKind.TEST,
        "lint": CommandKind.LINT,
        "typecheck": CommandKind.TYPECHECK,
        "type-check": CommandKind.TYPECHECK,
        "format": CommandKind.FORMAT,
        "build": CommandKind.BUILD,
        "check": CommandKind.LINT,
        "ci": CommandKind.TEST,
    }

    for script_name, script_cmd in scripts.items():
        if not isinstance(script_cmd, str):
            continue
        kind = script_kind_map.get(script_name, CommandKind.UNKNOWN)
        if kind == CommandKind.UNKNOWN:
            continue  # Only surface known-kind scripts as candidates

        safety = SafetyClassification.READ_ONLY_VALIDATION
        if kind == CommandKind.FORMAT:
            safety = SafetyClassification.WRITES_WORKSPACE
        elif kind == CommandKind.BUILD:
            safety = SafetyClassification.NEEDS_CONFIRMATION

        commands.append(
            DetectedCommand(
                command=f"npm run {script_name}",
                kind=kind,
                safety_classification=safety,
                provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
                source_file="package.json",
                confidence=ConfidenceLevel.DEFINITE,
            )
        )

    return commands


def _rust_commands(eco: DetectedEcosystem) -> list[DetectedCommand]:
    """Detect Rust validation commands."""
    from rig_relay.digestion.models import (
        CommandKind,
        ConfidenceLevel,
        DetectedCommand,
        ProvenanceClass,
        SafetyClassification,
    )

    return [
        DetectedCommand(
            command="cargo test",
            kind=CommandKind.TEST,
            safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
            provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            confidence=ConfidenceLevel.DEFINITE,
        ),
        DetectedCommand(
            command="cargo clippy -- -D warnings",
            kind=CommandKind.LINT,
            safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
            provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            confidence=ConfidenceLevel.DEFINITE,
        ),
        DetectedCommand(
            command="cargo fmt --check",
            kind=CommandKind.FORMAT,
            safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
            provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            confidence=ConfidenceLevel.DEFINITE,
        ),
        DetectedCommand(
            command="cargo fmt",
            kind=CommandKind.FORMAT,
            safety_classification=SafetyClassification.WRITES_WORKSPACE,
            provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            confidence=ConfidenceLevel.DEFINITE,
        ),
        DetectedCommand(
            command="cargo build",
            kind=CommandKind.BUILD,
            safety_classification=SafetyClassification.READ_ONLY_VALIDATION,
            provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
            confidence=ConfidenceLevel.DEFINITE,
        ),
    ]


def _read_json(path: Path) -> dict | None:
    import json

    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

"""Ecosystem detection for Python, TypeScript, and Rust repositories.

Slice 1A: Desktop Repository Preview Intake v1.
Detects language ecosystems from manifest files and conventional config.
Pure functions — no side effects, no writes.
"""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

from rig_relay.digestion.models import DetectedEcosystem

_PYTHON_FILE_THRESHOLD = 5


def detect_ecosystems(repo_root: Path) -> list[DetectedEcosystem]:
    """Detect language ecosystems from manifest files in the repository.

    Inspects pyproject.toml, package.json, Cargo.toml, and supporting
    config files to determine languages, package managers, build systems,
    test frameworks, lint tools, type checkers, and formatters.
    """
    ecosystems: list[DetectedEcosystem] = []

    pyproject = _read_toml(repo_root / "pyproject.toml")
    package_json = _read_json(repo_root / "package.json")
    cargo_toml = _read_toml(repo_root / "Cargo.toml")

    # Python detection
    if pyproject is not None or _has_python_files(repo_root):
        ecosystems.append(_detect_python(repo_root, pyproject))

    # TypeScript/Node detection
    if package_json is not None:
        ecosystems.append(_detect_typescript(repo_root, package_json))

    # Rust detection
    if cargo_toml is not None:
        ecosystems.append(_detect_rust(repo_root, cargo_toml))

    return ecosystems


def _detect_python(  # noqa: PLR0912,PLR0914,PLR0915
    repo_root: Path, pyproject: dict | None
) -> DetectedEcosystem:
    """Detect Python ecosystem from pyproject.toml and conventions."""
    from rig_relay.digestion.models import (
        ConfidenceLevel,
        DetectedEcosystem,
        ProvenanceClass,
    )

    confidence = (
        ConfidenceLevel.DEFINITE if pyproject is not None else ConfidenceLevel.INFERRED
    )
    evidence = []
    if pyproject is not None:
        evidence.append("pyproject.toml")
    if (repo_root / "uv.lock").exists():
        evidence.append("uv.lock")

    # Package manager detection
    pkg_manager = None
    if (repo_root / "uv.lock").exists():
        pkg_manager = "uv"
    elif (repo_root / "poetry.lock").exists():
        pkg_manager = "poetry"
    elif (repo_root / "Pipfile.lock").exists():
        pkg_manager = "pipenv"

    # Build system from [build-system]
    build_system = None
    if pyproject is not None:
        bs = pyproject.get("build-system", {})
        requires = bs.get("requires", []) if isinstance(bs, dict) else []
        for r in requires:
            r_str = str(r)
            if "hatchling" in r_str:
                build_system = "hatchling"
                break
            elif "setuptools" in r_str:
                build_system = "setuptools"
                break
            elif "flit" in r_str:
                build_system = "flit"
                break

    # Test frameworks from dev dependencies
    test_frameworks: list[str] = []
    lint_tools: list[str] = []
    type_checkers: list[str] = []
    formatters: list[str] = []

    if pyproject is not None:
        dep_groups = pyproject.get("dependency-groups", {})
        dev_deps = dep_groups.get("dev", []) if isinstance(dep_groups, dict) else []
        opt_deps = pyproject.get("optional-dependencies", {})
        dev_opt = opt_deps.get("dev", []) if isinstance(opt_deps, dict) else []

        all_dev = list(dev_deps) + list(dev_opt)
        for dep in all_dev:
            dep_str = str(dep).lower()
            if "pytest" in dep_str:
                test_frameworks.append("pytest")
            elif "unittest" in dep_str:
                test_frameworks.append("unittest")
            if "ruff" in dep_str:
                if "ruff" not in lint_tools:
                    lint_tools.append("ruff")
                if "ruff" not in formatters:
                    formatters.append("ruff-format")
            if "pyright" in dep_str or "pyre" in dep_str:
                if "pyre" in dep_str and "pyright" not in type_checkers:
                    type_checkers.append("pyright")
                elif "pyright" not in type_checkers:
                    type_checkers.append("pyright")
            if "mypy" in dep_str and "mypy" not in type_checkers:
                type_checkers.append("mypy")

        # Check for tool configs
        if "tool" in pyproject:
            tool = pyproject["tool"]
            if isinstance(tool, dict):
                if "pytest" in tool:
                    if "pytest" not in test_frameworks:
                        test_frameworks.append("pytest")
                if "ruff" in tool:
                    if "ruff" not in lint_tools:
                        lint_tools.append("ruff")
                if "pyright" in tool or "pyre" in tool:
                    if "pyright" not in type_checkers:
                        type_checkers.append("pyright")

    # Deduplicate
    test_frameworks = list(dict.fromkeys(test_frameworks))
    lint_tools = list(dict.fromkeys(lint_tools))
    type_checkers = list(dict.fromkeys(type_checkers))
    formatters = list(dict.fromkeys(formatters))

    # Entry points
    entry_points = _find_python_entry_points(repo_root)

    return DetectedEcosystem(
        language="python",
        confidence=confidence,
        evidence_files=evidence,
        package_manager=pkg_manager,
        build_system=build_system,
        test_frameworks=test_frameworks,
        lint_tools=lint_tools,
        type_checkers=type_checkers,
        formatters=formatters,
        entry_points=entry_points,
        provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
    )


def _detect_typescript(repo_root: Path, package_json: dict) -> DetectedEcosystem:
    """Detect TypeScript/Node ecosystem from package.json."""
    from rig_relay.digestion.models import (
        ConfidenceLevel,
        DetectedEcosystem,
        ProvenanceClass,
    )

    evidence = ["package.json"]
    has_tsconfig = (repo_root / "tsconfig.json").exists()
    if has_tsconfig:
        evidence.append("tsconfig.json")

    confidence = ConfidenceLevel.DEFINITE if has_tsconfig else ConfidenceLevel.INFERRED
    language = "typescript" if has_tsconfig else "javascript"

    # Package manager
    pkg_manager = None
    if (repo_root / "package-lock.json").exists():
        pkg_manager = "npm"
    elif (repo_root / "yarn.lock").exists():
        pkg_manager = "yarn"
    elif (repo_root / "pnpm-lock.yaml").exists():
        pkg_manager = "pnpm"

    # Dev dependencies
    dev_deps: dict[str, str] = {}
    if isinstance(package_json.get("devDependencies"), dict):
        dev_deps = package_json["devDependencies"]
    all_deps = {**package_json.get("dependencies", {}), **dev_deps}

    test_frameworks: list[str] = []
    lint_tools: list[str] = []
    type_checkers: list[str] = []
    formatters: list[str] = []

    dep_keys = {str(k).lower() for k in all_deps}
    if "jest" in dep_keys or "vitest" in dep_keys:
        for fw in ("jest", "vitest", "mocha", "jasmine"):
            if fw in dep_keys:
                test_frameworks.append(fw)
    if "eslint" in dep_keys:
        lint_tools.append("eslint")
    if "prettier" in dep_keys:
        formatters.append("prettier")
    if "typescript" in dep_keys:
        type_checkers.append("tsc")

    # Entry points
    entry_points = _find_ts_entry_points(repo_root, package_json)

    return DetectedEcosystem(
        language=language,
        confidence=confidence,
        evidence_files=evidence,
        package_manager=pkg_manager,
        build_system=None,
        test_frameworks=test_frameworks,
        lint_tools=lint_tools,
        type_checkers=type_checkers,
        formatters=formatters,
        entry_points=entry_points,
        provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
    )


def _detect_rust(repo_root: Path, cargo_toml: dict) -> DetectedEcosystem:
    """Detect Rust ecosystem from Cargo.toml."""
    from rig_relay.digestion.models import (
        ConfidenceLevel,
        DetectedEcosystem,
        ProvenanceClass,
    )

    evidence = ["Cargo.toml"]
    if (repo_root / "Cargo.lock").exists():
        evidence.append("Cargo.lock")

    # Entry points
    entry_points = _find_rust_entry_points(repo_root, cargo_toml)

    return DetectedEcosystem(
        language="rust",
        confidence=ConfidenceLevel.DEFINITE,
        evidence_files=evidence,
        package_manager="cargo",
        build_system="cargo",
        test_frameworks=["cargo-test"],
        lint_tools=["clippy"],
        type_checkers=[],
        formatters=["cargo-fmt"],
        entry_points=entry_points,
        provenance=ProvenanceClass.FILESYSTEM_MANIFEST,
    )


# ── Helpers ──────────────────────────────────────────────────────


def _read_toml(path: Path) -> dict | None:
    """Read a TOML file, returning None if absent or unparseable."""
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None if absent or unparseable."""
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _has_python_files(root: Path) -> bool:
    """Check if the repo contains Python files."""
    count = 0
    for p in root.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        count += 1
        if count >= _PYTHON_FILE_THRESHOLD:
            return True
    return False


def _find_python_entry_points(root: Path) -> list[str]:
    """Find Python entry point files."""
    candidates = []
    for pattern in ("__main__.py", "entrypoint.py", "main.py", "app.py", "cli.py"):
        for p in root.rglob(pattern):
            if ".venv" in p.parts or "__pycache__" in p.parts:
                continue
            candidates.append(str(p.relative_to(root)))
    # Also check pyproject.toml scripts
    pyproject = _read_toml(root / "pyproject.toml")
    if pyproject is not None:
        scripts = pyproject.get("project", {}).get("scripts", {})
        if isinstance(scripts, dict):
            for _name, path in scripts.items():
                candidates.append(f"[project.scripts] {_name}: {path}")
    return candidates[:10]


def _find_ts_entry_points(root: Path, package_json: dict) -> list[str]:
    """Find TypeScript/Node entry point files."""
    candidates = []
    # From package.json main/module/bin
    main = package_json.get("main", "")
    if isinstance(main, str) and main:
        if (root / main).exists():
            candidates.append(main)
    module = package_json.get("module", "")
    if isinstance(module, str) and module:
        if (root / module).exists():
            candidates.append(module)
    bin_entry = package_json.get("bin", {})
    if isinstance(bin_entry, dict):
        for _name, path in bin_entry.items():
            if isinstance(path, str):
                candidates.append(path)
    # Conventional entry files
    for pattern in ("src/index.ts", "src/index.js", "src/main.ts", "src/main.js"):
        if (root / pattern).exists():
            candidates.append(pattern)
    return candidates[:10]


def _find_rust_entry_points(root: Path, cargo_toml: dict) -> list[str]:
    """Find Rust entry point files."""
    candidates = []
    # From Cargo.toml [[bin]] sections
    bins = cargo_toml.get("bin", [])
    if isinstance(bins, list):
        for b in bins:
            if isinstance(b, dict):
                path = b.get("path", "")
                if isinstance(path, str):
                    candidates.append(path)
    # Conventional entry files
    if (root / "src" / "main.rs").exists():
        candidates.append("src/main.rs")
    if (root / "src" / "lib.rs").exists():
        candidates.append("src/lib.rs")
    return candidates[:10]

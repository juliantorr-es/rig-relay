from __future__ import annotations

from pathlib import Path
import tomllib

from rig_relay.core.logger import logger
from rig_relay.digestion.dependency_classifier.models import (
    DependencyEntry,
    DependencyKind,
    DependencyRisk,
    PackageManagerKind,
    known_deprecated_packages,
)


def parse_rust_dependencies(
    repo_root: Path, package_manager: PackageManagerKind | None
) -> list[DependencyEntry]:
    del package_manager

    deps: list[DependencyEntry] = []
    cargo_toml = _read_toml(repo_root / "Cargo.toml")
    if cargo_toml is None:
        return deps

    deprecated = known_deprecated_packages(PackageManagerKind.CARGO)

    sections: list[tuple[str, DependencyKind]] = [
        ("dependencies", DependencyKind.PRODUCTION),
        ("dev-dependencies", DependencyKind.DEV),
        ("build-dependencies", DependencyKind.BUILD),
    ]

    for section_key, kind in sections:
        section = cargo_toml.get(section_key)
        if not isinstance(section, dict):
            continue
        for name, value in section.items():
            name = str(name)
            spec = _extract_version_spec(value)
            risk = _classify_risk(deprecated, name, spec)
            deps.append(
                DependencyEntry(
                    name=name, version_spec=spec, kind=kind, risk=risk, is_direct=True
                )
            )

    transitive_names = _parse_lockfile_transitive(repo_root, deps)
    existing = {d.name for d in deps}
    for tname in transitive_names:
        if tname not in existing:
            deps.append(
                DependencyEntry(
                    name=tname,
                    version_spec=None,
                    kind=DependencyKind.PRODUCTION,
                    risk=DependencyRisk.NONE,
                    is_direct=False,
                )
            )

    return deps


def _extract_version_spec(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        ver = value.get("version")
        if isinstance(ver, str):
            return ver
        features = value.get("features")
        if isinstance(features, list) and len(features) > 0:
            return f"features: {', '.join(str(f) for f in features)}"
    return None


def _classify_risk(
    deprecated: frozenset[str], name: str, spec: str | None
) -> DependencyRisk:
    if name in deprecated:
        return DependencyRisk.DEPRECATED
    if spec is None:
        return DependencyRisk.NONE
    if spec == "*":
        return DependencyRisk.UNKNOWN
    if spec.startswith(">") and "<" not in spec and "," not in spec:
        return DependencyRisk.UNKNOWN
    if spec.startswith(">=") and "<" not in spec and "," not in spec:
        return DependencyRisk.UNKNOWN
    return DependencyRisk.NONE


def _parse_lockfile_transitive(
    repo_root: Path, direct_deps: list[DependencyEntry]
) -> set[str]:
    _ = direct_deps
    names: set[str] = set()

    cargo_lock = _read_toml(repo_root / "Cargo.lock")
    if cargo_lock is None:
        return names

    packages = cargo_lock.get("package", [])
    if isinstance(packages, list):
        for p in packages:
            if isinstance(p, dict):
                name = p.get("name")
                if isinstance(name, str):
                    names.add(name)
    return names


def _read_toml(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        logger.warning("Failed to parse TOML: %s", path)
        return None

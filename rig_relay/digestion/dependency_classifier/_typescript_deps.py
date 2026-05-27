from __future__ import annotations

import json
from pathlib import Path

from rig_relay.core.logger import logger
from rig_relay.digestion.dependency_classifier.models import (
    DependencyEntry,
    DependencyKind,
    DependencyRisk,
    PackageManagerKind,
    known_deprecated_packages,
)


def parse_typescript_dependencies(
    repo_root: Path, package_manager: PackageManagerKind | None
) -> list[DependencyEntry]:
    deps: list[DependencyEntry] = []
    package_json = _read_json(repo_root / "package.json")
    if package_json is None:
        return deps

    pm = package_manager or PackageManagerKind.NPM
    deprecated = known_deprecated_packages(pm)

    direct_names: set[str] = set()

    sections: list[tuple[dict | None, DependencyKind]] = [
        (package_json.get("dependencies"), DependencyKind.PRODUCTION),
        (package_json.get("devDependencies"), DependencyKind.DEV),
        (package_json.get("peerDependencies"), DependencyKind.PEER),
        (package_json.get("optionalDependencies"), DependencyKind.OPTIONAL),
    ]

    for section, kind in sections:
        if not isinstance(section, dict):
            continue
        for name, spec in section.items():
            name = str(name)
            direct_names.add(name)
            version_spec = str(spec) if spec is not None else None
            risk = _classify_risk(deprecated, name, version_spec)
            deps.append(
                DependencyEntry(
                    name=name,
                    version_spec=version_spec,
                    kind=kind,
                    risk=risk,
                    is_direct=True,
                )
            )

    transitive_names = _parse_lockfile_transitive(repo_root)
    if transitive_names:
        for tname in transitive_names:
            if tname not in direct_names:
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


def _classify_risk(
    deprecated: frozenset[str], name: str, spec: str | None
) -> DependencyRisk:
    if name in deprecated:
        return DependencyRisk.DEPRECATED
    if spec is None or spec in {"*", "latest"}:
        return DependencyRisk.UNKNOWN
    if spec.startswith("^") or spec.startswith("~"):
        return DependencyRisk.NONE
    if (spec.startswith(">") or spec.startswith(">=")) and "<" not in spec:
        return DependencyRisk.UNKNOWN
    return DependencyRisk.NONE


def _parse_lockfile_transitive(repo_root: Path) -> set[str]:
    names: set[str] = set()

    package_lock = _read_json(repo_root / "package-lock.json")
    if package_lock is not None:
        packages = package_lock.get("packages", {})
        if isinstance(packages, dict):
            for key in packages:
                key_str = str(key)
                if key_str and key_str.startswith("node_modules/"):
                    pkg_name = key_str[len("node_modules/") :]
                    if "/" not in pkg_name:
                        names.add(pkg_name)
        return names

    return names


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to parse JSON: %s", path)
        return None

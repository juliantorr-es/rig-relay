from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

from rig_relay.core.logger import logger
from rig_relay.digestion.dependency_classifier.models import (
    DependencyEntry,
    DependencyKind,
    DependencyRisk,
    PackageManagerKind,
    known_deprecated_packages,
)

_NAME_SPEC_RE = re.compile(r"^(?P<name>[a-zA-Z0-9_.-]+)\s*(?P<spec>.+)?$")

_EXTRAS_STRIP_RE = re.compile(r"\[.*?\]")


def parse_python_dependencies(
    repo_root: Path, package_manager: PackageManagerKind | None
) -> list[DependencyEntry]:
    deps: list[DependencyEntry] = []
    pyproject = _read_toml(repo_root / "pyproject.toml")
    if pyproject is None:
        return deps

    deprecated = known_deprecated_packages(package_manager or PackageManagerKind.UV)

    project = pyproject.get("project", {}) if isinstance(pyproject, dict) else {}
    if isinstance(project, dict):
        raw_deps = project.get("dependencies", [])
        if isinstance(raw_deps, list):
            for raw in raw_deps:
                raw_name, spec = _split_name_spec(str(raw))
                name = _EXTRAS_STRIP_RE.sub("", raw_name)
                deps.append(
                    DependencyEntry(
                        name=name,
                        version_spec=spec,
                        kind=DependencyKind.PRODUCTION,
                        risk=_classify_risk(deprecated, name, spec),
                        is_direct=True,
                    )
                )

        opt_deps = project.get("optional-dependencies", {})
        if isinstance(opt_deps, dict):
            for _group, pkgs in opt_deps.items():
                if not isinstance(pkgs, list):
                    continue
                for raw in pkgs:
                    raw_name, spec = _split_name_spec(str(raw))
                    name = _EXTRAS_STRIP_RE.sub("", raw_name)
                    deps.append(
                        DependencyEntry(
                            name=name,
                            version_spec=spec,
                            kind=DependencyKind.OPTIONAL,
                            risk=_classify_risk(deprecated, name, spec),
                            is_direct=True,
                        )
                    )

    dep_groups = pyproject.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        for group, pkgs in dep_groups.items():
            if not isinstance(pkgs, list):
                continue
            kind = _group_kind(str(group))
            for raw in pkgs:
                raw_name, spec = _split_name_spec(str(raw))
                name = _EXTRAS_STRIP_RE.sub("", raw_name)
                deps.append(
                    DependencyEntry(
                        name=name,
                        version_spec=spec,
                        kind=kind,
                        risk=_classify_risk(deprecated, name, spec),
                        is_direct=True,
                    )
                )

    transitive_names = _parse_lockfile_transitive(repo_root)
    if transitive_names:
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


def _group_kind(group: str) -> DependencyKind:
    match group:
        case "dev" | "test":
            return DependencyKind.DEV
        case "build":
            return DependencyKind.BUILD
        case _:
            return DependencyKind.DEV


def _split_name_spec(raw: str) -> tuple[str, str | None]:
    m = _NAME_SPEC_RE.match(raw.strip())
    if m is None:
        return raw.strip(), None
    name = m.group("name")
    spec = m.group("spec")
    if spec is not None:
        spec = spec.strip()
    return name, spec


def _classify_risk(
    deprecated: frozenset[str], name: str, spec: str | None
) -> DependencyRisk:
    if name in deprecated:
        return DependencyRisk.DEPRECATED
    if spec is None:
        return DependencyRisk.UNKNOWN
    if spec == "*":
        return DependencyRisk.UNKNOWN
    if spec.startswith(">") and "<" not in spec and "," not in spec:
        return DependencyRisk.UNKNOWN
    if spec.startswith(">=") and "<" not in spec and "," not in spec:
        if spec != ">=0":
            return DependencyRisk.UNKNOWN
    return DependencyRisk.NONE


def _parse_lockfile_transitive(repo_root: Path) -> set[str]:
    names: set[str] = set()

    uv_lock = _read_toml(repo_root / "uv.lock")
    if uv_lock is not None and isinstance(uv_lock, dict):
        packages = uv_lock.get("package", [])
        if isinstance(packages, list):
            for p in packages:
                if isinstance(p, dict):
                    name = p.get("name")
                    if isinstance(name, str):
                        names.add(name)
        return names

    req_txt = _read_lines(repo_root / "requirements.txt")
    if req_txt:
        for line in req_txt:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name, _ = _split_name_spec(line)
            names.add(_EXTRAS_STRIP_RE.sub("", name))
        return names

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


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to parse JSON: %s", path)
        return None


def _read_lines(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    try:
        return path.read_text().splitlines()
    except Exception:
        logger.warning("Failed to read file: %s", path)
        return None

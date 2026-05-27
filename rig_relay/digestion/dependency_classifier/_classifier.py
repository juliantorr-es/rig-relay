from __future__ import annotations

from pathlib import Path

from rig_relay.core.logger import logger
from rig_relay.digestion.dependency_classifier._python_deps import (
    parse_python_dependencies,
)
from rig_relay.digestion.dependency_classifier._rust_deps import parse_rust_dependencies
from rig_relay.digestion.dependency_classifier._typescript_deps import (
    parse_typescript_dependencies,
)
from rig_relay.digestion.dependency_classifier.models import (
    ClassifiedDependencies,
    DependencyEntry,
    DependencyKind,
    DependencyRisk,
    PackageManagerKind,
    package_manager_from_string,
)
from rig_relay.digestion.models import DetectedEcosystem


class DependencyClassifier:
    def classify_dependencies(
        self, repository_root: Path, ecosystems: list[DetectedEcosystem]
    ) -> ClassifiedDependencies:
        all_deps: list[DependencyEntry] = []
        pm_kind: PackageManagerKind | None = None

        for eco in ecosystems:
            language = eco.language.lower()
            eco_pm = package_manager_from_string(eco.package_manager)
            if eco_pm is not None:
                pm_kind = eco_pm

            match language:
                case "python":
                    parsed = parse_python_dependencies(repository_root, eco_pm)
                    all_deps.extend(parsed)
                case "typescript" | "javascript":
                    parsed = parse_typescript_dependencies(repository_root, eco_pm)
                    all_deps.extend(parsed)
                case "rust":
                    parsed = parse_rust_dependencies(repository_root, eco_pm)
                    all_deps.extend(parsed)
                case _:
                    logger.debug("Unsupported ecosystem language: %s", language)
                    continue

        if pm_kind is None:
            pm_kind = _infer_package_manager(repository_root)

        classified = ClassifiedDependencies(
            repository_root=repository_root,
            package_manager=pm_kind,
            dependencies=all_deps,
            total_count=len(all_deps),
            production_count=sum(
                1 for d in all_deps if d.kind == DependencyKind.PRODUCTION
            ),
            dev_count=sum(
                1
                for d in all_deps
                if d.kind in {DependencyKind.DEV, DependencyKind.BUILD}
            ),
            risk_count=sum(1 for d in all_deps if d.risk != DependencyRisk.NONE),
        )
        classified.classification_digest = classified.compute_digest()
        return classified


def _infer_package_manager(repo_root: Path) -> PackageManagerKind:
    has_uv = (repo_root / "uv.lock").exists()
    has_pyproject = (repo_root / "pyproject.toml").exists()
    has_package_json = (repo_root / "package.json").exists()
    has_cargo = (repo_root / "Cargo.toml").exists()

    if has_uv or has_pyproject:
        return PackageManagerKind.UV
    if has_cargo:
        return PackageManagerKind.CARGO
    if has_package_json:
        if (repo_root / "pnpm-lock.yaml").exists():
            return PackageManagerKind.PNPM
        if (repo_root / "yarn.lock").exists():
            return PackageManagerKind.YARN
        return PackageManagerKind.NPM
    return PackageManagerKind.UV

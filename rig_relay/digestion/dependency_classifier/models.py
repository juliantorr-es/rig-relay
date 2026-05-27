from __future__ import annotations

from enum import StrEnum, auto
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DependencyKind(StrEnum):
    PRODUCTION = auto()
    DEV = auto()
    BUILD = auto()
    OPTIONAL = auto()
    PEER = auto()


class DependencyRisk(StrEnum):
    NONE = auto()
    DEPRECATED = auto()
    UNMAINTAINED = auto()
    VULNERABLE = auto()
    CONFLICT = auto()
    UNKNOWN = auto()


class PackageManagerKind(StrEnum):
    PIP = auto()
    POETRY = auto()
    UV = auto()
    NPM = auto()
    YARN = auto()
    PNPM = auto()
    CARGO = auto()


_DEPRECATED_PYTHON_PACKAGES: frozenset[str] = frozenset({
    "distribute",
    "setuptools-git",
    "nose",
    "pymongo",
    "pil",
    "MySQL-python",
    "BeautifulSoup",
    "functools32",
    "os.path.path",
})

_DEPRECATED_JS_PACKAGES: frozenset[str] = frozenset({
    "request",
    "core-js",
    "left-pad",
    "babel-eslint",
    "gulp-util",
    "deep-extend",
    "hoek",
    "cryptiles",
})

_DEPRECATED_RUST_CRATES: frozenset[str] = frozenset({
    "try_trait",
    "std-semaphore",
    "chan",
    "chan-signal",
    "argparse",
    "getopts",
    "rustc-serialize",
    "tempdir",
    "timer",
})


def known_deprecated_packages(pm: PackageManagerKind) -> frozenset[str]:
    match pm:
        case PackageManagerKind.PIP | PackageManagerKind.POETRY | PackageManagerKind.UV:
            return _DEPRECATED_PYTHON_PACKAGES
        case PackageManagerKind.NPM | PackageManagerKind.YARN | PackageManagerKind.PNPM:
            return _DEPRECATED_JS_PACKAGES
        case PackageManagerKind.CARGO:
            return _DEPRECATED_RUST_CRATES


_PACKAGE_MANAGER_MAP: dict[str, PackageManagerKind] = {
    "uv": PackageManagerKind.UV,
    "poetry": PackageManagerKind.POETRY,
    "pip": PackageManagerKind.PIP,
    "pipenv": PackageManagerKind.PIP,
    "npm": PackageManagerKind.NPM,
    "yarn": PackageManagerKind.YARN,
    "yarn_classic": PackageManagerKind.YARN,
    "yarn_berry": PackageManagerKind.YARN,
    "pnpm": PackageManagerKind.PNPM,
    "cargo": PackageManagerKind.CARGO,
}


def package_manager_from_string(raw: str | None) -> PackageManagerKind | None:
    if raw is None:
        return None
    return _PACKAGE_MANAGER_MAP.get(raw.lower())


class DependencyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Package name.")
    version_spec: str | None = Field(
        default=None, description="Raw version specifier string from the manifest."
    )
    kind: DependencyKind = Field(
        description="Production, dev, build, optional, or peer."
    )
    risk: DependencyRisk = Field(
        default=DependencyRisk.NONE, description="Risk classification."
    )
    is_direct: bool = Field(
        default=True, description="True if declared directly in the manifest."
    )
    reason: str | None = Field(
        default=None, description="Why this classification was applied."
    )


class ClassifiedDependencies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_root: Path = Field(description="Absolute path to the repository root.")
    package_manager: PackageManagerKind = Field(
        description="Detected package manager for this dependency set."
    )
    dependencies: list[DependencyEntry] = Field(
        default_factory=list, description="All classified dependency entries."
    )
    total_count: int = Field(default=0, description="Total dependency count.")
    production_count: int = Field(default=0, description="Production dependency count.")
    dev_count: int = Field(default=0, description="Development dependency count.")
    risk_count: int = Field(
        default=0, description="Count of dependencies with risk > NONE."
    )
    classification_digest: str = Field(
        default="",
        description="SHA256 digest of canonical JSON for this classification.",
    )

    def compute_digest(self) -> str:
        entries = sorted(
            [
                {
                    "name": d.name,
                    "version_spec": d.version_spec,
                    "kind": d.kind.value,
                    "risk": d.risk.value,
                    "is_direct": d.is_direct,
                    "reason": d.reason,
                }
                for d in self.dependencies
            ],
            key=lambda e: (e["name"], e["kind"]),
        )
        canonical = json.dumps(
            {
                "repository_root": str(self.repository_root),
                "package_manager": self.package_manager.value,
                "dependencies": entries,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

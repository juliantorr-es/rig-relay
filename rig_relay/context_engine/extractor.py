"""Source-derived structural extractor for context assembly.

Deterministically extracts structural facts from a real repository:
package manifests, language signals, framework signals, test infrastructure,
build systems, documentation signals, and publication assets.

All facts carry provenance (source_path, extraction_method).
No model assertion or heuristics that produce facts without provenance.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rig_relay.context_engine.models import (
    IntakeDependencyStatus,
    PublicationAssets,
    TechnologySignals,
    TestSignals,
)
from rig_relay.context_engine.provenance import (
    FactOrigin,
    PrivacyDisposition,
    SourceDerivedFact,
)

if TYPE_CHECKING:
    from rig_relay.context_engine.fixtures import IntakeFixture


class SourceDerivedStructuralExtractor:
    """Extracts structural facts from a repository using deterministic methods.

    Reads manifest files (pyproject.toml, package.json, Cargo.toml, etc.),
    inspects directory structure, and detects signals through parsers
    and indexers. Every fact carries the source file path and extraction
    method that produced it. Never asserts facts from model inference alone.
    """

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()
        self._fact_counter = 0

    def extract_all(
        self, intake: IntakeFixture | None = None
    ) -> list[SourceDerivedFact]:
        """Extract all structural facts from the repository."""
        facts: list[SourceDerivedFact] = []

        facts.extend(self._extract_languages())
        facts.extend(self._extract_frameworks())
        facts.extend(self._extract_build_systems())
        facts.extend(self._extract_test_frameworks())
        facts.extend(self._extract_lint_tools())
        facts.extend(self._extract_type_checkers())
        facts.extend(self._extract_formatters())
        facts.extend(self._extract_package_managers())
        facts.extend(self._extract_entry_points())
        facts.extend(self._extract_readme())
        facts.extend(self._extract_license())
        facts.extend(self._extract_documentation())
        facts.extend(self._extract_ci_cd())
        facts.extend(self._extract_github_pages())

        return facts

    def extract_technology_signals(
        self, intake: IntakeFixture | None = None
    ) -> TechnologySignals:
        """Extract technology signals as a structured model."""
        facts = self.extract_all(intake)
        return _technology_signals_from_facts(facts)

    def extract_publication_assets(self) -> PublicationAssets:
        """Detect publication-ready documentation assets."""
        return PublicationAssets(
            has_readme=(self._root / "README.md").exists(),
            has_license=_has_license_file(self._root),
            has_contributing=(self._root / "CONTRIBUTING.md").exists(),
            has_changelog=(self._root / "CHANGELOG.md").exists(),
            has_security_policy=(self._root / "SECURITY.md").exists(),
            has_documentation_site=_detect_documentation_site(self._root),
            screenshot_count=0,
            demo_count=0,
            publication_ready_asset_count=0,
        )

    def extract_test_signals(self) -> TestSignals:
        """Detect test infrastructure signals."""
        facts = self.extract_all()
        test_frameworks = [f.value for f in facts if f.category == "test_framework"]
        test_commands = [f for f in facts if f.category == "test_command"]
        test_dirs = [f for f in facts if f.category == "test_directory"]
        ci_facts = [f for f in facts if f.category == "ci_cd"]

        return TestSignals(
            test_framework_detected=len(test_frameworks) > 0,
            test_command_detected=len(test_commands) > 0,
            ci_test_pipeline_detected=any(
                "test" in f.value.lower() or "pytest" in f.value.lower()
                for f in ci_facts
            ),
            coverage_tool_detected=any(
                "coverage" in f.value.lower() or "codecov" in f.value.lower()
                for f in facts
            ),
            test_directory_detected=len(test_dirs) > 0,
        )

    def extract_bootstrap_gaps(self) -> list[str]:
        """Identify bootstrap gaps where signals are missing."""
        gaps: list[str] = []
        assets = self.extract_publication_assets()
        if not assets.has_readme:
            gaps.append("No README.md found — project page needs manual description")
        if not assets.has_license:
            gaps.append("No license file detected")
        if not assets.has_documentation_site:
            gaps.append("No documentation site detected")
        facts = self.extract_all()
        if not any(f.category == "test_framework" for f in facts):
            gaps.append("No test framework detected")
        if not any(f.category == "ci_cd" for f in facts):
            gaps.append("No CI/CD pipeline detected")
        return gaps

    def extract_intake_dependency_status(self) -> IntakeDependencyStatus:
        """Produce the intake dependency status."""
        return IntakeDependencyStatus(
            j0_intake_boundary="fixture",
            k0_investigation_boundary="fixture",
            j0_intake_available=False,
            k0_investigation_available=False,
        )

    # ── Private extractors ───────────────────────────────────────────

    def _next_id(self) -> str:
        self._fact_counter += 1
        return f"fact_{self._fact_counter:04d}"

    def _fact(
        self,
        category: str,
        value: str,
        source_path: str,
        source_kind: str,
        extraction_method: str,
        confidence: str = "high",
    ) -> SourceDerivedFact:
        return SourceDerivedFact(
            fact_id=self._next_id(),
            category=category,
            value=value,
            source_path=source_path,
            source_kind=source_kind,
            extraction_method=extraction_method,
            confidence=confidence,
            provenance=FactOrigin.SOURCE_DERIVED,
            privacy_disposition=PrivacyDisposition.PUBLIC_SAFE,
        )

    def _extract_languages(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        if (self._root / "pyproject.toml").exists():
            facts.append(
                self._fact(
                    "language",
                    "python",
                    "pyproject.toml",
                    "pyproject.toml",
                    "manifest_reader",
                )
            )
        if (self._root / "package.json").exists():
            facts.append(
                self._fact(
                    "language",
                    "javascript/typescript",
                    "package.json",
                    "package.json",
                    "manifest_reader",
                    "medium",
                )
            )
        if (self._root / "tsconfig.json").exists():
            facts.append(
                self._fact(
                    "language",
                    "typescript",
                    "tsconfig.json",
                    "tsconfig.json",
                    "manifest_reader",
                )
            )
        if (self._root / "Cargo.toml").exists():
            facts.append(
                self._fact(
                    "language", "rust", "Cargo.toml", "Cargo.toml", "manifest_reader"
                )
            )
        if (self._root / "go.mod").exists():
            facts.append(
                self._fact("language", "go", "go.mod", "go.mod", "manifest_reader")
            )
        return facts

    def _extract_frameworks(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            deps = _all_deps(pyproject)
            for dep in deps:
                dl = dep.lower()
                if "fastapi" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "fastapi",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "django" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "django",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "flask" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "flask",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "pydantic" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "pydantic",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "textual" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "textual",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "pywebview" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "pywebview",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "duckdb" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "duckdb",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "jinja2" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "jinja2",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "websockets" in dl:
                    facts.append(
                        self._fact(
                            "framework",
                            "websockets",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
        return facts

    def _extract_build_systems(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            bs = pyproject.get("build-system", {})
            requires = bs.get("requires", []) if isinstance(bs, dict) else []
            for r in requires:
                r_str = str(r).lower()
                if "hatchling" in r_str:
                    facts.append(
                        self._fact(
                            "build_system",
                            "hatchling",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                elif "setuptools" in r_str:
                    facts.append(
                        self._fact(
                            "build_system",
                            "setuptools",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                elif "flit" in r_str:
                    facts.append(
                        self._fact(
                            "build_system",
                            "flit",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
            if (self._root / "uv.lock").exists():
                facts.append(
                    self._fact(
                        "package_manager", "uv", "uv.lock", "uv.lock", "file_detection"
                    )
                )
        if (self._root / "Cargo.toml").exists():
            facts.append(
                self._fact(
                    "build_system",
                    "cargo",
                    "Cargo.toml",
                    "Cargo.toml",
                    "manifest_reader",
                )
            )
        if (self._root / "Makefile").exists():
            facts.append(
                self._fact(
                    "build_system", "make", "Makefile", "Makefile", "file_detection"
                )
            )
        return facts

    def _extract_test_frameworks(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            deps = _all_deps(pyproject)
            for dep in deps:
                dl = dep.lower()
                if "pytest" in dl:
                    facts.append(
                        self._fact(
                            "test_framework",
                            "pytest",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "unittest" in dl:
                    facts.append(
                        self._fact(
                            "test_framework",
                            "unittest",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "hypothesis" in dl:
                    facts.append(
                        self._fact(
                            "test_framework",
                            "hypothesis",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
            # Also check tool config
            tool = pyproject.get("tool", {})
            if isinstance(tool, dict) and "pytest" in tool:
                facts.append(
                    self._fact(
                        "test_framework",
                        "pytest",
                        "pyproject.toml [tool.pytest]",
                        "pyproject.toml",
                        "manifest_reader",
                    )
                )
        if self._has_test_directory():
            facts.append(
                self._fact(
                    "test_directory",
                    "tests/",
                    "tests/",
                    "directory_structure",
                    "directory_scan",
                    "medium",
                )
            )
        if (self._root / "Cargo.toml").exists():
            facts.append(
                self._fact(
                    "test_framework",
                    "cargo-test",
                    "Cargo.toml",
                    "Cargo.toml",
                    "manifest_reader",
                )
            )
        return facts

    def _extract_lint_tools(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            deps = _all_deps(pyproject)
            for dep in deps:
                dl = dep.lower()
                if "ruff" in dl:
                    facts.append(
                        self._fact(
                            "lint_tool",
                            "ruff",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "vulture" in dl:
                    facts.append(
                        self._fact(
                            "lint_tool",
                            "vulture",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
        if (self._root / ".eslintrc.js").exists() or (
            self._root / ".eslintrc.json"
        ).exists():
            facts.append(
                self._fact(
                    "lint_tool",
                    "eslint",
                    ".eslintrc.*",
                    "config_file",
                    "file_detection",
                )
            )
        return facts

    def _extract_type_checkers(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            deps = _all_deps(pyproject)
            for dep in deps:
                dl = dep.lower()
                if "pyright" in dl or "pyre" in dl:
                    facts.append(
                        self._fact(
                            "type_checker",
                            "pyright",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
                if "mypy" in dl:
                    facts.append(
                        self._fact(
                            "type_checker",
                            "mypy",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
        if (self._root / "tsconfig.json").exists():
            facts.append(
                self._fact(
                    "type_checker",
                    "tsc",
                    "tsconfig.json",
                    "tsconfig.json",
                    "manifest_reader",
                )
            )
        return facts

    def _extract_formatters(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            deps = _all_deps(pyproject)
            for dep in deps:
                dl = dep.lower()
                if "ruff" in dl:
                    facts.append(
                        self._fact(
                            "formatter",
                            "ruff-format",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
        return facts

    def _extract_package_managers(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        if (self._root / "uv.lock").exists():
            facts.append(
                self._fact(
                    "package_manager", "uv", "uv.lock", "uv.lock", "file_detection"
                )
            )
        elif (self._root / "requirements.txt").exists():
            facts.append(
                self._fact(
                    "package_manager",
                    "pip",
                    "requirements.txt",
                    "requirements.txt",
                    "file_detection",
                )
            )
        if (self._root / "package-lock.json").exists():
            facts.append(
                self._fact(
                    "package_manager",
                    "npm",
                    "package-lock.json",
                    "package-lock.json",
                    "file_detection",
                )
            )
        if (self._root / "Cargo.lock").exists():
            facts.append(
                self._fact(
                    "package_manager",
                    "cargo",
                    "Cargo.lock",
                    "Cargo.lock",
                    "file_detection",
                )
            )
        return facts

    def _extract_entry_points(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pyproject = _read_pyproject(self._root)
        if pyproject:
            scripts = pyproject.get("project", {}).get("scripts", {})
            if isinstance(scripts, dict):
                for name in scripts:
                    facts.append(
                        self._fact(
                            "entry_point",
                            f"rig-relay: {name}",
                            "pyproject.toml",
                            "pyproject.toml",
                            "manifest_reader",
                        )
                    )
        for pattern in _ENTRY_POINT_PATTERNS:
            for dirpath, _dirnames, filenames in self._root.walk():
                _dirnames[:] = [d for d in _dirnames if d not in _SKIP_DIRS]
                for fname in filenames:
                    if fname == pattern:
                        rel = str((Path(dirpath) / fname).relative_to(self._root))
                        facts.append(
                            self._fact(
                                "entry_point", rel, rel, "source_file", "directory_scan"
                            )
                        )
                        if len(facts) >= 15:
                            return facts
        return facts

    def _extract_readme(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        readme = self._root / "README.md"
        if readme.exists():
            facts.append(
                self._fact(
                    "documentation",
                    "README.md present",
                    "README.md",
                    "README.md",
                    "file_detection",
                )
            )
            blurb = _safe_readme_blurb(readme)
            if blurb:
                facts.append(
                    self._fact(
                        "project_description",
                        blurb,
                        "README.md",
                        "README.md",
                        "header_extraction",
                    )
                )
        return facts

    def _extract_license(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
            lic = self._root / name
            if lic.exists():
                facts.append(
                    self._fact("license", name, name, "license_file", "file_detection")
                )
                break
        return facts

    def _extract_documentation(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        docs_dir = self._root / "docs"
        if docs_dir.is_dir():
            md_count = len(list(docs_dir.rglob("*.md")))
            facts.append(
                self._fact(
                    "documentation",
                    f"docs/ directory with ~{md_count} markdown files",
                    "docs/",
                    "directory_structure",
                    "directory_scan",
                )
            )
        return facts

    def _extract_ci_cd(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        workflows = self._root / ".github" / "workflows"
        if workflows.is_dir():
            wf_files = list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))
            for wf in wf_files:
                facts.append(
                    self._fact(
                        "ci_cd",
                        f"github_actions:{wf.name}",
                        str(wf.relative_to(self._root)),
                        "ci_workflow",
                        "file_detection",
                    )
                )
        return facts

    def _extract_github_pages(self) -> list[SourceDerivedFact]:
        facts: list[SourceDerivedFact] = []
        pages_yml = self._root / ".github" / "workflows" / "pages.yml"
        if pages_yml.exists():
            facts.append(
                self._fact(
                    "publication_surface",
                    "github_pages_workflow",
                    ".github/workflows/pages.yml",
                    "ci_workflow",
                    "file_detection",
                )
            )
        if (self._root / "docs" / "index.html").exists():
            facts.append(
                self._fact(
                    "publication_surface",
                    "docs/index.html static site",
                    "docs/index.html",
                    "static_site_file",
                    "file_detection",
                )
            )
        return facts

    def _has_test_directory(self) -> bool:
        return (self._root / "tests").is_dir() or (self._root / "test").is_dir()


# ── Helpers ──────────────────────────────────────────────────────────


def _read_pyproject(root: Path) -> dict | None:
    import tomllib

    fp = root / "pyproject.toml"
    if not fp.is_file():
        return None
    try:
        with open(fp, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def _all_deps(pyproject: dict) -> list[str]:
    deps: list[str] = []
    proj_deps = pyproject.get("project", {}).get("dependencies", [])
    if isinstance(proj_deps, list):
        deps.extend(str(d) for d in proj_deps)
    dep_groups = pyproject.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        for group_deps in dep_groups.values():
            if isinstance(group_deps, list):
                deps.extend(str(d) for d in group_deps)
    opt = pyproject.get("project", {}).get("optional-dependencies", {})
    if isinstance(opt, dict):
        for od in opt.values():
            if isinstance(od, list):
                deps.extend(str(d) for d in od)
    return deps


def _safe_readme_blurb(readme_path: Path) -> str:
    """Extract first meaningful paragraph from README — never raw source."""
    try:
        text = readme_path.read_text()[:2000]
        lines = text.split("\n")
        blurb_lines: list[str] = []
        in_header = True
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if in_header:
                    return stripped.lstrip("#").strip()
                continue
            if stripped.startswith("[!["):
                continue
            if stripped.startswith("!["):
                continue
            if stripped.startswith("<"):
                continue
            if stripped.startswith("```"):
                break
            in_header = False
            blurb_lines.append(stripped)
            if len(" ".join(blurb_lines)) > 200:
                break
        return " ".join(blurb_lines)[:300] if blurb_lines else ""
    except Exception:
        return ""


def _has_license_file(root: Path) -> bool:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        if (root / name).exists():
            return True
    return False


def _detect_documentation_site(root: Path) -> bool:
    docs_index = root / "docs" / "index.html"
    return docs_index.exists()


_SKIP_DIRS: set[str] = {
    ".venv",
    "venv",
    ".tox",
    "node_modules",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".build",
    "target",
}

_ENTRY_POINT_PATTERNS: tuple[str, ...] = (
    "__main__.py",
    "main.py",
    "entrypoint.py",
    "app.py",
)

_EXCLUDE_DIRS: set[str] = _SKIP_DIRS


def _should_skip_dir(parts: tuple) -> bool:
    return any(p in _SKIP_DIRS for p in parts)


def _count_screenshots(root: Path) -> int:
    count = 0
    try:
        for _dirpath, dirnames, _filenames in root.walk():
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in _filenames:
                fl = f.lower()
                if ("screenshot" in fl or "screencap" in fl) and any(
                    fl.endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp")
                ):
                    count += 1
                    if count >= 10:
                        return count
    except Exception:
        pass
    return count


def _count_demos(root: Path) -> int:
    count = 0
    try:
        for _dirpath, dirnames, _filenames in root.walk():
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in _filenames:
                fl = f.lower()
                if "demo" in fl and any(
                    fl.endswith(e) for e in (".gif", ".mp4", ".mov", ".webm")
                ):
                    count += 1
                    if count >= 10:
                        return count
    except Exception:
        pass
    return count


def _technology_signals_from_facts(facts: list[SourceDerivedFact]) -> TechnologySignals:
    signals = TechnologySignals()
    for f in facts:
        cat = f.category
        if cat == "language":
            if f.value not in signals.languages:
                signals.languages.append(f.value)
        elif cat == "framework":
            if f.value not in signals.frameworks:
                signals.frameworks.append(f.value)
        elif cat == "build_system":
            if f.value not in signals.build_systems:
                signals.build_systems.append(f.value)
        elif cat == "package_manager":
            if f.value not in signals.package_managers:
                signals.package_managers.append(f.value)
        elif cat == "test_framework":
            if f.value not in signals.test_frameworks:
                signals.test_frameworks.append(f.value)
        elif cat == "lint_tool":
            if f.value not in signals.lint_tools:
                signals.lint_tools.append(f.value)
        elif cat == "type_checker":
            if f.value not in signals.type_checkers:
                signals.type_checkers.append(f.value)
        elif cat == "formatter":
            if f.value not in signals.formatters:
                signals.formatters.append(f.value)
    return signals


__all__ = ["SourceDerivedStructuralExtractor"]

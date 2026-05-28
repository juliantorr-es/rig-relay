from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.logger import logger

if TYPE_CHECKING:
    from rig_relay.digestion.models import InstructionScopeCollection
from rig_relay.digestion.context_release import (
    DependencyRiskSummary,
    InstructionMapDigest,
    RepositoryContextRelease,
    StructuralIndexDigest,
    compute_digest,
)
from rig_relay.digestion.instruction_scanner import (
    build_scope_map,
    discover_instructions_with_content,
)
from rig_relay.digestion.structural_indexer import (
    StructuralIndex,
    StructuralIndexConfig,
    StructuralIndexer,
    StructuralIndexKind,
)

_INSTRUCTION_FILE_NAMES: frozenset[str] = frozenset({
    "AGENTS.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "PROJECT.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.rst",
    "CODEOWNERS",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CHANGELOG.md",
    "README.md",
    "LICENSE",
    ".cursorrules",
    ".windsurfrules",
})

_RULE_DIR_PATTERNS: frozenset[str] = frozenset({
    ".cursor/rules",
    ".claude/rules",
    ".github/instructions",
})

_MANIFEST_FILE_NAMES: frozenset[str] = frozenset({
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements.in",
    "Pipfile",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "tsconfig.json",
    "uv.lock",
})

_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
})

_MIN_PATH_PARTS_FOR_TEST_DIR = 2

_GLOBAL_SCOPE_ROOTS: frozenset[str] = frozenset({"", ".", "*"})


class StaleAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capsule_id: str = Field(description="Which capsule is stale.")
    stale_reason: str = Field(
        description="source_file_changed, instruction_changed, schema_changed, or dependency_changed."
    )
    affected_paths: list[str] = Field(
        default_factory=list, description="Paths that changed."
    )
    stale_since: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 timestamp when the capsule became stale.",
    )


class ChangedFileObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Relative path of changed file.")
    change_kind: str = Field(description="modified, added, deleted, or renamed.")
    before_digest: str | None = Field(
        default=None, description="SHA256 hex digest before change."
    )
    after_digest: str | None = Field(
        default=None, description="SHA256 hex digest after change."
    )
    is_instruction_file: bool = Field(default=False)
    is_source_file: bool = Field(default=False)
    is_manifest_file: bool = Field(default=False)
    is_schema_file: bool = Field(default=False)
    is_test_file: bool = Field(default=False)


class IncrementalContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release: RepositoryContextRelease = Field(
        description="The refreshed context release."
    )
    changed_files: list[ChangedFileObservation] = Field(
        default_factory=list, description="Observed file changes."
    )
    stale_capsules: list[StaleAnnotation] = Field(
        default_factory=list, description="Capsules that became stale."
    )
    reindexed_modules: int = Field(
        default=0, description="How many modules were re-parsed."
    )
    instructions_changed: bool = Field(
        default=False, description="True when instruction files were among the changes."
    )
    dependencies_changed: bool = Field(
        default=False, description="True when manifest/dependency files changed."
    )
    schemas_changed: bool = Field(
        default=False, description="True when JSON Schema files changed."
    )
    update_digest: str = Field(
        default="", description="SHA256 hex digest of the canonical incremental update."
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 timestamp when this update was emitted.",
    )


class IncrementalContextCompiler:
    def __init__(self, indexer: StructuralIndexer | None = None) -> None:
        self._indexer = indexer or StructuralIndexer(
            StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
        )

    def observe_changes(
        self, workspace_root: Path, previous_head_sha: str
    ) -> list[ChangedFileObservation]:
        root = workspace_root.resolve()
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "diff",
                    "--name-only",
                    f"{previous_head_sha}..HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("git diff failed in observe_changes: %s", exc)
            return []

        if result.returncode != 0:
            logger.warning(
                "git diff returned non-zero exit=%s stderr=%s",
                result.returncode,
                result.stderr.strip(),
            )
            return []

        paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        if not paths:
            return []

        observations: list[ChangedFileObservation] = []
        for rel_path in paths:
            abs_path = root / rel_path
            change_kind = _classify_change_kind(
                abs_path, rel_path, root, previous_head_sha
            )

            before_digest: str | None = None
            after_digest: str | None = None
            if change_kind == "deleted":
                before_digest = _git_show_digest(root, previous_head_sha, rel_path)
            elif change_kind == "added":
                after_digest = _file_digest(abs_path) if abs_path.is_file() else None
            elif change_kind == "renamed":
                after_digest = _file_digest(abs_path) if abs_path.is_file() else None
            else:
                before_digest = _git_show_digest(root, previous_head_sha, rel_path)
                after_digest = _file_digest(abs_path) if abs_path.is_file() else None

            observations.append(
                ChangedFileObservation(
                    path=rel_path,
                    change_kind=change_kind,
                    before_digest=before_digest,
                    after_digest=after_digest,
                    is_instruction_file=_is_instruction_file(rel_path),
                    is_source_file=_is_source_file(rel_path),
                    is_manifest_file=_is_manifest_file(rel_path),
                    is_schema_file=_is_schema_file(rel_path),
                    is_test_file=_is_test_file(rel_path),
                )
            )

        return observations

    def compute_stale_capsules(
        self, changes: list[ChangedFileObservation], existing_capsules: list[dict]
    ) -> list[StaleAnnotation]:
        if not changes:
            return []

        now = datetime.now(UTC)
        stale: list[StaleAnnotation] = []
        seen_ids: set[str] = set()

        for obs in changes:
            if obs.is_source_file or obs.is_test_file:
                capsule_id = _module_capsule_id(obs.path)
                if capsule_id not in seen_ids:
                    seen_ids.add(capsule_id)
                    stale.append(
                        StaleAnnotation(
                            capsule_id=capsule_id,
                            stale_reason="source_file_changed",
                            affected_paths=[obs.path],
                            stale_since=now,
                        )
                    )
                    continue

                existing = next((s for s in stale if s.capsule_id == capsule_id), None)
                if existing is not None:
                    existing.affected_paths.append(obs.path)

            if obs.is_instruction_file:
                for capsule in existing_capsules:
                    capsule_id = capsule.get("capsule_id", "")
                    if not capsule_id or capsule_id in seen_ids:
                        continue
                    scope_root = capsule.get("scope_root", "")
                    if _path_in_scope(obs.path, scope_root):
                        seen_ids.add(capsule_id)
                        stale.append(
                            StaleAnnotation(
                                capsule_id=capsule_id,
                                stale_reason="instruction_changed",
                                affected_paths=[obs.path],
                                stale_since=now,
                            )
                        )

            if obs.is_schema_file:
                capsule_id = _schema_capsule_id(obs.path)
                if capsule_id not in seen_ids:
                    seen_ids.add(capsule_id)
                    stale.append(
                        StaleAnnotation(
                            capsule_id=capsule_id,
                            stale_reason="schema_changed",
                            affected_paths=[obs.path],
                            stale_since=now,
                        )
                    )

            if obs.is_manifest_file:
                has_dep_stale = any(
                    s.stale_reason == "dependency_changed" for s in stale
                )
                if not has_dep_stale:
                    global_id = "global"
                    stale.append(
                        StaleAnnotation(
                            capsule_id=global_id,
                            stale_reason="dependency_changed",
                            affected_paths=[obs.path],
                            stale_since=now,
                        )
                    )
                else:
                    dep_stale = next(
                        s for s in stale if s.stale_reason == "dependency_changed"
                    )
                    dep_stale.affected_paths.append(obs.path)

        return stale

    def refresh_context(
        self,
        release: RepositoryContextRelease,
        changed_files: list[ChangedFileObservation],
        existing_index: StructuralIndex | None = None,
    ) -> IncrementalContextUpdate:
        release = release.model_copy(deep=True)
        release.released_at = datetime.now(UTC)

        reindexed_modules = 0
        instructions_changed = False
        dependencies_changed = False
        schemas_changed = False

        for obs in changed_files:
            if obs.is_instruction_file:
                instructions_changed = True
            if obs.is_manifest_file:
                dependencies_changed = True
            if obs.is_schema_file:
                schemas_changed = True

        if instructions_changed:
            try:
                instructions = discover_instructions_with_content(
                    release.repository_root
                )
                scope_collection = build_scope_map(instructions)
                release.instruction_map_digest = _build_instruction_digest(
                    scope_collection, release.repository_root
                )
            except Exception as exc:
                logger.warning("Instruction refresh failed: %s", exc)

        source_paths = [Path(obs.path) for obs in changed_files if obs.is_source_file]
        if source_paths and existing_index is not None:
            try:
                refreshed = self._indexer.refresh_index(existing_index, source_paths)
                reindexed_modules = _count_refreshed(
                    existing_index, refreshed, source_paths
                )
                release.structural_index_digest = _build_structural_digest(refreshed)
                release.provenance["structural_index"] = (
                    f"sha256:{refreshed.index_digest}"
                )
            except Exception as exc:
                logger.warning("Structural index refresh failed: %s", exc)

        if dependencies_changed:
            try:
                release.dependency_risk_summary = _rebuild_dependency_summary(
                    release.repository_root
                )
            except Exception as exc:
                logger.warning("Dependency refresh failed: %s", exc)

        release.content_digest = compute_digest(release)

        update = IncrementalContextUpdate(
            release=release,
            changed_files=changed_files,
            stale_capsules=[],
            reindexed_modules=reindexed_modules,
            instructions_changed=instructions_changed,
            dependencies_changed=dependencies_changed,
            schemas_changed=schemas_changed,
        )

        canonical = json.dumps(
            update.model_dump(mode="json", exclude={"update_digest"}),
            sort_keys=True,
            ensure_ascii=False,
        )
        update.update_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return update

    def is_fresh(
        self, release: RepositoryContextRelease, observed_head_sha: str
    ) -> bool:
        head_digest = release.provenance.get("head_sha", "")
        if head_digest and head_digest == observed_head_sha:
            return True
        if (
            release.quarantine is not None
            and release.quarantine.source_head_sha == observed_head_sha
        ):
            return True
        return False


def _classify_change_kind(
    abs_path: Path, rel_path: str, root: Path, previous_head_sha: str
) -> str:
    if abs_path.is_file():
        existed_before = _git_cat_file_check(root, previous_head_sha, rel_path)
        return "modified" if existed_before else "added"
    existed_before = _git_cat_file_check(root, previous_head_sha, rel_path)
    return "deleted" if existed_before else "added"


def _git_cat_file_check(root: Path, sha: str, rel_path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{sha}:{rel_path}"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _git_show_digest(root: Path, sha: str, rel_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{sha}:{rel_path}"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        return hashlib.sha256(result.stdout).hexdigest()
    except (subprocess.TimeoutExpired, OSError):
        return None


def _file_digest(filepath: Path) -> str | None:
    try:
        return hashlib.sha256(filepath.read_bytes()).hexdigest()
    except OSError:
        return None


def _is_instruction_file(rel_path: str) -> bool:
    filename = Path(rel_path).name
    if filename in _INSTRUCTION_FILE_NAMES:
        return True
    for pattern in _RULE_DIR_PATTERNS:
        if rel_path.startswith(pattern):
            return True
    if rel_path.startswith(".github/workflows/"):
        return True
    return False


def _is_source_file(rel_path: str) -> bool:
    if _is_test_file(rel_path) or _is_schema_file(rel_path):
        return False
    suffix = Path(rel_path).suffix
    return suffix in _SOURCE_EXTENSIONS


def _is_manifest_file(rel_path: str) -> bool:
    filename = Path(rel_path).name
    if filename in _MANIFEST_FILE_NAMES:
        return True
    if rel_path.endswith(".lock") and not rel_path.startswith("docs/"):
        return True
    return False


def _is_schema_file(rel_path: str) -> bool:
    return rel_path.startswith("docs/schemas/") and rel_path.endswith(".json")


def _is_test_file(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if len(parts) >= _MIN_PATH_PARTS_FOR_TEST_DIR and parts[0] == "tests":
        return True
    filename = Path(rel_path).name
    return filename.startswith("test_") or filename.endswith("_test.py")


def _module_capsule_id(rel_path: str) -> str:
    if rel_path.startswith("tests/"):
        return f"test:{rel_path}"
    return f"source:{rel_path}"


def _schema_capsule_id(rel_path: str) -> str:
    return f"schema:{rel_path}"


def _path_in_scope(instruction_path: str, scope_root: str) -> bool:
    if scope_root in _GLOBAL_SCOPE_ROOTS:
        return True
    scope_dir = scope_root.rstrip("/")
    return instruction_path.startswith(scope_dir + "/") or instruction_path == scope_dir


def _count_refreshed(
    old_index: StructuralIndex, new_index: StructuralIndex, changed_paths: list[Path]
) -> int:
    changed_rel = {str(p) for p in changed_paths}
    python_key = StructuralIndexKind.PYTHON.value
    old_modules = old_index.language_indices.get(python_key, [])
    old_paths = {m.path for m in old_modules}
    new_modules = new_index.language_indices.get(python_key, [])
    new_paths = {m.path for m in new_modules}
    reindexed = changed_rel & (old_paths | new_paths)
    return len(reindexed)


def _build_instruction_digest(
    scope_collection: InstructionScopeCollection, repo_root: Path
) -> InstructionMapDigest:

    raw = {
        "files": [
            {
                "path": inst.scope.path,
                "kind": inst.scope.kind,
                "scope_root": inst.scope.scope_root,
                "scope_depth": inst.scope.scope_depth,
                "content_sha256": inst.content_sha256,
            }
            for inst in scope_collection.instruction_files
        ],
        "scope_map": scope_collection.scope_map,
        "conflicts": [
            {"a": c[0], "b": c[1], "reason": c[2]} for c in scope_collection.conflicts
        ],
    }
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    kind_counts: dict[str, int] = {}
    for inst in scope_collection.instruction_files:
        kind = inst.scope.kind
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    return InstructionMapDigest(
        instruction_file_count=len(scope_collection.instruction_files),
        nested_instruction_count=sum(
            1 for inst in scope_collection.instruction_files if inst.nested_instructions
        ),
        rule_directory_count=sum(
            1
            for inst in scope_collection.instruction_files
            if any(inst.scope.path.startswith(p) for p in _RULE_DIR_PATTERNS)
        ),
        scope_conflicts=len(scope_collection.conflicts),
        top_level_kinds=kind_counts,
        map_sha256=digest,
    )


def _build_structural_digest(index: StructuralIndex) -> StructuralIndexDigest:

    python_key = StructuralIndexKind.PYTHON.value
    modules = index.language_indices.get(python_key, [])

    language_counts: dict[str, int] = {}
    for lang, mods in index.language_indices.items():
        language_counts[lang] = len(mods)

    exported_count = sum(sum(1 for s in m.symbols if s.is_exported) for m in modules)

    return StructuralIndexDigest(
        module_count=index.module_count,
        symbol_count=index.symbol_count,
        exported_symbol_count=exported_count,
        language_counts=language_counts,
        parser_errors=len(index.parser_errors),
        index_digest=index.index_digest,
    )


def _rebuild_dependency_summary(repo_root: Path) -> DependencyRiskSummary | None:
    from rig_relay.digestion.dependency_classifier import (
        DependencyClassifier,
        DependencyRisk,
    )
    from rig_relay.digestion.ecosystem_detector import detect_ecosystems

    classifier = DependencyClassifier()
    try:
        ecosystems = detect_ecosystems(repo_root)
        classified = classifier.classify_dependencies(repo_root, ecosystems)
    except Exception:
        return None

    risk_count = sum(
        1 for d in classified.dependencies if d.risk != DependencyRisk.NONE
    )
    prod_count = sum(1 for d in classified.dependencies if not d.is_dev)
    dev_count = sum(1 for d in classified.dependencies if d.is_dev)
    managers = list({
        d.package_manager.value for d in classified.dependencies if d.package_manager
    })

    return DependencyRiskSummary(
        total_dependencies=len(classified.dependencies),
        production_count=prod_count,
        dev_count=dev_count,
        risk_count=risk_count,
        package_managers=managers,
        classification_digest=classified.classification_digest,
    )


__all__ = [
    "ChangedFileObservation",
    "IncrementalContextCompiler",
    "IncrementalContextUpdate",
    "StaleAnnotation",
]

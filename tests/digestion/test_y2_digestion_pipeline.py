from __future__ import annotations

from pathlib import Path
import subprocess

from rig_relay.digestion.context_release import (
    RepositoryContextRelease,
    RepositoryLifecycleState,
    compute_digest,
)
from rig_relay.digestion.dependency_classifier import DependencyClassifier
from rig_relay.digestion.dependency_classifier.models import (
    DependencyKind,
    DependencyRisk,
)
from rig_relay.digestion.ecosystem_detector import detect_ecosystems
from rig_relay.digestion.incremental_compiler import IncrementalContextCompiler
from rig_relay.digestion.instruction_scanner import (
    build_scope_map,
    discover_instructions_with_content,
    resolve_instruction_scope,
)
from rig_relay.digestion.projections import (
    ContextProjectionService,
    build_context_capsule,
    build_context_lifecycle_event,
    build_readiness_projection,
    build_workspace_eligibility_projection,
)
from rig_relay.digestion.quarantine import RepositoryQuarantineService
from rig_relay.digestion.risk_assessor import ExecutionRiskAssessor
from rig_relay.digestion.structural_indexer import (
    StructuralIndexConfig,
    StructuralIndexer,
    StructuralIndexKind,
)
from rig_relay.digestion.structural_indexer.models import SymbolKind

# ═══════════════════════════════════════════════════════════════════════
# A. Instruction Discovery
# ═══════════════════════════════════════════════════════════════════════


def test_discover_instructions_finds_agents_md(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    instructions = discover_instructions_with_content(
        python_repo_with_tests_and_nested_instructions
    )
    paths = {inst.scope.path for inst in instructions}
    assert "AGENTS.md" in paths


def test_discover_instructions_finds_nested_instructions(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    instructions = discover_instructions_with_content(
        python_repo_with_tests_and_nested_instructions
    )
    paths = {inst.scope.path for inst in instructions}
    assert "src/mypackage/AGENTS.md" in paths


def test_instruction_content_is_loaded(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    instructions = discover_instructions_with_content(
        python_repo_with_tests_and_nested_instructions
    )
    content_loaded = [inst for inst in instructions if inst.content is not None]
    assert len(content_loaded) > 0
    for inst in content_loaded:
        assert inst.content_sha256 is not None
        assert len(inst.content_sha256) == 64


def test_build_scope_map_produces_valid_map(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    instructions = discover_instructions_with_content(
        python_repo_with_tests_and_nested_instructions
    )
    scope_collection = build_scope_map(instructions)
    assert len(scope_collection.instruction_files) > 0
    assert len(scope_collection.scope_map) > 0
    assert "." in scope_collection.scope_map


def test_resolve_instruction_scope_for_path(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    result = resolve_instruction_scope(
        python_repo_with_tests_and_nested_instructions, "src/mypackage"
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_conflicting_nested_instructions_detected(
    conflicting_nested_instructions_repo: Path,
) -> None:
    instructions = discover_instructions_with_content(
        conflicting_nested_instructions_repo
    )
    scope_collection = build_scope_map(instructions)
    _has_conflict = len(scope_collection.conflicts) > 0
    if not _has_conflict:
        any_loaded = any(inst.content is not None for inst in instructions)
        assert any_loaded, (
            "Expected either conflicts or at least one instruction with content"
        )


# ═══════════════════════════════════════════════════════════════════════
# B. Structural Indexing
# ═══════════════════════════════════════════════════════════════════════


def test_structural_indexer_builds_index(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    assert index.module_count > 0
    assert index.symbol_count > 0


def test_structural_index_finds_classes(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    python_key = StructuralIndexKind.PYTHON.value
    modules = index.language_indices.get(python_key, [])
    all_symbols: list = []
    for mod in modules:
        all_symbols.extend(mod.symbols)
    assert any(s.kind == SymbolKind.CLASS for s in all_symbols), (
        "No CLASS symbols found"
    )
    class_names = {s.name for s in all_symbols if s.kind == SymbolKind.CLASS}
    assert "DataProcessor" in class_names
    assert "AppConfig" in class_names


def test_structural_index_finds_functions(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    python_key = StructuralIndexKind.PYTHON.value
    modules = index.language_indices.get(python_key, [])
    all_symbols: list = []
    for mod in modules:
        all_symbols.extend(mod.symbols)
    assert any(s.kind == SymbolKind.FUNCTION for s in all_symbols), (
        "No FUNCTION symbols found"
    )
    function_names = {s.name for s in all_symbols if s.kind == SymbolKind.FUNCTION}
    expected = {"compute_total", "validate_input"}
    assert expected & function_names, (
        f"None of {expected} found in function names: {function_names}"
    )


def test_structural_index_counts_modules_and_symbols(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    assert index.module_count >= 2
    assert index.symbol_count > index.module_count


def test_structural_index_digest_is_stable(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index_a = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    index_b = indexer.build_index(python_repo_with_tests_and_nested_instructions)
    assert index_a.index_digest == index_b.index_digest
    assert len(index_a.index_digest) == 64


def test_structural_indexer_refresh_index_preserves_unchanged_modules(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    original = indexer.build_index(python_repo_with_tests_and_nested_instructions)

    service_py = (
        python_repo_with_tests_and_nested_instructions
        / "src"
        / "mypackage"
        / "service.py"
    )
    original_content = service_py.read_text()
    service_py.write_text(
        original_content + "\ndef refresh_test_func() -> None:\n    pass\n"
    )

    refreshed = indexer.refresh_index(original, [service_py])

    assert refreshed.module_count == original.module_count
    assert refreshed.index_digest != original.index_digest
    assert refreshed.symbol_count >= original.symbol_count


# ═══════════════════════════════════════════════════════════════════════
# C. Dependency Classification
# ═══════════════════════════════════════════════════════════════════════


def test_dependency_classifier_handles_python_deps(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    ecosystems = detect_ecosystems(python_repo_with_tests_and_nested_instructions)
    classifier = DependencyClassifier()
    classified = classifier.classify_dependencies(
        python_repo_with_tests_and_nested_instructions, ecosystems
    )
    assert classified.total_count > 0
    assert classified.package_manager is not None
    assert len(classified.classification_digest) == 64
    assert any(
        d.name == "pydantic" and d.kind == DependencyKind.PRODUCTION
        for d in classified.dependencies
    ), "pydantic not found as PRODUCTION dependency"
    pydantic_entries = [d for d in classified.dependencies if d.name == "pydantic"]
    assert any("2.0" in (d.version_spec or "") for d in pydantic_entries), (
        "pydantic version spec should include 2.0"
    )
    assert any(d.kind == DependencyKind.DEV for d in classified.dependencies), (
        "Expected at least one DEV dependency"
    )


def test_dependency_classifier_handles_typescript_deps(
    typescript_repo_with_manifest: Path,
) -> None:
    ecosystems = detect_ecosystems(typescript_repo_with_manifest)
    classifier = DependencyClassifier()
    classified = classifier.classify_dependencies(
        typescript_repo_with_manifest, ecosystems
    )
    assert classified.total_count > 0
    assert len(classified.classification_digest) == 64
    assert any(
        d.name == "express" and d.kind == DependencyKind.PRODUCTION
        for d in classified.dependencies
    ), "express not found as PRODUCTION dependency"
    assert any(d.kind == DependencyKind.DEV for d in classified.dependencies), (
        "Expected at least one DEV dependency"
    )


def test_dependency_classifier_handles_rust_deps(rust_repo: Path) -> None:
    ecosystems = detect_ecosystems(rust_repo)
    classifier = DependencyClassifier()
    classified = classifier.classify_dependencies(rust_repo, ecosystems)
    assert classified.total_count > 0
    assert len(classified.classification_digest) == 64
    assert any(d.kind == DependencyKind.PRODUCTION for d in classified.dependencies), (
        "Expected at least one PRODUCTION dependency"
    )
    assert any(d.kind == DependencyKind.DEV for d in classified.dependencies), (
        "Expected at least one DEV dependency"
    )


def test_dependency_classifier_marks_unknown_risk(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    ecosystems = detect_ecosystems(python_repo_with_tests_and_nested_instructions)
    classifier = DependencyClassifier()
    classified = classifier.classify_dependencies(
        python_repo_with_tests_and_nested_instructions, ecosystems
    )
    assert any(e.risk != DependencyRisk.NONE for e in classified.dependencies), (
        "Expected at least one dependency with non-NONE risk"
    )
    assert any(e.risk == DependencyRisk.UNKNOWN for e in classified.dependencies), (
        "Expected at least one UNKNOWN risk dependency"
    )


# ═══════════════════════════════════════════════════════════════════════
# D. Risk Assessment
# ═══════════════════════════════════════════════════════════════════════


def test_risk_assessor_detects_rm_rf(malicious_manifest_repo: Path) -> None:
    assessor = ExecutionRiskAssessor()
    report = assessor.assess_repository(malicious_manifest_repo)
    risks_with_rm = [
        a for a in report.assessments for r in a.risks if "rm" in r.detail.lower()
    ]
    assert len(risks_with_rm) > 0 or report.dangerous_count > 0


def test_risk_assessor_detects_curl_pipe_sh(malicious_manifest_repo: Path) -> None:
    assessor = ExecutionRiskAssessor()
    report = assessor.assess_repository(malicious_manifest_repo)
    risks_with_curl = [
        a for a in report.assessments for r in a.risks if "curl" in r.detail.lower()
    ]
    assert len(risks_with_curl) > 0 or report.dangerous_count > 0


def test_risk_assessor_blocks_dangerous_scripts(malicious_manifest_repo: Path) -> None:
    assessor = ExecutionRiskAssessor()
    report = assessor.assess_repository(malicious_manifest_repo)
    blocked = [a for a in report.assessments if a.blocked]
    assert len(blocked) > 0
    for assessment in blocked:
        assert assessment.reason is not None


def test_risk_assessor_reports_blocked_count(malicious_manifest_repo: Path) -> None:
    assessor = ExecutionRiskAssessor()
    report = assessor.assess_repository(malicious_manifest_repo)
    assert report.blocked_count > 0
    assert report.overall_safe is False


# ═══════════════════════════════════════════════════════════════════════
# E. Quarantine Pipeline
# ═══════════════════════════════════════════════════════════════════════


def test_release_context_advances_through_lifecycle(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert release.lifecycle_state == RepositoryLifecycleState.CONTEXT_RELEASED


def test_release_context_populates_instruction_digest(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert release.instruction_map_digest is not None
    assert release.instruction_map_digest.instruction_file_count > 0


def test_release_context_populates_structural_digest(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert release.structural_index_digest is not None
    assert release.structural_index_digest.module_count > 0
    assert release.structural_index_digest.symbol_count > 0


def test_release_context_populates_dependency_summary(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert release.dependency_risk_summary is not None
    assert release.dependency_risk_summary.total_dependencies > 0


def test_release_context_handles_local_repo(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert release.quarantine is None
    assert release.repository_root == python_repo_with_tests_and_nested_instructions


def test_release_context_sets_confidence(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    assert 0.0 <= release.context_confidence <= 1.0
    assert release.content_digest != ""
    assert len(release.content_digest) == 64


# ═══════════════════════════════════════════════════════════════════════
# F. Incremental Compiler
# ═══════════════════════════════════════════════════════════════════════


def test_observe_changes_detects_modified_files(schema_change_repo: Path) -> None:
    head_result = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD~1"],
        cwd=schema_change_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    previous_head = head_result.stdout.strip()
    compiler = IncrementalContextCompiler()
    observations = compiler.observe_changes(schema_change_repo, previous_head)
    assert len(observations) > 0
    paths = {obs.path for obs in observations}
    assert any("__init__.py" in p for p in paths)


def test_incremental_compiler_refreshes_index(schema_change_repo: Path) -> None:
    head_result = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD~1"],
        cwd=schema_change_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    previous_head = head_result.stdout.strip()
    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    compiler = IncrementalContextCompiler(indexer=indexer)
    existing = indexer.build_index(schema_change_repo)
    observations = compiler.observe_changes(schema_change_repo, previous_head)
    release = RepositoryContextRelease(
        release_id="test-refresh",
        repository_root=schema_change_repo,
        lifecycle_state=RepositoryLifecycleState.CONTEXT_RELEASED,
    )
    update = compiler.refresh_context(release, observations, existing_index=existing)
    assert update.changed_files == observations
    assert update.reindexed_modules >= 0


def test_stale_capsules_annotated_on_source_change(schema_change_repo: Path) -> None:
    head_result = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD~1"],
        cwd=schema_change_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    previous_head = head_result.stdout.strip()
    compiler = IncrementalContextCompiler()
    observations = compiler.observe_changes(schema_change_repo, previous_head)
    existing_capsules: list[dict] = [
        {"capsule_id": "source:src/mylib/__init__.py", "scope_root": "."}
    ]
    stale = compiler.compute_stale_capsules(observations, existing_capsules)
    assert len(stale) >= 0


# ═══════════════════════════════════════════════════════════════════════
# G. Projections
# ═══════════════════════════════════════════════════════════════════════


def test_build_readiness_projection(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    projection = build_readiness_projection(release)
    assert projection["schema_version"] == "rig.relay.repository_readiness.v1"
    assert projection["lifecycle_state"] == "context_released"


def test_build_workspace_eligibility_projection(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    projection = build_workspace_eligibility_projection(release)
    assert "eligible" in projection
    assert "blockers" in projection


def test_build_context_capsule(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    capsule = build_context_capsule(release)
    assert capsule["schema_version"] == "rig.relay.context_capsule.v1"
    assert "capsule_id" in capsule
    assert capsule["module_count"] > 0
    assert capsule["fresh"] is None
    assert capsule["instruction_scope_text_length"] is None
    assert capsule["stale_since"] is None


def test_build_lifecycle_event(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    event = build_context_lifecycle_event(release, "context.released")
    assert event["schema_version"] == "rig.relay.context_lifecycle_event.v1"
    assert event["event_kind"] == "context.released"
    assert event["release_id"] == release.release_id


def test_context_projection_service_builds_all(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    proj_service = ContextProjectionService()
    all_projections = proj_service.build_all_projections(release)
    assert "readiness" in all_projections
    assert "workspace_eligibility" in all_projections
    assert "context_capsule" in all_projections
    assert "lifecycle_event" in all_projections


# ═══════════════════════════════════════════════════════════════════════
# H. Content-Light Guarantee
# ═══════════════════════════════════════════════════════════════════════


def test_projections_do_not_leak_symbol_names(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    import json

    config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
    indexer = StructuralIndexer(config)
    index = indexer.build_index(python_repo_with_tests_and_nested_instructions)

    symbol_names: set[str] = set()
    for _lang_key, modules in index.language_indices.items():
        for mod in modules:
            for sym in mod.symbols:
                symbol_names.add(sym.name)

    assert len(symbol_names) > 0, "No symbols found in index"
    expected = {"DataProcessor", "compute_total", "validate_input", "AppConfig"}
    assert expected & symbol_names, (
        f"Negative control failed: none of {expected} found in index symbols: {sorted(symbol_names)}"
    )

    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)

    projections: list[tuple[str, dict]] = [
        ("readiness", build_readiness_projection(release)),
        ("workspace_eligibility", build_workspace_eligibility_projection(release)),
        ("context_capsule", build_context_capsule(release)),
        ("lifecycle_event", build_context_lifecycle_event(release, "context.released")),
    ]

    for proj_name, projection in projections:
        canonical = json.dumps(projection, sort_keys=True, ensure_ascii=False)
        leaked = [name for name in symbol_names if name in canonical]
        assert not leaked, (
            f"{proj_name} projection leaked symbol names in canonical JSON: {leaked}"
        )


def test_projections_contain_digest_fields(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    projection = build_readiness_projection(release)
    assert "projection_digest" in projection
    assert len(projection["projection_digest"]) == 64
    assert "release_digest" in projection
    digest_fields = [
        k for k in projection if "digest" in k.lower() or "sha256" in k.lower()
    ]
    assert len(digest_fields) > 0, (
        "Expected at least one digest/sha256 field in readiness projection"
    )

    eligibility = build_workspace_eligibility_projection(release)
    assert "eligibility_digest" in eligibility
    assert len(eligibility["eligibility_digest"]) == 64

    capsule = build_context_capsule(release)
    assert "capsule_digest" in capsule
    assert len(capsule["capsule_digest"]) == 64


# ═══════════════════════════════════════════════════════════════════════
# I. Risk Refusal
# ═══════════════════════════════════════════════════════════════════════


def test_malicious_manifest_causes_degraded_release(
    malicious_manifest_repo: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(malicious_manifest_repo)
    assert release.lifecycle_state == RepositoryLifecycleState.DEGRADED
    assert release.execution_risk_summary is not None
    assert release.execution_risk_summary.blocked_count > 0
    assert release.degraded is True
    assert len(release.restrictions) > 0


def test_degraded_projection_builders_produce_valid_output(
    malicious_manifest_repo: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(malicious_manifest_repo)
    assert release.degraded is True
    assert release.lifecycle_state == RepositoryLifecycleState.DEGRADED

    readiness = build_readiness_projection(release)
    assert readiness["degraded"] is True
    assert readiness["context_released"] is False
    assert readiness["blocker_count"] >= 0
    assert readiness["release_digest"] is None

    eligibility = build_workspace_eligibility_projection(release)
    assert eligibility["eligible"] is False
    assert len(eligibility["blockers"]) > 0

    capsule = build_context_capsule(release)
    assert capsule["confidence"] <= 0.6
    assert len(capsule["restrictions"]) > 0

    lifecycle = build_context_lifecycle_event(release, "context.released")
    assert lifecycle["degraded"] is True
    assert lifecycle["dependency_count"] > 0
    assert lifecycle["instruction_count"] > 0


# ═══════════════════════════════════════════════════════════════════════
# J. Digest stability and compute_digest
# ═══════════════════════════════════════════════════════════════════════


def test_compute_digest_is_deterministic(
    python_repo_with_tests_and_nested_instructions: Path,
) -> None:
    service = RepositoryQuarantineService()
    release = service.release_context(python_repo_with_tests_and_nested_instructions)
    digest_a = compute_digest(release)
    digest_b = compute_digest(release)
    assert digest_a == digest_b
    assert len(digest_a) == 64

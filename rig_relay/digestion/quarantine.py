from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
import stat
import subprocess
import uuid

from rig_relay.core.logger import logger
from rig_relay.digestion.context_release import (
    DependencyRiskSummary,
    ExecutionRiskSummary,
    InstructionMapDigest,
    QuarantineInfo,
    RepositoryContextRelease,
    RepositoryLifecycleState,
    SafeValidationResult,
    StructuralIndexDigest,
    WorkspaceEligibility,
    compute_digest,
)
from rig_relay.digestion.dependency_classifier import DependencyClassifier
from rig_relay.digestion.ecosystem_detector import detect_ecosystems
from rig_relay.digestion.identity import (
    resolve_git_branch,
    resolve_git_head_sha,
    resolve_git_remotes,
    resolve_git_worktree_root,
)
from rig_relay.digestion.instruction_scanner import (
    build_scope_map,
    discover_instructions_with_content,
)
from rig_relay.digestion.models import OpenedRepository, SafetyClassification
from rig_relay.digestion.risk_assessor import ExecutionRiskAssessor, RiskLevel
from rig_relay.digestion.structural_indexer import (
    StructuralIndexConfig,
    StructuralIndexer,
    StructuralIndexKind,
)
from rig_relay.digestion.topology_mapper import map_topology
from rig_relay.digestion.validation_detector import detect_validation_candidates


def _derive_stable_dir_name(remote_url: str) -> str:
    m = re.search(r"/([^/]+?)(?:\.git)?$", remote_url.rstrip("/"))
    if m:
        return m.group(1)
    return hashlib.sha256(remote_url.encode()).hexdigest()[:12]


def _make_read_only(root: Path) -> None:
    read_only_mask = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
        for name in dirnames + filenames:
            path = dirpath / name
            if ".git" in path.parts:
                continue
            if path.is_symlink():
                continue
            try:
                current = path.stat().st_mode
                if path.is_dir():
                    path.chmod(
                        current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
                        | stat.S_IXUSR
                        | stat.S_IXGRP
                        | stat.S_IXOTH
                    )
                else:
                    path.chmod(read_only_mask)
            except OSError as exc:
                logger.warning("chmod failed for %s: %s", path, exc)


def _run_subprocess(
    cmd: list[str], cwd: Path, timeout: int = 120
) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )
    return result.returncode, result.stdout, result.stderr


class RepositoryQuarantineService:
    def quarantine_remote(
        self, remote_url: str, quarantine_root: Path, branch: str | None = None
    ) -> tuple[Path, OpenedRepository]:
        dir_name = _derive_stable_dir_name(remote_url)
        target_dir = quarantine_root / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        clone_args = [
            "git",
            "clone",
            "--depth",
            "1",
            "--no-checkout",
            remote_url,
            str(target_dir),
        ]
        logger.info(
            "Cloning remote url=%s into quarantine path=%s", remote_url, target_dir
        )
        returncode, stdout, stderr = _run_subprocess(clone_args, quarantine_root)
        if returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr}")

        checkout_args = ["git", "checkout", "HEAD"]
        logger.info("Checking out HEAD in quarantine path=%s", target_dir)
        returncode, stdout, stderr = _run_subprocess(checkout_args, target_dir)
        if returncode != 0:
            raise RuntimeError(f"git checkout failed: {stderr}")

        if branch is not None:
            checkout_branch_args = ["git", "checkout", branch]
            logger.info(
                "Checking out branch=%s in quarantine path=%s", branch, target_dir
            )
            returncode, stdout, stderr = _run_subprocess(
                checkout_branch_args, target_dir
            )
            if returncode != 0:
                logger.warning(
                    "Failed to checkout branch=%s, staying on HEAD: %s", branch, stderr
                )

        logger.info("Setting quarantine path=%s to read-only", target_dir)
        _make_read_only(target_dir)

        git_root = resolve_git_worktree_root(target_dir)
        if git_root is None:
            git_root = target_dir
        resolved_branch = resolve_git_branch(git_root)
        head_sha = resolve_git_head_sha(git_root) or ""
        remotes = resolve_git_remotes(git_root)

        repo = OpenedRepository(
            root_path=str(git_root),
            git_root=str(git_root),
            is_git_repo=True,
            branch=resolved_branch,
            head_sha=head_sha,
            remotes=remotes,
            is_github_backed=any(r.get("host") == "github.com" for r in remotes),
            is_local_only=not bool(remotes),
        )

        logger.info(
            "Quarantine complete path=%s head_sha=%s branch=%s",
            target_dir,
            head_sha,
            resolved_branch,
        )
        return target_dir, repo

    def discover_instructions(
        self, release: RepositoryContextRelease
    ) -> RepositoryContextRelease:
        instructions = discover_instructions_with_content(release.repository_root)
        scope_collection = build_scope_map(instructions)

        instruction_count = len(scope_collection.instruction_files)
        nested_count = sum(
            len(inst.nested_instructions) for inst in scope_collection.instruction_files
        )
        top_kinds: dict[str, int] = {}
        for inst in scope_collection.instruction_files:
            kind = inst.scope.kind
            top_kinds[kind] = top_kinds.get(kind, 0) + 1

        map_json = scope_collection.model_dump_json()
        map_digest = hashlib.sha256(map_json.encode()).hexdigest()

        release.instruction_map_digest = InstructionMapDigest(
            instruction_file_count=instruction_count,
            nested_instruction_count=nested_count,
            rule_directory_count=0,
            scope_conflicts=len(scope_collection.conflicts),
            top_level_kinds=top_kinds,
            map_sha256=map_digest,
        )
        release.lifecycle_state = RepositoryLifecycleState.INSTRUCTIONS_DISCOVERED
        logger.info(
            "Instructions discovered count=%s nested=%s conflicts=%s",
            instruction_count,
            nested_count,
            len(scope_collection.conflicts),
        )
        return release

    def build_structural_index(
        self,
        release: RepositoryContextRelease,
        config: StructuralIndexConfig | None = None,
    ) -> RepositoryContextRelease:
        if config is None:
            config = StructuralIndexConfig(parsers=[StructuralIndexKind.PYTHON])
        indexer = StructuralIndexer(config)
        index = indexer.build_index(release.repository_root)

        lang_counts: dict[str, int] = {}
        for lang_key, modules in index.language_indices.items():
            lang_counts[lang_key] = len(modules)

        release.structural_index_digest = StructuralIndexDigest(
            module_count=index.module_count,
            symbol_count=index.symbol_count,
            exported_symbol_count=index.exported_symbol_count,
            language_counts=lang_counts,
            parser_errors=len(index.parser_errors),
            index_digest=index.index_digest,
        )
        release.lifecycle_state = RepositoryLifecycleState.STRUCTURE_INDEXED
        logger.info(
            "Structure indexed modules=%s symbols=%s errors=%s",
            index.module_count,
            index.symbol_count,
            len(index.parser_errors),
        )
        return release

    def classify_dependencies(
        self, release: RepositoryContextRelease
    ) -> RepositoryContextRelease:
        ecosystems = detect_ecosystems(release.repository_root)
        classifier = DependencyClassifier()
        classified = classifier.classify_dependencies(
            release.repository_root, ecosystems
        )

        pm_kinds = (
            [classified.package_manager.value] if classified.package_manager else []
        )
        release.dependency_risk_summary = DependencyRiskSummary(
            total_dependencies=classified.total_count,
            production_count=classified.production_count,
            dev_count=classified.dev_count,
            risk_count=classified.risk_count,
            package_managers=pm_kinds,
            classification_digest=classified.classification_digest,
        )
        release.lifecycle_state = RepositoryLifecycleState.DEPENDENCIES_CLASSIFIED
        logger.info(
            "Dependencies classified total=%s production=%s risk=%s",
            classified.total_count,
            classified.production_count,
            classified.risk_count,
        )
        return release

    def assess_execution_risks(
        self, release: RepositoryContextRelease
    ) -> RepositoryContextRelease:
        assessor = ExecutionRiskAssessor()
        report = assessor.assess_repository(release.repository_root)

        blocked_count = report.blocked_count
        dangerous_count = report.dangerous_count
        safe_count = sum(
            1 for a in report.assessments if a.risk_level == RiskLevel.SAFE
        )

        for assessment in report.assessments:
            if assessment.blocked:
                release.restrictions.append(
                    f"Blocked: {assessment.script_name} — {assessment.reason}"
                )

        if not report.overall_safe:
            release.degraded = True
            release.degradation_reasons.append(
                "Execution risk assessment found dangerous or blocked scripts"
            )

        release.execution_risk_summary = ExecutionRiskSummary(
            total_scripts_assessed=len(report.assessments),
            blocked_count=blocked_count,
            dangerous_count=dangerous_count,
            safe_count=safe_count,
            report_digest=report.report_digest,
        )
        release.execution_risk_report = report
        release.lifecycle_state = RepositoryLifecycleState.EXECUTION_RISKS_REVIEWED
        logger.info(
            "Execution risks assessed total=%s blocked=%s dangerous=%s safe=%s",
            len(report.assessments),
            blocked_count,
            dangerous_count,
            safe_count,
        )
        return release

    def probe_safe_validation(
        self, release: RepositoryContextRelease
    ) -> RepositoryContextRelease:
        exec_summary = release.execution_risk_summary
        if exec_summary is not None and exec_summary.blocked_count > 0:
            logger.warning(
                "Skipping safe validation probes: %s scripts are blocked",
                exec_summary.blocked_count,
            )
            release.lifecycle_state = RepositoryLifecycleState.SAFE_VALIDATION_PROBED
            return release

        ecosystems = detect_ecosystems(release.repository_root)
        candidates = detect_validation_candidates(release.repository_root, ecosystems)
        assessor = ExecutionRiskAssessor()

        restrictions_set = set(release.restrictions)
        blocked_source_files: set[str] = set()
        if release.execution_risk_report is not None:
            for assessment in release.execution_risk_report.assessments:
                if assessment.blocked:
                    blocked_source_files.add(str(assessment.script_path))

        safe_candidates = []
        for cmd in candidates:
            if cmd.safety_classification != SafetyClassification.READ_ONLY_VALIDATION:
                continue
            risks = assessor._detect_dangerous_patterns(cmd.command, cmd.command)
            risks += assessor._detect_shell_injection(cmd.command, cmd.command)
            blocked = any(
                r.level in {RiskLevel.DANGEROUS, RiskLevel.REJECTED} for r in risks
            )
            if blocked:
                continue
            if cmd.source_file is not None and cmd.source_file in blocked_source_files:
                logger.warning(
                    "Skipping safe validation command=%s from blocked source=%s",
                    cmd.command,
                    cmd.source_file,
                )
                continue
            source_restricted = cmd.source_file is not None and any(
                cmd.source_file in r for r in restrictions_set
            )
            if source_restricted:
                logger.warning(
                    "Skipping safe validation command=%s from restricted source=%s",
                    cmd.command,
                    cmd.source_file,
                )
                continue
            safe_candidates.append(cmd)

        executed_count = 0
        for cmd in safe_candidates[:3]:
            parts = cmd.command.split()
            start = datetime.now(UTC)
            try:
                returncode, stdout, stderr = _run_subprocess(
                    parts, release.repository_root, timeout=120
                )
                latency_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
                combined_output = stdout + stderr
                output_digest = hashlib.sha256(
                    combined_output.encode("utf-8", errors="replace")
                ).hexdigest()
                passed = returncode == 0

                release.safe_validation_results.append(
                    SafeValidationResult(
                        command=cmd.command,
                        exit_code=returncode,
                        output_digest=output_digest,
                        latency_ms=latency_ms,
                        passed=passed,
                    )
                )
                executed_count += 1
                logger.info(
                    "Safe validation probe command=%s exit_code=%s passed=%s",
                    cmd.command,
                    returncode,
                    passed,
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Safe validation probe timed out command=%s", cmd.command
                )
            except Exception as exc:
                logger.warning(
                    "Safe validation probe failed command=%s error=%s", cmd.command, exc
                )

        release.lifecycle_state = RepositoryLifecycleState.SAFE_VALIDATION_PROBED
        logger.info(
            "Safe validation probed candidate_count=%s executed=%s",
            len(safe_candidates),
            executed_count,
        )
        return release

    def compute_workspace_eligibility(
        self, release: RepositoryContextRelease
    ) -> RepositoryContextRelease:
        blockers: list[str] = []

        exec_summary = release.execution_risk_summary
        if exec_summary is not None and exec_summary.blocked_count > 0:
            blockers.append(
                f"{exec_summary.blocked_count} scripts are blocked from execution"
            )

        if release.instruction_map_digest is None:
            blockers.append("No instructions discovered")
        elif release.instruction_map_digest.instruction_file_count == 0:
            blockers.append("No instruction files found")

        if release.structural_index_digest is None:
            blockers.append("Structural index not built")
        elif release.structural_index_digest.module_count == 0:
            blockers.append("No modules indexed")

        if release.dependency_risk_summary is None:
            blockers.append("Dependencies not classified")

        safe_passes = sum(1 for r in release.safe_validation_results if r.passed)
        if safe_passes == 0 and release.safe_validation_results:
            blockers.append("All safe validation probes failed")
        elif not release.safe_validation_results:
            blockers.append("No safe validation probes completed")

        eligible = len(blockers) == 0

        exec_safe = exec_summary is not None and exec_summary.dangerous_count == 0
        if eligible and exec_safe:
            recommended = "managed_write"
        elif eligible and not exec_safe:
            recommended = "read_only"
        elif exec_summary is not None and exec_summary.blocked_count > 0:
            recommended = "read_only"
        else:
            recommended = None

        ecosystems = detect_ecosystems(release.repository_root)
        detected_languages = [e.language for e in ecosystems]
        topology = map_topology(release.repository_root, detected_languages)

        path_policy: dict[str, str] = {}
        for entry in topology:
            kind = entry.kind
            if kind in {"source", "test"}:
                path_policy[entry.name] = "write"
            elif kind in {"docs", "schemas", "scripts"}:
                path_policy[entry.name] = "write"
            elif kind == "config":
                path_policy[entry.name] = "read"
            else:
                path_policy[entry.name] = "read"

        release.workspace_eligibility = WorkspaceEligibility(
            eligible=eligible,
            blockers=blockers,
            recommended_workspace_kind=recommended,
            path_policy=path_policy if path_policy else None,
        )
        release.lifecycle_state = RepositoryLifecycleState.WORKSPACE_ELIGIBLE
        logger.info(
            "Workspace eligibility computed eligible=%s recommended=%s blockers=%s",
            eligible,
            recommended,
            len(blockers),
        )
        return release

    def release_context(
        self, repository_root: Path, remote_url: str | None = None
    ) -> RepositoryContextRelease:
        if remote_url is not None:
            quarantine_root = repository_root
            quarantine_path, repo = self.quarantine_remote(remote_url, quarantine_root)
            actual_root = quarantine_path
            release = RepositoryContextRelease(
                release_id=str(uuid.uuid4()),
                repository_root=actual_root,
                lifecycle_state=RepositoryLifecycleState.CLONED_QUARANTINED,
                quarantine=QuarantineInfo(
                    quarantine_path=quarantine_path,
                    cloned_at=datetime.now(UTC),
                    source_url=remote_url,
                    source_branch=repo.branch,
                    source_head_sha=repo.head_sha or "",
                    is_read_only_intended=True,
                ),
            )
            logger.info(
                "Repository cloned into quarantine path=%s url=%s",
                quarantine_path,
                remote_url,
            )
        else:
            actual_root = repository_root
            release = RepositoryContextRelease(
                release_id=str(uuid.uuid4()),
                repository_root=actual_root,
                lifecycle_state=RepositoryLifecycleState.REMOTE_SELECTED,
            )

        try:
            release = self.discover_instructions(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(f"Instruction discovery failed: {exc}")
            logger.warning("Instruction discovery failed: %s", exc)

        try:
            release = self.build_structural_index(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(f"Structural indexing failed: {exc}")
            logger.warning("Structural indexing failed: %s", exc)

        try:
            release = self.classify_dependencies(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(
                f"Dependency classification failed: {exc}"
            )
            logger.warning("Dependency classification failed: %s", exc)

        try:
            release = self.assess_execution_risks(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(
                f"Execution risk assessment failed: {exc}"
            )
            logger.warning("Execution risk assessment failed: %s", exc)

        try:
            release = self.probe_safe_validation(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(f"Safe validation probing failed: {exc}")
            logger.warning("Safe validation probing failed: %s", exc)

        try:
            release = self.compute_workspace_eligibility(release)
        except Exception as exc:
            release.degraded = True
            release.degradation_reasons.append(
                f"Workspace eligibility computation failed: {exc}"
            )
            logger.warning("Workspace eligibility computation failed: %s", exc)

        release.content_digest = compute_digest(release)
        release.lifecycle_state = (
            RepositoryLifecycleState.DEGRADED
            if release.degraded
            else RepositoryLifecycleState.CONTEXT_RELEASED
        )

        stage_count = 5
        degraded_stages = sum(
            1 for r in release.degradation_reasons if "failed" in r.lower()
        )
        if release.degraded and degraded_stages >= stage_count // 2:
            release.context_confidence = 0.3
        elif release.degraded:
            release.context_confidence = 0.6
        elif (
            release.workspace_eligibility is not None
            and release.workspace_eligibility.eligible
        ):
            release.context_confidence = 0.95
        else:
            release.context_confidence = 0.8

        logger.info(
            "Context released release_id=%s confidence=%s degraded=%s",
            release.release_id,
            release.context_confidence,
            release.degraded,
        )
        return release


__all__ = ["RepositoryQuarantineService", "_derive_stable_dir_name"]

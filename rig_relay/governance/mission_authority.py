from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class AuthorityDecision(StrEnum):
    """Typed authority evaluation outcome.

    Emitted by the authority evaluator, not reconstructed from result status.
    """

    ALLOWED_IN_SCOPE = "allowed_in_scope"
    REQUIRES_SCOPE_EXPANSION = "requires_scope_expansion"
    REQUIRES_CONSECUTIAL_APPROVAL = "requires_consequential_approval"
    REFUSED_BY_POLICY = "refused_by_policy"
    NOT_EVALUATED = "not_evaluated_under_mission_authority"


class AuthoritySource(StrEnum):
    MISSION_CLAIM = "mission_claim"
    LEGACY_POLICY = "legacy_policy"
    BYPASS_PROFILE = "bypass_profile"
    NONE = "none"


class MatchedRuleKind(StrEnum):
    SCOPE_PATH = "scope_path"
    CONSEQUENTIAL_ACTION = "consequential_action"
    PROTECTED_SURFACE = "protected_surface"
    TOOL_NOT_ADMITTED = "tool_not_admitted"
    NORMAL_WORK = "normal_work"
    REPOSITORY_READ = "repository_read"
    WORKTREE_VALIDATION = "worktree_validation"
    CANONICAL_EVIDENCE_WRITE = "canonical_evidence_write"
    GOVERNED_CHECKPOINT = "governed_checkpoint"


# ── Invariant policy rails — never weakened by mission claim ─────────

_PUSH_MERGE_PROMOTE_ACTIONS: frozenset[str] = frozenset({
    "push",
    "merge",
    "promote",
    "publish",
    "release",
    "force_push",
})

_DESTRUCTIVE_GIT_ACTIONS: frozenset[str] = frozenset({
    "reset",
    "clean",
    "rebase",
    "checkout",
    "stash",
})

_REMOTE_MUTATION_ACTIONS: frozenset[str] = frozenset({
    "remote_mutation",
    "external_api_mutation",
    "provider_mutation",
})

_PROTECTED_SURFACE_ACTIONS: frozenset[str] = frozenset({
    "telemetry_policy_change",
    "privacy_policy_change",
    "consent_policy_change",
    "credential_access",
    "secret_access",
    "governance_weakening",
    "test_gate_weakening",
    "release_gate_weakening",
    "dependency_change",
    "lockfile_regeneration",
})

# ── Normal-work tool classes admitted automatically within scope ─────

_NORMAL_WORK_MUTATION_CLASSES: frozenset[str] = frozenset({"writes_workspace"})

_READ_ONLY_VISIBILITY_CLASSES: frozenset[str] = frozenset({"read_only"})


@dataclass(frozen=True)
class AuthorityEvaluation:
    """Result of authority evaluation for a single tool call.

    Emitted by the authority evaluator gate (Gate 2.5). This is the
    canonical authority truth, not reconstructed from result status.
    """

    decision: AuthorityDecision
    source: AuthoritySource = AuthoritySource.NONE
    matched_rule_kind: str | None = None
    requires_approval: bool = False
    mission_id: str | None = None
    claim_id: str | None = None
    provenance_sha256: str | None = None


@dataclass(frozen=True)
class MissionExecutionAuthority:
    """Runtime projection of an admitted coordination claim + invariant policy.

    Derived mechanically from CoordinationTaskClaim. Read-only. Contains
    no independent scope fields — canonical_paths are normalized from
    scope_allowed_paths on the claim.
    """

    claim_id: str
    session_id: str
    task_id: str
    mission_id: str | None = None
    canonical_paths: tuple[Path, ...] = ()
    worktree_root: Path | None = None
    admitted_checkpoint: bool = False
    admitted_dependency_change: bool = False
    admitted_protected_surface: bool = False
    expires_at: str | None = None
    status: str = "active"
    provenance_sha256: str | None = None

    def is_active(self) -> bool:
        if self.status != "active":
            return False
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at)
                if datetime.now(UTC) > expires:
                    return False
            except (ValueError, TypeError):
                return False
        return True

    def is_path_in_write_scope(self, target_path: str | Path) -> bool:
        target = Path(target_path).resolve()
        for allowed in self.canonical_paths:
            try:
                target.relative_to(allowed.resolve())
                return True
            except ValueError:
                continue
        return False

    def is_path_in_read_scope(self, target_path: str | Path) -> bool:
        if self.worktree_root is None:
            return self.is_path_in_write_scope(target_path)
        target = Path(target_path).resolve()
        try:
            target.relative_to(self.worktree_root.resolve())
            return True
        except ValueError:
            pass
        return self.is_path_in_write_scope(target_path)

    def evaluate(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        mutation_class: str | None,
        execution_mode: str | None,
    ) -> AuthorityEvaluation:
        if not self.is_active():
            return AuthorityEvaluation(
                decision=AuthorityDecision.REFUSED_BY_POLICY,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.PROTECTED_SURFACE,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        file_paths = _extract_file_paths(tool_args)

        # 1. Protected surfaces always escalate
        if (
            tool_name in _PROTECTED_SURFACE_ACTIONS
            or tool_name in _REMOTE_MUTATION_ACTIONS
        ):
            if self.admitted_protected_surface:
                return AuthorityEvaluation(
                    decision=AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL,
                    source=AuthoritySource.MISSION_CLAIM,
                    matched_rule_kind=MatchedRuleKind.PROTECTED_SURFACE,
                    requires_approval=True,
                    mission_id=self.mission_id,
                    claim_id=self.claim_id,
                    provenance_sha256=self.provenance_sha256,
                )
            return AuthorityEvaluation(
                decision=AuthorityDecision.REFUSED_BY_POLICY,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.PROTECTED_SURFACE,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        if (
            tool_name in _PUSH_MERGE_PROMOTE_ACTIONS
            or tool_name in _DESTRUCTIVE_GIT_ACTIONS
        ):
            return AuthorityEvaluation(
                decision=AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.CONSEQUENTIAL_ACTION,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        # 2. Read-only tools: auto-admitted worktree-wide
        if mutation_class in _READ_ONLY_VISIBILITY_CLASSES:
            return AuthorityEvaluation(
                decision=AuthorityDecision.ALLOWED_IN_SCOPE,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.REPOSITORY_READ,
                requires_approval=False,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        # 3. Mutation tools: check file paths against write scope
        is_mutation = mutation_class in _NORMAL_WORK_MUTATION_CLASSES

        if tool_name == "checkpoint":
            if self.admitted_checkpoint:
                return AuthorityEvaluation(
                    decision=AuthorityDecision.ALLOWED_IN_SCOPE,
                    source=AuthoritySource.MISSION_CLAIM,
                    matched_rule_kind=MatchedRuleKind.GOVERNED_CHECKPOINT,
                    requires_approval=False,
                    mission_id=self.mission_id,
                    claim_id=self.claim_id,
                    provenance_sha256=self.provenance_sha256,
                )
            return AuthorityEvaluation(
                decision=AuthorityDecision.REQUIRES_CONSECUTIAL_APPROVAL,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.CONSEQUENTIAL_ACTION,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        if tool_name in {"ruff_format"}:
            if file_paths and all(self.is_path_in_write_scope(p) for p in file_paths):
                return AuthorityEvaluation(
                    decision=AuthorityDecision.ALLOWED_IN_SCOPE,
                    source=AuthoritySource.MISSION_CLAIM,
                    matched_rule_kind=MatchedRuleKind.SCOPE_PATH,
                    requires_approval=False,
                    mission_id=self.mission_id,
                    claim_id=self.claim_id,
                    provenance_sha256=self.provenance_sha256,
                )

        if is_mutation and file_paths:
            if all(self.is_path_in_write_scope(p) for p in file_paths):
                return AuthorityEvaluation(
                    decision=AuthorityDecision.ALLOWED_IN_SCOPE,
                    source=AuthoritySource.MISSION_CLAIM,
                    matched_rule_kind=MatchedRuleKind.SCOPE_PATH,
                    requires_approval=False,
                    mission_id=self.mission_id,
                    claim_id=self.claim_id,
                    provenance_sha256=self.provenance_sha256,
                )
            return AuthorityEvaluation(
                decision=AuthorityDecision.REQUIRES_SCOPE_EXPANSION,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.SCOPE_PATH,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        if is_mutation:
            return AuthorityEvaluation(
                decision=AuthorityDecision.REQUIRES_SCOPE_EXPANSION,
                source=AuthoritySource.MISSION_CLAIM,
                matched_rule_kind=MatchedRuleKind.TOOL_NOT_ADMITTED,
                requires_approval=True,
                mission_id=self.mission_id,
                claim_id=self.claim_id,
                provenance_sha256=self.provenance_sha256,
            )

        return AuthorityEvaluation(
            decision=AuthorityDecision.NOT_EVALUATED,
            source=AuthoritySource.MISSION_CLAIM,
            matched_rule_kind=MatchedRuleKind.TOOL_NOT_ADMITTED,
            requires_approval=True,
            mission_id=self.mission_id,
            claim_id=self.claim_id,
            provenance_sha256=self.provenance_sha256,
        )


def _extract_file_paths(args: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "path", "target", "file"):
        val = args.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
    for key in ("files", "paths", "targets"):
        val = args.get(key)
        if isinstance(val, list):
            paths.extend(v for v in val if isinstance(v, str) and v)
    val = args.get("include_paths")
    if isinstance(val, list):
        paths.extend(v for v in val if isinstance(v, str) and v)
    return paths


def derive_authority_from_claim(
    claim: Any,
    worktree_root: str | Path | None = None,
    admitted_checkpoint: bool = False,
    admitted_dependency_change: bool = False,
    admitted_protected_surface: bool = False,
    mission_id: str | None = None,
) -> MissionExecutionAuthority:
    canonical_paths: list[Path] = []
    for raw in getattr(claim, "scope_allowed_paths", []) or []:
        try:
            p = Path(raw).resolve()
            canonical_paths.append(p)
        except (TypeError, ValueError):
            continue

    wt_root = None
    if worktree_root is not None:
        wt_root = Path(worktree_root).resolve()

    return MissionExecutionAuthority(
        claim_id=getattr(claim, "task_id", ""),
        session_id=getattr(claim, "session_id", ""),
        task_id=getattr(claim, "task_id", ""),
        mission_id=mission_id,
        canonical_paths=tuple(canonical_paths),
        worktree_root=wt_root,
        admitted_checkpoint=admitted_checkpoint,
        admitted_dependency_change=admitted_dependency_change,
        admitted_protected_surface=admitted_protected_surface,
        expires_at=getattr(claim, "expires_at", None),
        status=getattr(claim, "status", "active"),
        provenance_sha256=getattr(claim, "state_sha256", None),
    )


__all__ = [
    "AuthorityDecision",
    "AuthorityEvaluation",
    "AuthoritySource",
    "MatchedRuleKind",
    "MissionExecutionAuthority",
    "derive_authority_from_claim",
]

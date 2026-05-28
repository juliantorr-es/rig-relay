"""Internal projection builders for Y-lane digestion consumers.

These projections are for internal lane consumers only and must not be
serialized to telemetry or external surfaces. Repository root paths in
projections require content-light redaction for unknown consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import uuid4

from rig_relay.core.logger import logger
from rig_relay.digestion.context_release import (
    RepositoryContextRelease,
    RepositoryLifecycleState,
)


def build_readiness_projection(release: RepositoryContextRelease) -> dict:
    is_released = release.lifecycle_state in {
        RepositoryLifecycleState.CONTEXT_RELEASED,
        RepositoryLifecycleState.WORKSPACE_ELIGIBLE,
    } and bool(release.content_digest)

    is_eligible = False
    if release.workspace_eligibility is not None:
        is_eligible = release.workspace_eligibility.eligible

    _projection: dict = {
        "schema_version": "rig.relay.repository_readiness.v1",
        "repository_root": str(release.repository_root),
        "lifecycle_state": release.lifecycle_state.value,
        "context_released": is_released,
        "workspace_eligible": is_eligible,
        "degraded": release.degraded,
        "blocker_count": len(release.blockers),
        "context_confidence": release.context_confidence,
        "last_released_at": release.released_at.isoformat() if is_released else None,
        "release_digest": release.content_digest if is_released else None,
    }
    _projection["projection_digest"] = sha256(
        json.dumps(_projection, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return _projection


def compute_readiness_summary(releases: list[RepositoryContextRelease]) -> dict:
    total = len(releases)
    if total == 0:
        return {
            "total_repos": 0,
            "ready_count": 0,
            "degraded_count": 0,
            "average_confidence": 0.0,
            "by_lifecycle_state": {},
        }

    ready = 0
    degraded = 0
    confidence_sum = 0.0
    state_groups: dict[str, int] = {}

    for release in releases:
        is_released = release.lifecycle_state in {
            RepositoryLifecycleState.CONTEXT_RELEASED,
            RepositoryLifecycleState.WORKSPACE_ELIGIBLE,
        } and bool(release.content_digest)

        is_eligible = False
        if release.workspace_eligibility is not None:
            is_eligible = release.workspace_eligibility.eligible

        if is_released and is_eligible:
            ready += 1

        if release.degraded:
            degraded += 1

        confidence_sum += release.context_confidence

        state = release.lifecycle_state.value
        state_groups[state] = state_groups.get(state, 0) + 1

    return {
        "total_repos": total,
        "ready_count": ready,
        "degraded_count": degraded,
        "average_confidence": round(confidence_sum / total, 4),
        "by_lifecycle_state": state_groups,
    }


def build_workspace_eligibility_projection(release: RepositoryContextRelease) -> dict:
    eligibility = release.workspace_eligibility
    _projection: dict = {
        "schema_version": "rig.relay.repository_workspace_eligibility.v1",
        "release_id": release.release_id,
        "eligible": eligibility.eligible if eligibility else False,
        "blockers": eligibility.blockers if eligibility else [],
        "recommended_workspace_kind": (
            eligibility.recommended_workspace_kind if eligibility else None
        ),
        "path_policy": eligibility.path_policy if eligibility else None,
        "evaluated_at": release.released_at.isoformat(),
    }
    _projection["eligibility_digest"] = sha256(
        json.dumps(_projection, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return _projection


def compute_eligibility_summary(releases: list[RepositoryContextRelease]) -> dict:
    eligible_count = 0
    blocked_count = 0
    blocker_frequencies: dict[str, int] = {}

    for release in releases:
        eligibility = release.workspace_eligibility
        if eligibility is None:
            blocked_count += 1
            blocker_frequencies["workspace_eligibility_not_evaluated"] = (
                blocker_frequencies.get("workspace_eligibility_not_evaluated", 0) + 1
            )
            continue

        if eligibility.eligible:
            eligible_count += 1
        else:
            blocked_count += 1
            for blocker in eligibility.blockers:
                key = blocker[:120]
                blocker_frequencies[key] = blocker_frequencies.get(key, 0) + 1

    return {
        "eligible_count": eligible_count,
        "blocked_count": blocked_count,
        "blocker_frequencies": blocker_frequencies,
    }


def build_context_capsule(release: RepositoryContextRelease) -> dict:
    capsule_id = uuid4().hex

    dep_summary = release.dependency_risk_summary
    si_digest = release.structural_index_digest

    _capsule: dict = {
        "schema_version": "rig.relay.context_capsule.v1",
        "capsule_id": capsule_id,
        "repository_root": str(release.repository_root),
        "released_context_digest": release.content_digest,
        "instruction_scope_text_length": None,
        "structural_index_digest": si_digest.index_digest if si_digest else "",
        "module_count": si_digest.module_count if si_digest else 0,
        "symbol_count": si_digest.symbol_count if si_digest else 0,
        "dependency_summary": {
            "total": dep_summary.total_dependencies if dep_summary else 0,
            "production": dep_summary.production_count if dep_summary else 0,
            "dev": dep_summary.dev_count if dep_summary else 0,
            "risk": dep_summary.risk_count if dep_summary else 0,
        },
        "safe_commands": [r.command for r in release.safe_validation_results],
        "restrictions": list(release.restrictions),
        "confidence": release.context_confidence,
        "fresh": None,
        "stale_since": None,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _capsule["capsule_digest"] = sha256(
        json.dumps(_capsule, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return _capsule


def compute_harness_envelope_hint(capsule: dict, harness_profile: str) -> dict:
    sections = _harness_sections(harness_profile)

    total_tokens = 0
    for section in sections:
        total_tokens += section.get("content_token_estimate", 0)

    hint: dict = {
        "harness": harness_profile,
        "suggested_sections": sections,
        "estimated_tokens": max(total_tokens, 100),
    }

    match harness_profile:
        case "claude_code":
            hint["target_file"] = "CLAUDE.md"
        case "github_copilot":
            hint["target_file"] = ".github/copilot-instructions.md"
        case "cursor":
            hint["target_file"] = ".cursor/rules/rig-relay-context.mdc"
        case "rig_relay":
            hint["target_file"] = "AGENTS.md"

    return hint


def _harness_sections(harness_profile: str) -> list[dict]:
    match harness_profile:
        case "claude_code":
            return [
                {
                    "name": "Repository Context",
                    "kind": "overview",
                    "priority": 1,
                    "content_token_estimate": 120,
                    "template": (
                        "This is a {lang} repository with {module_count} modules "
                        "and {symbol_count} symbols. Repository root: {root}."
                    ),
                },
                {
                    "name": "Validation Commands",
                    "kind": "commands",
                    "priority": 2,
                    "content_token_estimate": 80,
                    "template": (
                        "Safe validation commands: {commands}. "
                        "Always run validation before proposing changes."
                    ),
                },
                {
                    "name": "Path Restrictions",
                    "kind": "policy",
                    "priority": 3,
                    "content_token_estimate": 60,
                    "template": (
                        "Restrictions: {restrictions}. "
                        "Do not modify paths outside scope without explicit permission."
                    ),
                },
            ]
        case "github_copilot":
            return [
                {
                    "name": "Workspace Instructions",
                    "kind": "overview",
                    "priority": 1,
                    "content_token_estimate": 100,
                    "template": (
                        "Repository: {root}. Context confidence: {confidence:.2f}. "
                        "Follow existing instruction file conventions."
                    ),
                },
                {
                    "name": "Code Style",
                    "kind": "style",
                    "priority": 2,
                    "content_token_estimate": 70,
                    "template": (
                        "Use {lang}. Follow project conventions. "
                        "Run {commands} after changes."
                    ),
                },
            ]
        case "cursor":
            return [
                {
                    "name": "Project Rules",
                    "kind": "rules",
                    "priority": 1,
                    "content_token_estimate": 110,
                    "template": (
                        "Always read AGENTS.md and PROJECT.md first. "
                        "This repository has {module_count} modules. "
                        "Context confidence: {confidence:.2f}."
                    ),
                },
                {
                    "name": "Validation",
                    "kind": "commands",
                    "priority": 2,
                    "content_token_estimate": 60,
                    "template": "Always run: {commands}",
                },
            ]
        case _:
            return [
                {
                    "name": "Context Summary",
                    "kind": "overview",
                    "priority": 1,
                    "content_token_estimate": 100,
                    "template": (
                        "Repository context capsule. Confidence: {confidence:.2f}. "
                        "Modules: {module_count}, Symbols: {symbol_count}."
                    ),
                }
            ]


def build_context_lifecycle_event(
    release: RepositoryContextRelease, event_kind: str
) -> dict:
    si_digest = release.structural_index_digest
    dep_summary = release.dependency_risk_summary
    inst_digest = release.instruction_map_digest

    module_count = si_digest.module_count if si_digest else 0
    dep_count = dep_summary.total_dependencies if dep_summary else 0
    risk_count = dep_summary.risk_count if dep_summary else 0
    inst_count = inst_digest.instruction_file_count if inst_digest else 0

    _event: dict = {
        "schema_version": "rig.relay.context_lifecycle_event.v1",
        "event_id": uuid4().hex,
        "event_kind": event_kind,
        "release_id": release.release_id,
        "lifecycle_state": release.lifecycle_state.value,
        "degraded": release.degraded,
        "context_confidence": release.context_confidence,
        "instruction_count": inst_count,
        "module_count": module_count,
        "dependency_count": dep_count,
        "risk_count": risk_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    event_copy = dict(_event)
    _raw = json.dumps(event_copy, sort_keys=True, ensure_ascii=False).encode("utf-8")
    event_copy["content_digest"] = sha256(_raw).hexdigest()
    return event_copy


def _redact_repository_roots(projections: dict) -> dict:
    """Redact ``repository_root`` from projection dicts for non-internal consumers."""
    return {
        k: {**v, "repository_root": ""}
        if isinstance(v, dict) and "repository_root" in v
        else v
        for k, v in projections.items()
    }


class ContextProjectionService:
    def build_all_projections(self, release: RepositoryContextRelease) -> dict:
        lifecycle_event_kind = {
            RepositoryLifecycleState.CONTEXT_RELEASED: "context.released",
            RepositoryLifecycleState.WORKSPACE_ELIGIBLE: "context.released",
            RepositoryLifecycleState.DEGRADED: "context.degraded",
        }.get(release.lifecycle_state, "context.released")

        result = {
            "readiness": build_readiness_projection(release),
            "workspace_eligibility": build_workspace_eligibility_projection(release),
            "context_capsule": build_context_capsule(release),
            "lifecycle_event": build_context_lifecycle_event(
                release, lifecycle_event_kind
            ),
        }
        logger.debug(
            "Projections built for release %s, state=%s",
            release.release_id,
            release.lifecycle_state.value,
        )
        return result

    def project_for_consumer(
        self, release: RepositoryContextRelease, consumer: str
    ) -> dict:
        consumer_lower = consumer.lower().strip()

        match consumer_lower:
            case "y0":
                return {"readiness": build_readiness_projection(release)}
            case "y1":
                return {
                    "workspace_eligibility": build_workspace_eligibility_projection(
                        release
                    )
                }
            case "y3":
                return {"context_capsule": build_context_capsule(release)}
            case "y4":
                lifecycle_event_kind = {
                    RepositoryLifecycleState.CONTEXT_RELEASED: "context.released",
                    RepositoryLifecycleState.WORKSPACE_ELIGIBLE: "context.released",
                    RepositoryLifecycleState.DEGRADED: "context.degraded",
                }.get(release.lifecycle_state, "context.released")
                return {
                    "lifecycle_event": build_context_lifecycle_event(
                        release, lifecycle_event_kind
                    )
                }
            case _:
                logger.warning(
                    "Unknown consumer %s, redacting repository_root from projections",
                    consumer_lower,
                )
                return _redact_repository_roots(self.build_all_projections(release))


__all__ = [
    "ContextProjectionService",
    "build_context_capsule",
    "build_context_lifecycle_event",
    "build_readiness_projection",
    "build_workspace_eligibility_projection",
    "compute_eligibility_summary",
    "compute_harness_envelope_hint",
    "compute_readiness_summary",
]

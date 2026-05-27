"""Projection builder — typed collaborator for evidence reconstruction.

Reads all registration and observation evidence from the append-only store,
validates payloads and observation-chain linkage, tracks corruption events,
and produces a RepositoryEstateProjection with explicit authority degradation
when any evidence is corrupt or broken.
"""

from __future__ import annotations

from rig_relay.repository_estate._change_detector import ChangeDetector
from rig_relay.repository_estate._models import (
    AuthorityState,
    CorruptionEvent,
    ObservationStatus,
    ProvenanceClass,
    RecentChangeEvent,
    RegisteredRepository,
    RegisteredRepositorySummary,
    RepositoryEstateProjection,
    RepositoryKind,
    RepositoryObservation,
)
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore


class ProjectionBuilder:
    """Typed authority for reconstructing projections from canonical evidence.

    Validates every registration and observation payload on reconstruction.
    Corruption events, model-validation failures, and broken observation-chain
    digest links are tracked and degrade the projection authority_state.

    A projection may report CANONICAL_LIVE only when all evidence payloads
    pass validation and all observation-chain links are intact.
    """

    def __init__(self, store: RepositoryEstateRegistryStore) -> None:
        self._store = store
        self._change_detector = ChangeDetector()

    def build(self) -> RepositoryEstateProjection:
        registrations = self._store.read_all_registrations()
        observations = self._store.read_all_observations()

        if not registrations:
            return RepositoryEstateProjection(
                authority_state=AuthorityState.MISSING,
                degraded_reason="No registrations found in evidence store.",
            )

        corruption_events: list[CorruptionEvent] = []

        # Validate and deduplicate registrations
        latest_reg: dict[str, RegisteredRepository] = {}
        for reg_event in registrations:
            event_id = reg_event.get("event_id", "")
            if reg_event.get("_corrupt"):
                corruption_events.append(
                    CorruptionEvent(
                        event_kind="registration",
                        event_id=event_id,
                        reason="malformed_json",
                    )
                )
                continue
            try:
                reg = RegisteredRepository.model_validate(reg_event["payload"])
            except Exception:
                corruption_events.append(
                    CorruptionEvent(
                        event_kind="registration",
                        event_id=event_id,
                        reason="model_validation_failed",
                    )
                )
                continue
            rh = reg.repository_hash
            existing = latest_reg.get(rh)
            if (
                existing is None
                or reg.last_registered_at >= existing.last_registered_at
            ):
                latest_reg[rh] = reg

        # Index observations by repository_hash
        obs_by_repo: dict[str, list[dict]] = {}
        valid_observations: dict[str, list[RepositoryObservation]] = {}
        for o in observations:
            event_id = o.get("event_id", "")
            repo_hash = o.get("payload", {}).get("repository_hash", "")
            if o.get("_corrupt"):
                corruption_events.append(
                    CorruptionEvent(
                        event_kind="observation",
                        event_id=event_id,
                        reason="malformed_json",
                        repository_hash=repo_hash,
                    )
                )
                continue
            try:
                obs = RepositoryObservation.model_validate(o["payload"])
            except Exception:
                corruption_events.append(
                    CorruptionEvent(
                        event_kind="observation",
                        event_id=event_id,
                        reason="model_validation_failed",
                        repository_hash=repo_hash,
                    )
                )
                if repo_hash:
                    obs_by_repo.setdefault(repo_hash, []).append(o)
                continue
            if repo_hash:
                obs_by_repo.setdefault(repo_hash, []).append(o)
                valid_observations.setdefault(repo_hash, []).append(obs)
            else:
                corruption_events.append(
                    CorruptionEvent(
                        event_kind="observation",
                        event_id=event_id,
                        reason="missing_repository_hash",
                    )
                )

        # Validate observation-chain linkage
        chain_broken = 0
        for rh, obs_list in valid_observations.items():
            for i in range(1, len(obs_list)):
                prev = obs_list[i - 1]
                curr = obs_list[i]
                if curr.previous_observation_digest is not None:
                    if curr.previous_observation_digest != prev.observation_digest:
                        chain_broken += 1
                        corruption_events.append(
                            CorruptionEvent(
                                event_kind="observation",
                                event_id=curr.observation_id,
                                reason="chain_broken",
                                repository_hash=rh,
                                observation_id=curr.observation_id,
                            )
                        )

        # Build summaries
        summaries: list[RegisteredRepositorySummary] = []
        recent_changes: list[RecentChangeEvent] = []
        dirty_count = 0
        inaccessible_count = 0
        _DEGRADED_STATUS_SET = {
            ObservationStatus.INACCESSIBLE,
            ObservationStatus.NOT_A_REPOSITORY,
            ObservationStatus.DISAPPEARED,
        }

        for reg in latest_reg.values():
            repo_obs_list = valid_observations.get(reg.repository_hash, [])
            latest_obs = repo_obs_list[-1] if repo_obs_list else None

            is_dirty = False
            if latest_obs is not None:
                dc = latest_obs.git_facts.dirty_counts
                is_dirty = bool(
                    dc.modified
                    or dc.staged
                    or dc.untracked
                    or dc.deleted
                    or dc.conflicted
                )
                if latest_obs.status in _DEGRADED_STATUS_SET:
                    inaccessible_count += 1
                elif is_dirty:
                    dirty_count += 1

            summary = RegisteredRepositorySummary(
                provenance=(
                    ProvenanceClass.CANONICAL_FACT
                    if latest_obs
                    else ProvenanceClass.CORRUPT_UNTRUSTED
                ),
                repository_hash=reg.repository_hash,
                repository_label=reg.repository_label,
                repository_kind=reg.repository_kind,
                root_path_digest=reg.root_path_digest,
                registered_at=reg.registered_at,
                last_registered_at=reg.last_registered_at,
                latest_observation_digest=reg.latest_observation_digest,
                latest_observation_at=reg.latest_observation_at,
                latest_status=latest_obs.status
                if latest_obs
                else ObservationStatus.REGISTERED,
                latest_head_sha=latest_obs.git_facts.head_sha if latest_obs else None,
                latest_branch=latest_obs.git_facts.branch if latest_obs else None,
                is_detached=latest_obs.git_facts.is_detached if latest_obs else False,
                is_dirty=is_dirty,
                dirty_modified=latest_obs.git_facts.dirty_counts.modified
                if latest_obs
                else 0,
                dirty_untracked=latest_obs.git_facts.dirty_counts.untracked
                if latest_obs
                else 0,
                tracked_file_count=latest_obs.git_facts.tracked_file_count
                if latest_obs
                else 0,
                is_github_backed=reg.repository_kind == RepositoryKind.GITHUB_BACKED,
                is_local_only=reg.repository_kind == RepositoryKind.LOCAL_ONLY,
                instruction_file_count=(
                    len(latest_obs.git_facts.instruction_files) if latest_obs else 0
                ),
                remote_count=len(latest_obs.git_facts.remotes) if latest_obs else 0,
                degraded_reason=(
                    _degraded_reason_for_status(latest_obs.status)
                    if latest_obs and latest_obs.status in _DEGRADED_STATUS_SET
                    else ""
                ),
            )
            summaries.append(summary)

            # Compute recent changes
            prev_obs_wrapper: RepositoryObservation | None = None
            for obs in repo_obs_list[-10:]:
                if prev_obs_wrapper is not None:
                    change = self._change_detector.detect(
                        prev_obs_wrapper, obs.git_facts, obs.observation_id
                    )
                    if change.changed:
                        recent_changes.append(
                            RecentChangeEvent(
                                repository_hash=reg.repository_hash,
                                repository_label=reg.repository_label,
                                detected_at=obs.observed_at,
                                change_kinds=change.change_kinds,
                                from_observation_id=change.from_observation_id,
                                to_observation_id=change.to_observation_id,
                            )
                        )
                prev_obs_wrapper = obs

        recent_changes.sort(key=lambda c: c.detected_at, reverse=True)
        recent_changes = recent_changes[:50]

        # Compute authority state with corruption degradation
        authority = AuthorityState.CANONICAL_LIVE
        degraded = ""
        has_corruption = bool(corruption_events)
        has_inaccessible = inaccessible_count > 0

        if has_corruption or chain_broken > 0:
            authority = AuthorityState.CORRUPT
            parts: list[str] = []
            if has_corruption:
                parts.append(f"{len(corruption_events)} corrupt evidence records")
            if chain_broken > 0:
                parts.append(f"{chain_broken} broken chain links")
            degraded = "; ".join(parts)
        elif has_inaccessible:
            authority = AuthorityState.DEGRADED
            degraded = f"{inaccessible_count} repositories inaccessible"
        elif not observations:
            authority = AuthorityState.STALE
            degraded = "No observations recorded"

        return RepositoryEstateProjection(
            provenance=ProvenanceClass.DERIVED_PROJECTION,
            authority_state=authority,
            degraded_reason=degraded,
            available=len(summaries) > 0,
            registered_repositories=summaries,
            total_registered=len(summaries),
            local_only_count=sum(
                1 for s in summaries if s.repository_kind == RepositoryKind.LOCAL_ONLY
            ),
            github_backed_count=sum(
                1
                for s in summaries
                if s.repository_kind == RepositoryKind.GITHUB_BACKED
            ),
            dirty_count=dirty_count,
            inaccessible_count=inaccessible_count,
            recent_changes=recent_changes,
            total_observations=len(observations),
            corrupt_registration_count=sum(
                1 for c in corruption_events if c.event_kind == "registration"
            ),
            corrupt_observation_count=sum(
                1 for c in corruption_events if c.event_kind == "observation"
            ),
            corrupt_chain_links=chain_broken,
            corruption_events=corruption_events,
        )


def _degraded_reason_for_status(status: ObservationStatus) -> str:
    if status == ObservationStatus.INACCESSIBLE:
        return "Repository path is inaccessible."
    if status == ObservationStatus.NOT_A_REPOSITORY:
        return "Path is no longer a git repository."
    if status == ObservationStatus.DISAPPEARED:
        return "Repository path has disappeared."
    if status == ObservationStatus.IDENTITY_MISMATCH:
        return "Observed path does not match registered repository identity."
    return ""


__all__ = ["ProjectionBuilder"]

"""Change detector — typed collaborator for observation change analysis.

Compares two observation payloads and produces a structured
RepositoryObservationChange with specific change kind classification.
"""

from __future__ import annotations

from rig_relay.repository_estate._models import (
    ChangeKind,
    GitIdentityBundle,
    RepositoryObservation,
    RepositoryObservationChange,
)


class ChangeDetector:
    """Typed authority for detecting changes between repository observations.

    Compares GitIdentityBundle facts and produces a classified change record.
    Exists as a separate collaborator so change-detection logic can be
    tested in isolation and reused by both observation and projection paths.
    """

    def detect(
        self,
        previous: RepositoryObservation,
        current_facts: GitIdentityBundle,
        new_obs_id: str,
    ) -> RepositoryObservationChange:
        """Detect changes between a prior observation and current facts."""
        prev_facts = previous.git_facts
        change_kinds: list[ChangeKind] = []

        if prev_facts.head_sha != current_facts.head_sha:
            change_kinds.append(ChangeKind.HEAD_CHANGED)
        if prev_facts.branch != current_facts.branch:
            change_kinds.append(ChangeKind.BRANCH_CHANGED)
        if prev_facts.is_detached != current_facts.is_detached:
            change_kinds.append(ChangeKind.DETACHED_STATE_CHANGED)

        prev_dc = prev_facts.dirty_counts
        curr_dc = current_facts.dirty_counts
        if (
            prev_dc.modified != curr_dc.modified
            or prev_dc.staged != curr_dc.staged
            or prev_dc.untracked != curr_dc.untracked
            or prev_dc.deleted != curr_dc.deleted
            or prev_dc.conflicted != curr_dc.conflicted
        ):
            change_kinds.append(ChangeKind.DIRTY_STATE_CHANGED)

        if prev_facts.tracked_file_count != current_facts.tracked_file_count:
            change_kinds.append(ChangeKind.TRACKED_FILE_COUNT_CHANGED)

        if self._remote_set(prev_facts) != self._remote_set(current_facts):
            change_kinds.append(ChangeKind.REMOTES_CHANGED)

        if prev_facts.git_common_dir_digest != current_facts.git_common_dir_digest:
            change_kinds.append(ChangeKind.COMMON_DIR_CHANGED)

        if self._instruction_set(prev_facts) != self._instruction_set(current_facts):
            change_kinds.append(ChangeKind.INSTRUCTION_FILES_CHANGED)

        return RepositoryObservationChange(
            repository_hash=previous.repository_hash,
            from_observation_id=previous.observation_id,
            to_observation_id=new_obs_id,
            from_observation_digest=previous.observation_digest,
            to_observation_digest="",
            changed=len(change_kinds) > 0,
            change_kinds=change_kinds,
        )

    def _remote_set(self, facts: GitIdentityBundle) -> frozenset[str]:
        return frozenset(r.url_digest for r in facts.remotes)

    def _instruction_set(self, facts: GitIdentityBundle) -> frozenset[str]:
        return frozenset(i.content_sha256 for i in facts.instruction_files)


__all__ = ["ChangeDetector"]

"""RepositoryEstateService — typed application service for repository registration,
observation, change detection, and projection with identity-match enforcement.

Orchestrates four collaborators: RegistrationAuthority, ObservationEngine,
ChangeDetector, and ProjectionBuilder. Every observation is identity-gated
before evidence is appended. Projections degrade on corrupt or broken evidence.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.repository_estate._change_detector import ChangeDetector
from rig_relay.repository_estate._models import (
    RegisteredRepository,
    RepositoryEstateProjection,
    RepositoryObservation,
)
from rig_relay.repository_estate._observation_engine import ObservationEngine
from rig_relay.repository_estate._projection_builder import ProjectionBuilder
from rig_relay.repository_estate._registration import (
    RegistrationAuthority,
    RegistrationError,
)
from rig_relay.repository_estate._registry_store import RepositoryEstateRegistryStore

RegistryError = RegistrationError


class RepositoryEstateService:
    """Typed application service for the Repository Estate domain.

    Owns the authority to register local repositories, observe them with
    identity-match enforcement, and emit reconstructable projections with
    explicit corruption degradation.

    All evidence is append-only and content-light. No private source content,
    raw paths, or secrets are ever emitted.
    """

    def __init__(self, store_root: Path | None = None) -> None:
        store = RepositoryEstateRegistryStore(store_root)
        self._store = store
        self._registration = RegistrationAuthority(store)
        self._observation = ObservationEngine(store)
        self._change_detector = ChangeDetector()
        self._projection_builder = ProjectionBuilder(store)

    # ── Public API ─────────────────────────────────────────────────────

    def register_repository(self, root_path: Path) -> RegisteredRepository:
        """Register a local repository through the typed application service.

        Idempotent: re-registering the same repository updates timestamps
        and observations without creating a duplicate identity record.

        Raises:
            RegistryError: If the path is not a git repository.
        """
        registration, worktree_root = self._registration.register(root_path)

        previous_obs = self._latest_observation(registration.repository_hash)
        observation = self._observation.observe(
            registration=registration,
            root_path=worktree_root,
            previous_obs=previous_obs,
            initial_registration=(
                previous_obs is None and registration.latest_observation_digest is None
            ),
        )
        self._store.append_observation(observation)

        registration.latest_observation_digest = observation.observation_digest
        registration.latest_observation_at = observation.observed_at
        self._store.append_registration(registration)

        return registration

    def observe_repository(
        self, repository_hash: str, root_path: Path | None = None
    ) -> RepositoryObservation:
        """Observe a registered repository with identity-match enforcement.

        The supplied root_path is validated against the registered
        repository identity before any observation evidence is appended.
        A mismatched path produces an IDENTITY_MISMATCH observation.

        Args:
            repository_hash: Stable identifier from registration.
            root_path: Filesystem path. If None and the path cannot be
                resolved, returns a DISAPPEARED observation.

        Returns:
            A RepositoryObservation with appropriate status.

        Raises:
            RegistryError: If no registration exists for this hash.
        """
        registration_event = self._registration.find_event(repository_hash)
        if registration_event is None:
            raise RegistryError(f"No registration found for hash: {repository_hash}")

        registration = RegisteredRepository.model_validate(
            registration_event["payload"]
        )

        previous_obs = self._latest_observation(repository_hash)

        observation = self._observation.observe_or_disappeared(
            registration=registration,
            root_path=root_path,
            previous_obs=previous_obs,
            initial_registration=False,
        )
        self._store.append_observation(observation)

        registration.latest_observation_digest = observation.observation_digest
        registration.latest_observation_at = observation.observed_at
        self._store.append_registration(registration)

        return observation

    def build_projection(self) -> RepositoryEstateProjection:
        """Build a projection from canonical evidence with corruption degradation."""
        return self._projection_builder.build()

    # ── Internal helpers ───────────────────────────────────────────────

    def _latest_observation(self, repository_hash: str) -> RepositoryObservation | None:
        event = self._store.latest_observation_for(repository_hash)
        if event is None:
            return None
        try:
            return RepositoryObservation.model_validate(event["payload"])
        except Exception:
            return None


__all__ = ["RegistryError", "RepositoryEstateService"]

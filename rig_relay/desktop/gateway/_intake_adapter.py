"""Live intake adapter — converts RepositoryIntakeService output to IntakeFixture for L0 consumption.

Lane X0.2: This is a gateway adapter, not a fixture constructor. It reads real git state
from the published RepositoryIntakeService and maps it to the shape L0 expects.
The provenance is derived_projection (data from a real service), not fixture_deferred.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from rig_relay.context_engine.fixtures import IntakeFixture

if TYPE_CHECKING:
    from rig_relay.digestion.intake import IntakeResult


def intake_result_to_fixture(
    intake_result: IntakeResult, project_name: str = ""
) -> IntakeFixture:
    """Convert a live IntakeResult from RepositoryIntakeService to IntakeFixture.

    The IntakeFixture class is a data container. When populated from real
    application-service output, the data is real derived_projection,
    not fixture.
    """
    repo = intake_result.repository
    root_path = Path(repo.root_path) if repo.root_path else Path(".")
    name = project_name or root_path.name

    return IntakeFixture(
        repository_root=root_path,
        project_name=name,
        head_sha=repo.head_sha or "",
        branch=repo.branch or "",
        is_github_backed=repo.is_github_backed,
        is_local_only=repo.is_local_only,
        remotes_count=len(repo.remotes),
        repository_url_digest=(
            f"sha256:{sha256(str(root_path).encode()).hexdigest()}"
            if root_path != Path(".")
            else ""
        ),
    )


__all__ = ["intake_result_to_fixture"]

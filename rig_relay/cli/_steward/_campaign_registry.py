"""Path classification registry for campaign runtime authority.

The registry maps paths to classifications that the runtime uses for
write, read, provider-context, checkpoint, and push authorization.
Classifications are validated against the approved campaign manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PathClassification = Literal[
    "campaign_owned",
    "approved_read_context",
    "approved_write_scope",
    "approved_provider_context_candidate",
    "authority_surface_refused",
    "confidential_evidence_excluded",
    "credential_or_secret_refused",
    "private_authentication_material_refused",
    "patent_or_counsel_material_refused",
    "legal_strategy_material_refused",
    "requires_human_review",
    "unclassified_refused",
]

_WRITEABLE_CLASSIFICATIONS: frozenset[PathClassification] = frozenset({
    "approved_write_scope",
    "campaign_owned",
})

_READABLE_CLASSIFICATIONS: frozenset[PathClassification] = frozenset({
    "approved_read_context",
    "approved_write_scope",
    "approved_provider_context_candidate",
    "campaign_owned",
})

_PROVIDER_CONTEXT_CLASSIFICATIONS: frozenset[PathClassification] = frozenset({
    "approved_provider_context_candidate"
})

_REFUSED_CLASSIFICATIONS: frozenset[PathClassification] = frozenset({
    "authority_surface_refused",
    "confidential_evidence_excluded",
    "credential_or_secret_refused",
    "private_authentication_material_refused",
    "patent_or_counsel_material_refused",
    "legal_strategy_material_refused",
    "unclassified_refused",
})


class PathRegistryEntry(BaseModel):
    """A single entry in the path classification registry."""

    model_config = ConfigDict(extra="forbid")

    normalized_path: str = Field(min_length=1)
    classification: PathClassification
    identity_digest: str = Field(min_length=1)
    mission_scope: str | None = None


class PathClassificationRegistry(BaseModel):
    """Campaign-scoped path classification registry.

    Maps paths to classifications that grant or deny operational
    authority. Validated against the approved campaign manifest.
    macOS metadata tags (xattrs) must never grant authority;
    the canonical registry is the sole machine-readable source.
    """

    model_config = ConfigDict(extra="forbid")

    registry_identity: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    manifest_digest: str = Field(min_length=1)
    entries: list[PathRegistryEntry] = Field(default_factory=list)


def compute_registry_digest(registry: PathClassificationRegistry) -> str:
    """Compute a deterministic SHA-256 digest of the registry."""
    return hashlib.sha256(
        json.dumps(registry.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_path_registry(
    campaign_id: str, root: Path
) -> PathClassificationRegistry | None:
    """Load the path classification registry from the campaign directory."""
    registry_path = (
        root
        / ".rig"
        / "relay"
        / "campaigns"
        / campaign_id
        / "path_classification_registry.v1.json"
    )
    if not registry_path.exists():
        return None
    return PathClassificationRegistry.model_validate(
        json.loads(registry_path.read_text())
    )


def save_path_registry(
    registry: PathClassificationRegistry, campaign_id: str, root: Path
) -> Path:
    """Save the path classification registry to the campaign directory."""
    campaign_dir = root / ".rig" / "relay" / "campaigns" / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    registry_path = campaign_dir / "path_classification_registry.v1.json"
    registry_path.write_text(json.dumps(registry.model_dump(), indent=2))
    return registry_path


def lookup_path_classification(
    registry: PathClassificationRegistry, normalized_path: str
) -> PathClassification:
    """Look up the classification for a path in the registry.

    Returns 'unclassified_refused' if the path is not found.
    """
    for entry in registry.entries:
        if entry.normalized_path == normalized_path:
            return entry.classification
    return "unclassified_refused"


def is_write_allowed(
    registry: PathClassificationRegistry, normalized_path: str
) -> bool:
    """Check if a path is classified for write access."""
    classification = lookup_path_classification(registry, normalized_path)
    return classification in _WRITEABLE_CLASSIFICATIONS


def is_read_allowed(registry: PathClassificationRegistry, normalized_path: str) -> bool:
    """Check if a path is classified for read access."""
    classification = lookup_path_classification(registry, normalized_path)
    return classification in _READABLE_CLASSIFICATIONS


def is_provider_context_allowed(
    registry: PathClassificationRegistry, normalized_path: str
) -> bool:
    """Check if a path is classified for provider context."""
    classification = lookup_path_classification(registry, normalized_path)
    return classification in _PROVIDER_CONTEXT_CLASSIFICATIONS


def is_classification_refused(
    registry: PathClassificationRegistry, normalized_path: str
) -> bool:
    """Check if a path is refused (security/confidentiality/exclusion)."""
    classification = lookup_path_classification(registry, normalized_path)
    return classification in _REFUSED_CLASSIFICATIONS

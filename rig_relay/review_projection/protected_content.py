"""Protected-content classification policy and disclosure scope manifest.

Lane A owns this governance surface.  It defines a canonical
content-classification spine for the review-projection compiler and
generates content-light protected-content manifests bound to each
generated candidate bundle.

Content classes:
  RETAIN_PROJECTED         — safe in projected output
  PSEUDONYMIZED_DISCLOSABLE — pseudonymized; may be selectively disclosed
  HASH_EVIDENCE_ONLY        — content-light hash + metadata only
  PROHIBITED                — never exported or disclosed through this corridor
"""

from __future__ import annotations

from enum import StrEnum, auto
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

# ── Content classification classes ────────────────────────────────────


class ContentClass(StrEnum):
    RETAIN_PROJECTED = auto()
    PSEUDONYMIZED_DISCLOSABLE = auto()
    HASH_EVIDENCE_ONLY = auto()
    PROHIBITED = auto()


# ── Content kinds (what the compiler can observe) ─────────────────────


class ContentKind(StrEnum):
    # Structural source elements
    SOURCE_IDENTIFIER = auto()  # function/class/variable names
    SOURCE_PARAMETER = auto()  # function parameters
    SOURCE_STRING_LITERAL = auto()  # string literals in code
    SOURCE_COMMENT = auto()  # comments (stripped by transformer)
    SOURCE_DOCSTRING = auto()  # docstrings (stripped by transformer)
    # Paths and identity
    FILE_PATH = auto()  # file paths relative to repo root
    MODULE_PATH = auto()  # module import paths
    SYMBOL_IDENTITY = auto()  # compound scope identities
    # Sensitive shapes
    CREDENTIAL_SHAPED = auto()  # token/credential-like values
    SECRET_SHAPED = auto()  # API key / private key patterns
    CONFIGURATION_VALUE = auto()  # config-file values
    # Metadata
    BUNDLE_METADATA = auto()  # manifest/projection metadata
    CROSSWALK_MATERIAL = auto()  # pseudonym→original mapping values
    # Source content
    RAW_DIFF_FRAGMENT = auto()  # raw diff output
    USER_PROVIDED_TEXT = auto()  # user-authored comments/docstrings/text


# ── Classification rules ──────────────────────────────────────────────

# Content kinds that are safe to retain in projected output
_RETAIN_PROJECTED_KINDS: frozenset[str] = frozenset({
    ContentKind.BUNDLE_METADATA.value,
    ContentKind.RAW_DIFF_FRAGMENT.value,  # already transformed
})

# Content kinds that are pseudonymized but may be selectively disclosed
# with step-up authorization
_PSEUDONYMIZED_DISCLOSABLE_KINDS: frozenset[str] = frozenset({
    ContentKind.SOURCE_IDENTIFIER.value,
    ContentKind.SOURCE_PARAMETER.value,
    ContentKind.SYMBOL_IDENTITY.value,
})

# Content kinds reduced to hash/metadata only — no raw content in bundle
_HASH_EVIDENCE_ONLY_KINDS: frozenset[str] = frozenset({
    ContentKind.SOURCE_STRING_LITERAL.value,
    ContentKind.SOURCE_COMMENT.value,
    ContentKind.SOURCE_DOCSTRING.value,
    ContentKind.USER_PROVIDED_TEXT.value,
    ContentKind.CONFIGURATION_VALUE.value,
})

# Content kinds prohibited from export or disclosure
_PROHIBITED_KINDS: frozenset[str] = frozenset({
    ContentKind.CREDENTIAL_SHAPED.value,
    ContentKind.SECRET_SHAPED.value,
    ContentKind.CROSSWALK_MATERIAL.value,
})

# Path-related content: file_path → hash_evidence_only, module_path → hash_evidence_only
_PATH_KINDS: frozenset[str] = frozenset({
    ContentKind.FILE_PATH.value,
    ContentKind.MODULE_PATH.value,
})


def classify_content_kind(kind: str) -> ContentClass:
    """Map a ContentKind to its ContentClass per canonical policy."""
    if kind in _RETAIN_PROJECTED_KINDS:
        return ContentClass.RETAIN_PROJECTED
    if kind in _PSEUDONYMIZED_DISCLOSABLE_KINDS:
        return ContentClass.PSEUDONYMIZED_DISCLOSABLE
    if kind in _PROHIBITED_KINDS:
        return ContentClass.PROHIBITED
    return ContentClass.HASH_EVIDENCE_ONLY


def classify_path_kind(kind: str) -> ContentClass:
    if kind in _PATH_KINDS:
        return ContentClass.HASH_EVIDENCE_ONLY
    return ContentClass.HASH_EVIDENCE_ONLY


def is_disclosure_class_prohibited(disclosure_class: str) -> bool:
    """Return True if the governance DisclosureClass is prohibited for this corridor."""
    from rig_relay.governance.disclosure_authorization import (
        RESTRICTED_DISCLOSURE_CLASSES,
    )

    return disclosure_class in RESTRICTED_DISCLOSURE_CLASSES


# ── Protected Content Manifest ────────────────────────────────────────

MANIFEST_SCHEMA_VERSION = "rig.review_projection.protected_content_manifest.v1"
POLICY_VERSION = "rig.review_projection.protected_content_policy.v1"


class ManifestSelector(BaseModel):
    """A single selectively-disclosable item in the manifest."""

    model_config = ConfigDict(extra="forbid")

    selector_id: str = Field(description="Stable selector identifier")
    selector_digest: str = Field(
        description="SHA256 of the pseudonymized selector identity"
    )
    content_kind: str = Field(description="ContentKind of the protected item")
    disclosure_class: str = Field(
        description="Governance DisclosureClass required for disclosure"
    )
    disclosed: bool = Field(
        default=False, description="Whether this selector has been disclosed (consumed)"
    )


class ProtectedContentManifest(BaseModel):
    """Content-light protected-content manifest bound to a candidate bundle.

    Never contains raw protected literals, raw comments, secret values,
    raw source bodies, crosswalk values, or unrestricted errors.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = MANIFEST_SCHEMA_VERSION
    bundle_digest: str = Field(
        default="", description="SHA256 of the candidate ZIP bundle"
    )
    projection_id: str = Field(default="", description="Projection identifier")
    policy_version: str = POLICY_VERSION
    manifest_digest: str = Field(
        default="", description="SHA256 of this manifest (excluding this field)"
    )
    created_at: str = ""
    source_artifact_digest: str = Field(
        default="", description="Digest of the source input (HEAD SHA or equivalent)"
    )

    # Classification counts
    count_retained_projected: int = 0
    count_pseudonymized_disclosable: int = 0
    count_hash_evidence_only: int = 0
    count_prohibited: int = 0
    total_items: int = 0

    # Content-kind breakdown
    content_kinds_present: list[str] = Field(default_factory=list)

    # Selectively disclosable items
    selectors: list[ManifestSelector] = Field(default_factory=list)

    # Prohibition markers
    crosswalk_export_prohibited: bool = True
    credential_material_detected: bool = False
    sensitive_content_detected: bool = False
    prohibited_items_removed: int = 0

    # Assurance markers
    content_light_guarantee: bool = True
    raw_content_in_manifest: bool = False
    raw_crosswalk_in_manifest: bool = False


def compute_manifest_digest(manifest: ProtectedContentManifest) -> str:
    """Compute deterministic SHA256 of the manifest, excluding manifest_digest."""
    data = manifest.model_dump(exclude={"manifest_digest"})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seal_manifest(manifest: ProtectedContentManifest) -> None:
    """Compute and set the manifest digest."""
    manifest.manifest_digest = compute_manifest_digest(manifest)


def build_default_manifest(
    projection_id: str, bundle_digest: str, source_digest: str, created_at: str
) -> ProtectedContentManifest:
    """Build a minimal manifest with defaults for a generated bundle."""
    manifest = ProtectedContentManifest(
        projection_id=projection_id,
        bundle_digest=bundle_digest,
        source_artifact_digest=source_digest,
        created_at=created_at,
    )
    seal_manifest(manifest)
    return manifest


# ── Selector helpers ──────────────────────────────────────────────────


def compute_selector_digest(selector_id: str) -> str:
    """Content-light selector digest from the stable selector identity."""
    return "sha256:" + hashlib.sha256(selector_id.encode("utf-8")).hexdigest()


def build_selector_entries(
    pseudonymized_names: list[str], content_kind: str, disclosure_class: str
) -> list[ManifestSelector]:
    """Build content-light selector entries from pseudonymized names."""
    return [
        ManifestSelector(
            selector_id=f"{content_kind}:{disclosure_class}:{i:04d}",
            selector_digest=compute_selector_digest(
                f"{content_kind}:{disclosure_class}:{name}"
            ),
            content_kind=content_kind,
            disclosure_class=disclosure_class,
        )
        for i, name in enumerate(pseudonymized_names)
    ]


# ── Manifest serialization ────────────────────────────────────────────


def write_manifest_json(manifest: ProtectedContentManifest, path: str) -> None:
    """Write the manifest to a JSON file."""
    from pathlib import Path

    Path(path).write_text(
        json.dumps(manifest.model_dump(), indent=2, sort_keys=True), "utf-8"
    )


def load_manifest_json(path: str) -> ProtectedContentManifest | None:
    """Load and validate a manifest from a JSON file."""
    from pathlib import Path

    path_obj = Path(path)
    if not path_obj.exists():
        return None
    try:
        data = json.loads(path_obj.read_text("utf-8"))
        manifest = ProtectedContentManifest.model_validate(data)
        return manifest
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def verify_manifest_binding(
    manifest: ProtectedContentManifest, current_bundle_digest: str
) -> tuple[bool, str | None]:
    """Verify manifest is bound to the expected bundle digest."""
    if manifest.bundle_digest != current_bundle_digest:
        return False, (
            f"Bundle digest mismatch: manifest bound to "
            f"{manifest.bundle_digest[:16]}..., "
            f"current bundle is {current_bundle_digest[:16]}..."
        )
    return True, None


def verify_policy_version(
    manifest: ProtectedContentManifest,
) -> tuple[bool, str | None]:
    """Verify manifest policy version matches current policy."""
    if manifest.policy_version != POLICY_VERSION:
        return False, (
            f"Policy version mismatch: manifest uses "
            f"{manifest.policy_version}, current policy is {POLICY_VERSION}. "
            f"Regenerate the bundle and manifest."
        )
    return True, None


def verify_selector_disclosable(
    manifest: ProtectedContentManifest, selector_digest: str
) -> tuple[bool, str | None]:
    """Verify a selector is present and not yet disclosed."""
    for sel in manifest.selectors:
        if sel.selector_digest == selector_digest:
            if sel.disclosed:
                return False, f"Selector {selector_digest[:16]}... already disclosed"
            return True, None
    return False, f"Selector {selector_digest[:16]}... not found in manifest"


def mark_selector_disclosed(
    manifest: ProtectedContentManifest, selector_digest: str
) -> bool:
    """Mark a selector as disclosed. Returns True if found and marked."""
    for sel in manifest.selectors:
        if sel.selector_digest == selector_digest:
            sel.disclosed = True
            seal_manifest(manifest)
            return True
    return False


# ── Sanity checks ─────────────────────────────────────────────────────


def manifest_passes_content_light_check(manifest: ProtectedContentManifest) -> bool:
    """Ensure manifest contains no raw protected content."""
    serialized = json.dumps(manifest.model_dump(), sort_keys=True).lower()
    for forbidden in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "sk-ant", "sk-"]:
        if forbidden in serialized:
            return False
    return manifest.content_light_guarantee and not manifest.raw_content_in_manifest


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "POLICY_VERSION",
    "ContentClass",
    "ContentKind",
    "ManifestSelector",
    "ProtectedContentManifest",
    "build_default_manifest",
    "build_selector_entries",
    "classify_content_kind",
    "classify_path_kind",
    "compute_manifest_digest",
    "compute_selector_digest",
    "is_disclosure_class_prohibited",
    "load_manifest_json",
    "manifest_passes_content_light_check",
    "mark_selector_disclosed",
    "seal_manifest",
    "verify_manifest_binding",
    "verify_policy_version",
    "verify_selector_disclosable",
    "write_manifest_json",
]

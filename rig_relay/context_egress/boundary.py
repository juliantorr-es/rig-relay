from __future__ import annotations

from pathlib import Path

from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    ContextClassification,
    ProviderMode,
)
from rig_relay.core.paths._confidential_artifacts import (
    is_confidential_artifact_path,
    resolve_confidential_artifact_root,
)

_HARD_REFUSAL_PATTERNS = [
    ".env",
    "secret",
    "credential",
    "token",
    "cookie",
    "key",
    "auth",
]

_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar", ".dmg"}


def _is_hard_refused_path(path: Path) -> bool:
    name_lower = path.name.lower()
    if path.suffix in _ARCHIVE_EXTENSIONS:
        return True
    for pattern in _HARD_REFUSAL_PATTERNS:
        if pattern in name_lower:
            return True
    return False


def refuse_provider_context_input(
    path: Path | str, operation_kind: str, manifest: BoundedMissionManifest
) -> tuple[bool, str, ContextClassification]:
    p = Path(path).resolve()

    # 1. Output artifact sink restriction (Cannot use outputs as inputs)
    if is_confidential_artifact_path(p):
        return (
            True,
            "confidential_artifact_input_refused",
            ContextClassification.GENERATED_SENSITIVE_ARTIFACT_REFUSED,
        )

    # 2. Hard refusal by pattern (secrets, etc)
    if _is_hard_refused_path(p):
        return (
            True,
            "hard_refusal_pattern_matched",
            ContextClassification.SECRET_OR_CREDENTIAL_REFUSED,
        )

    # 3. Fixture-only lock for non-public modes
    if manifest.provider_mode != ProviderMode.PUBLIC_CONTEXT_ONLY:
        # It must be within an approved fixture root
        if not manifest.approved_fixture_root:
            return (
                True,
                "no_fixture_root_provided",
                ContextClassification.CONFIDENTIAL_NONTRANSMITTABLE_CONTEXT,
            )

        fixture_root = Path(manifest.approved_fixture_root).resolve()
        try:
            p.relative_to(fixture_root)
        except ValueError:
            return (
                True,
                "live_confidential_repository_input_refused",
                ContextClassification.CONFIDENTIAL_NONTRANSMITTABLE_CONTEXT,
            )

    # 4. Check explicitly approved files if provided
    if manifest.approved_file_list:
        approved = False
        for approved_file in manifest.approved_file_list:
            if p == Path(approved_file).resolve():
                approved = True
                break
        if not approved:
            return (
                True,
                "not_in_approved_file_list",
                ContextClassification.UNCLASSIFIED_REFUSED,
            )

    return False, "", ContextClassification.CONFIDENTIAL_MINIMIZABLE_CONTEXT


def validate_confidential_output_sink(
    path: Path | str, egress_decision_id: str, repo_root: Path | None = None
) -> tuple[bool, str]:
    p = Path(path).resolve()
    base_root = (
        resolve_confidential_artifact_root(repo_root)
        / "context_egress"
        / egress_decision_id
    )
    base_root = base_root.resolve()

    try:
        p.relative_to(base_root)
        return True, ""
    except ValueError:
        return (
            False,
            f"Output path {p} is not within the approved per-decision directory {base_root}",
        )

"""GitHub Provider capability loading and decision engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._models import (
    GitHubProviderAuthState,
    GitHubProviderCapability,
    GitHubProviderCapabilityDecision,
    GitHubProviderCapabilityManifest,
    GitHubVerdict,
)

_DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "json"
    / "integrations"
    / "github_provider_capability_manifest.v1.json"
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def _load_schema(schema_id: str) -> dict[str, Any]:
    path = _SCHEMAS_DIR / f"{schema_id}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_github_capability_manifest(manifest: dict[str, Any]) -> list[str]:
    import jsonschema

    schema = _load_schema("rig.github_provider.capability_manifest.v1")
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(manifest)]


def load_github_capability_manifest(
    path: Path | None = None,
) -> GitHubProviderCapabilityManifest:
    manifest_path = path or _DEFAULT_MANIFEST_PATH
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors = validate_github_capability_manifest(raw)
    if errors:
        raise ValueError(
            f"GitHub capability manifest validation failed: {'; '.join(errors)}"
        )

    caps: dict[str, GitHubProviderCapability] = {}
    for cap_raw in raw.get("capabilities", []):
        cap = GitHubProviderCapability(
            capability_id=cap_raw["capability_id"],
            operation_kind=cap_raw["operation_kind"],
            operation_class=cap_raw["operation_class"],
            required_auth_modes=cap_raw["required_auth_modes"],
            requires_step_up=cap_raw["requires_step_up"],
            requires_receipt=cap_raw["requires_receipt"],
            stores_raw_content=cap_raw["stores_raw_content"],
            content_light_output=cap_raw["content_light_output"],
            default_allowed=cap_raw["default_allowed"],
            refusal_code_when_denied=cap_raw["refusal_code_when_denied"],
        )
        caps[cap.capability_id] = cap

    return GitHubProviderCapabilityManifest(provider_id="github", capabilities=caps)


def get_capability(
    manifest: GitHubProviderCapabilityManifest, capability_id: str
) -> GitHubProviderCapability | None:
    return manifest.get_capability(capability_id)


def evaluate_github_capability(
    auth_state: GitHubProviderAuthState,
    capability_id: str,
    *,
    requested_operation_class: str | None = None,
    step_up_satisfied: bool = False,
    manifest: GitHubProviderCapabilityManifest | None = None,
) -> GitHubProviderCapabilityDecision:
    if manifest is None:
        manifest = load_github_capability_manifest()

    cap = manifest.get_capability(capability_id)
    if cap is None:
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.capability.unknown",
            reason=f"Unknown capability: {capability_id}",
            requires_step_up=False,
            step_up_satisfied=False,
        )

    if auth_state.token_material_stored:
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.invalid_token_material_stored",
            reason="Auth state claims token_material_stored=True which is forbidden",
            requires_step_up=cap.requires_step_up,
            step_up_satisfied=False,
        )

    if auth_state.token_storage_authority.value == "forbidden_json_file":
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.forbidden_storage",
            reason="Token storage authority is forbidden_json_file",
            requires_step_up=cap.requires_step_up,
            step_up_satisfied=False,
        )

    if cap.is_destructive:
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code=cap.refusal_code_when_denied,
            reason="Destructive remote mutation is refused in v0",
            requires_step_up=True,
            step_up_satisfied=False,
        )

    if cap.is_credentialed:
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code=cap.refusal_code_when_denied,
            reason="Credentialed remote mutation is refused in v0",
            requires_step_up=True,
            step_up_satisfied=False,
        )

    if cap.is_read_only and cap.allows_auth_mode("none"):
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.ALLOWED,
            refusal_code="",
            reason="Read-only capability allowed with unauthenticated access",
            requires_step_up=False,
            step_up_satisfied=False,
        )

    if not auth_state.is_authenticated():
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.unauthenticated",
            reason="Auth state is not authenticated and capability requires auth",
            requires_step_up=cap.requires_step_up,
            step_up_satisfied=False,
        )

    if not auth_state.is_usable():
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.not_usable",
            reason="Auth state is not usable",
            requires_step_up=cap.requires_step_up,
            step_up_satisfied=False,
        )

    if not cap.allows_auth_mode(auth_state.auth_mode.value):
        return GitHubProviderCapabilityDecision(
            capability_id=capability_id,
            verdict=GitHubVerdict.REFUSED,
            refusal_code="github.auth.mode_not_allowed",
            reason=f"Auth mode {auth_state.auth_mode.value} not in required modes: {cap.required_auth_modes}",
            requires_step_up=cap.requires_step_up,
            step_up_satisfied=False,
        )

    if cap.is_mutation:
        if cap.requires_step_up and not step_up_satisfied:
            return GitHubProviderCapabilityDecision(
                capability_id=capability_id,
                verdict=GitHubVerdict.REFUSED,
                refusal_code=cap.refusal_code_when_denied,
                reason="Mutation requires step-up approval which is not satisfied in v0",
                requires_step_up=True,
                step_up_satisfied=False,
            )
        if not step_up_satisfied and not cap.default_allowed:
            return GitHubProviderCapabilityDecision(
                capability_id=capability_id,
                verdict=GitHubVerdict.REFUSED,
                refusal_code=cap.refusal_code_when_denied,
                reason="Mutation capability default is refused",
                requires_step_up=cap.requires_step_up,
                step_up_satisfied=False,
            )

    return GitHubProviderCapabilityDecision(
        capability_id=capability_id,
        verdict=GitHubVerdict.ALLOWED,
        refusal_code="",
        reason="Capability allowed",
        requires_step_up=cap.requires_step_up,
        step_up_satisfied=step_up_satisfied,
    )

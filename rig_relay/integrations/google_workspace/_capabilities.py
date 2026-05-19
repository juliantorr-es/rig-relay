"""Google Workspace capability loading and decision engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceCapability,
    GoogleWorkspaceCapabilityManifest,
    GoogleWorkspaceDecision,
    GoogleWorkspaceVerdict,
)

_DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "json"
    / "integrations"
    / "google_workspace_capability_manifest.v1.json"
)
_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def _load_schema(schema_id: str) -> dict[str, Any]:
    return json.loads(
        (_SCHEMAS_DIR / f"{schema_id}.schema.json").read_text(encoding="utf-8")
    )


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    import jsonschema

    schema = _load_schema("rig.google_workspace.capability_manifest.v1")
    v = jsonschema.Draft7Validator(schema)
    return [e.message for e in v.iter_errors(manifest)]


def load_capability_manifest(
    path: Path | None = None,
) -> GoogleWorkspaceCapabilityManifest:
    raw = json.loads((path or _DEFAULT_MANIFEST_PATH).read_text(encoding="utf-8"))
    errors = validate_manifest(raw)
    if errors:
        raise ValueError(f"Manifest validation failed: {'; '.join(errors)}")
    caps = {}
    for c in raw.get("capabilities", []):
        cap = GoogleWorkspaceCapability(
            capability_id=c["capability_id"],
            product=c["product"],
            operation_kind=c.get("operation_kind", ""),
            operation_class=c.get("operation_class", "public_read"),
            required_scopes=c.get("required_scopes", []),
            required_auth_modes=c.get("required_auth_modes", []),
            required_boundary=c.get("required_boundary", "none"),
            scope_sensitivity=c.get("scope_sensitivity", "non_sensitive"),
            default_allowed=c.get("default_allowed", False),
            mutation_class=c.get("mutation_class", "none"),
            refusal_codes=c.get("refusal_codes", []),
            requires_domain_wide_delegation=c.get(
                "requires_domain_wide_delegation", False
            ),
            requires_user_subject=c.get("requires_user_subject", False),
            requires_customer_boundary=c.get("requires_customer_boundary", False),
            local_fixture_supported=c.get("local_fixture_supported", False),
        )
        caps[cap.capability_id] = cap
    return GoogleWorkspaceCapabilityManifest(capabilities=caps)


def evaluate_workspace_capability(
    auth: GoogleWorkspaceAuthState,
    capability_id: str,
    *,
    subject_hash: str = "",
    customer_hash: str = "",
    resource_hash: str = "",
    manifest: GoogleWorkspaceCapabilityManifest | None = None,
) -> GoogleWorkspaceDecision:
    if manifest is None:
        manifest = load_capability_manifest()

    cap = manifest.get_capability(capability_id)
    if cap is None:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.capability.unknown",
            f"Unknown capability: {capability_id}",
        )

    if auth.token_material_stored:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.auth.raw_token_material_refused",
            "Raw token stored in auth state",
        )

    if str(cap.operation_class) in {
        "destructive_mutation",
        "credentialed_live_operation",
    }:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.live_network.refused",
            f"Operation class {cap.operation_class} refused in v1",
        )

    if str(cap.mutation_class) in {
        "user_credentialed",
        "domain_credentialed",
        "destructive",
    }:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.mutation.refused",
            "Mutation refused in v1",
        )

    if (
        cap.requires_domain_wide_delegation
        and not auth.domain_wide_delegation_authorized
    ):
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.delegation.not_authorized",
            "Domain-wide delegation not authorized",
        )

    if str(cap.scope_sensitivity) == "restricted":
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.scope.restricted_security_assessment_required",
            "Restricted scope requires security assessment",
        )

    if str(cap.scope_sensitivity) in {"admin_restricted", "unknown"}:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.scope.sensitivity_refused",
            f"Scope sensitivity {cap.scope_sensitivity} refused",
        )

    if not auth.is_authenticated() and "none" not in cap.required_auth_modes:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.auth.unauthenticated",
            "Auth state not authenticated",
        )

    if auth.is_authenticated() and not auth.is_usable():
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.auth.not_usable",
            "Auth state not usable",
        )

    if auth.is_authenticated() and str(auth.auth_mode) not in cap.required_auth_modes:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.auth.mode_not_allowed",
            f"Auth mode {auth.auth_mode} not allowed",
        )

    active = auth.active_grants()
    for g in auth.scope_grants:
        if g.scope_id in cap.required_scopes:
            if str(g.grant_status) == "expired":
                return GoogleWorkspaceDecision(
                    capability_id,
                    GoogleWorkspaceVerdict.REFUSED,
                    "google.scope.expired",
                    f"Scope grant {g.scope_id} expired",
                )
            if str(g.grant_status) == "revoked":
                return GoogleWorkspaceDecision(
                    capability_id,
                    GoogleWorkspaceVerdict.REFUSED,
                    "google.scope.revoked",
                    f"Scope grant {g.scope_id} revoked",
                )

    has_scope = any(s.scope_id in cap.required_scopes for s in active)
    if cap.required_scopes and not has_scope:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.scope.missing",
            f"Required scopes not in active grants: {cap.required_scopes}",
        )

    for g in active:
        if str(g.grant_status) == "expired":
            return GoogleWorkspaceDecision(
                capability_id,
                GoogleWorkspaceVerdict.REFUSED,
                "google.scope.expired",
                f"Scope grant {g.scope_id} expired",
            )
        if str(g.grant_status) == "revoked":
            return GoogleWorkspaceDecision(
                capability_id,
                GoogleWorkspaceVerdict.REFUSED,
                "google.scope.revoked",
                f"Scope grant {g.scope_id} revoked",
            )

    if cap.requires_user_subject and not subject_hash:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.subject.missing",
            "User subject hash required",
        )
    if (
        cap.requires_user_subject
        and subject_hash
        and subject_hash not in auth.subject_hashes
    ):
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.subject.access_denied",
            "Subject hash not in authorized subjects",
        )

    if cap.requires_customer_boundary and not customer_hash:
        return GoogleWorkspaceDecision(
            capability_id,
            GoogleWorkspaceVerdict.REFUSED,
            "google.customer.missing",
            "Customer boundary hash required",
        )

    return GoogleWorkspaceDecision(
        capability_id, GoogleWorkspaceVerdict.ALLOWED, "", "Capability allowed"
    )

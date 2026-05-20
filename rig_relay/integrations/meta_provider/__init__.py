"""Meta Provider Implementation v1 — inventory, refusal, safety substrate.

No live Meta OAuth. No Meta App JWT. No token exchange. No webhooks.
No Meta API network calls. No credential storage. No publishing. No messaging.

Provides:
- Operating picture: local-only, schema-valid view of Meta surfaces/configuration/refusal
- Permissions inventory: static permission map with review-risk analysis
- Surface audit: future packet planner, refusal-first posture

Usage:
    from rig_relay.integrations.meta_provider import (
        MetaOperatingPictureError,
        build_meta_operating_picture,
        build_meta_operating_picture_from_paths,
        write_meta_operating_picture,
        MetaPermissionsInventoryError,
        build_meta_permissions_inventory,
        build_meta_permissions_inventory_from_paths,
        write_meta_permissions_inventory,
        MetaSurfaceAuditError,
        build_meta_surface_audit,
        build_meta_surface_audit_from_paths,
        write_meta_surface_audit,
    )
"""

from __future__ import annotations

from rig_relay.integrations.meta_provider._operating_picture import (
    MetaOperatingPictureError,
    build_meta_operating_picture,
    build_meta_operating_picture_from_paths,
    write_meta_operating_picture,
)
from rig_relay.integrations.meta_provider._permissions_inventory import (
    MetaPermissionsInventoryError,
    build_meta_permissions_inventory,
    build_meta_permissions_inventory_from_paths,
    write_meta_permissions_inventory,
)
from rig_relay.integrations.meta_provider._surface_audit import (
    MetaSurfaceAuditError,
    build_meta_surface_audit,
    build_meta_surface_audit_from_paths,
    write_meta_surface_audit,
)

__all__ = [
    "MetaOperatingPictureError",
    "MetaPermissionsInventoryError",
    "MetaSurfaceAuditError",
    "build_meta_operating_picture",
    "build_meta_operating_picture_from_paths",
    "build_meta_permissions_inventory",
    "build_meta_permissions_inventory_from_paths",
    "build_meta_surface_audit",
    "build_meta_surface_audit_from_paths",
    "write_meta_operating_picture",
    "write_meta_permissions_inventory",
    "write_meta_surface_audit",
]

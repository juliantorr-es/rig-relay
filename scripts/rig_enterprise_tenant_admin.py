#!/usr/bin/env python3
"""Rig Enterprise Tenant Admin CLI.

Register, list, grant/revoke permissions, and inspect tenant topology.

Usage:
    uv run python scripts/rig_enterprise_tenant_admin.py --register --tenant-id acme-corp --scope isolated
    uv run python scripts/rig_enterprise_tenant_admin.py --list
    uv run python scripts/rig_enterprise_tenant_admin.py --grant --tenant-id acme-corp --permission execute_live_mutation
    uv run python scripts/rig_enterprise_tenant_admin.py --revoke --tenant-id acme-corp --permission execute_live_mutation
    uv run python scripts/rig_enterprise_tenant_admin.py --topology --tenant-id acme-corp
    uv run python scripts/rig_enterprise_tenant_admin.py --cross-tenant-summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rig_relay.enterprise.tenancy import Tenant, TenantRegistry, TenantScope
from rig_relay.enterprise.tenant_permissions import (
    TenantPermission,
    TenantPermissionEvaluator,
)
from rig_relay.enterprise.tenant_topology import TenantTopologyProjection

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / ".build" / "rig-relay" / "tenants" / "registry.v1.json"
CONFIG_DIR = REPO_ROOT / ".build" / "rig-relay" / "tenants"


def _load_registry() -> TenantRegistry:
    registry = TenantRegistry()
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        tenants_raw = data.get("tenants", {})
        for _tid, tdata in tenants_raw.items():
            tenant = Tenant(
                tenant_id=tdata["tenant_id"],
                scope=TenantScope(tdata["scope"]),
                permissions=tdata.get("permissions", []),
                active=tdata.get("active", True),
            )
            registry.register(tenant)
    return registry


def _save_registry(registry: TenantRegistry) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tenants_data: dict[str, dict[str, Any]] = {}
    for tid, tenant in registry.tenants.items():
        tenants_data[tid] = {
            "tenant_id": tenant.tenant_id,
            "scope": tenant.scope,
            "event_log_path": str(tenant.event_log_path),
            "topology_path": str(tenant.topology_path),
            "permissions": list(tenant.permissions),
            "active": tenant.active,
        }
    doc: dict[str, Any] = {
        "schema_version": "rig.enterprise.tenant_registry.v1",
        "generated_at": (
            __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat()
        ),
        "tenants": tenants_data,
        "content_light": True,
        "mutation_authority": False,
    }
    REGISTRY_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def cmd_register(args: argparse.Namespace) -> int:
    registry = _load_registry()
    if registry.get(args.tenant_id) is not None:
        print(f"Tenant '{args.tenant_id}' already registered.")
        return 0

    tenant = Tenant(tenant_id=args.tenant_id, scope=TenantScope(args.scope))
    registry.register(tenant)

    config_dir = CONFIG_DIR / args.tenant_id
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(
        f"# Tenant config: {args.tenant_id}\n"
        f'tenant_id = "{args.tenant_id}"\n'
        f'scope = "{args.scope}"\n'
        f"active = true\n",
        encoding="utf-8",
    )

    _save_registry(registry)
    print(f"Registered tenant '{args.tenant_id}' with scope '{args.scope}'")

    if args.summary:
        topology = TenantTopologyProjection(registry)
        ttopo = topology.build_tenant_topology(args.tenant_id)
        rows = [
            ("tenant_id", args.tenant_id),
            ("scope", args.scope),
            ("permissions", str(tenant.permissions)),
            ("event_log_path", str(tenant.event_log_path)),
            ("topology_path", str(tenant.topology_path)),
            ("active", str(tenant.active)),
            ("topology_status", ttopo.get("status", "")),
            ("topology_nodes", str(len(ttopo.get("nodes", [])))),
        ]
        width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"  {label:<{width}}  {value}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    registry = _load_registry()
    active = registry.list_active()
    if not active:
        print("No active tenants registered.")
        return 0

    width = max(len(t.tenant_id) for t in active)
    print(f"{'Tenant ID':<{width}}  Scope         Permissions  Active")
    print(f"{'-' * width}  ------------  -----------  ------")
    for t in active:
        perms = ", ".join(t.permissions) if t.permissions else "-"
        print(f"{t.tenant_id:<{width}}  {t.scope:<12}  {perms:<11}  {t.active}")
    return 0


def cmd_grant(args: argparse.Namespace) -> int:
    registry = _load_registry()
    evaluator = TenantPermissionEvaluator(registry)

    perm_map: dict[str, TenantPermission] = {
        "read_event_fabric": TenantPermission.READ_EVENT_FABRIC,
        "publish_event": TenantPermission.PUBLISH_EVENT,
        "view_topology": TenantPermission.VIEW_TOPOLOGY,
        "execute_live_mutation": TenantPermission.EXECUTE_LIVE_MUTATION,
        "modify_gates": TenantPermission.MODIFY_GATES,
        "cross_tenant_view": TenantPermission.CROSS_TENANT_VIEW,
    }

    perm = perm_map.get(args.permission)
    if perm is None:
        print(f"Unknown permission: {args.permission}")
        print(f"Valid: {', '.join(sorted(perm_map))}")
        return 1

    try:
        evaluator.grant(args.tenant_id, perm)
    except PermissionError as e:
        print(f"ERROR: {e}")
        return 1
    except KeyError as e:
        print(f"ERROR: {e}")
        return 1

    _save_registry(registry)
    print(f"Granted '{args.permission}' to tenant '{args.tenant_id}'")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    registry = _load_registry()
    evaluator = TenantPermissionEvaluator(registry)

    perm_map: dict[str, TenantPermission] = {
        "read_event_fabric": TenantPermission.READ_EVENT_FABRIC,
        "publish_event": TenantPermission.PUBLISH_EVENT,
        "view_topology": TenantPermission.VIEW_TOPOLOGY,
        "execute_live_mutation": TenantPermission.EXECUTE_LIVE_MUTATION,
        "modify_gates": TenantPermission.MODIFY_GATES,
        "cross_tenant_view": TenantPermission.CROSS_TENANT_VIEW,
    }

    perm = perm_map.get(args.permission)
    if perm is None:
        print(f"Unknown permission: {args.permission}")
        return 1

    try:
        evaluator.revoke(args.tenant_id, perm)
    except PermissionError as e:
        print(f"ERROR: {e}")
        return 1
    except KeyError as e:
        print(f"ERROR: {e}")
        return 1

    _save_registry(registry)
    print(f"Revoked '{args.permission}' from tenant '{args.tenant_id}'")
    return 0


def cmd_topology(args: argparse.Namespace) -> int:
    registry = _load_registry()
    topology = TenantTopologyProjection(registry)
    proj = topology.build_tenant_topology(args.tenant_id)
    print(json.dumps(proj, indent=2, ensure_ascii=False))
    return 0


def cmd_cross_tenant_summary(args: argparse.Namespace) -> int:
    registry = _load_registry()
    topology = TenantTopologyProjection(registry)
    proj = topology.build_cross_tenant_summary()
    summary = proj.get("cross_tenant_summary", {})
    rows = [
        ("total_tenants", str(summary.get("total_tenants", 0))),
        ("healthy_tenants", str(summary.get("healthy_tenants", 0))),
        ("degraded_tenants", str(summary.get("degraded_tenants", 0))),
        ("tenant_health_map", json.dumps(summary.get("tenant_health_map", {}))),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rig-enterprise-tenant-admin",
        description="Rig Enterprise Tenant Admin: register, list, manage permissions, inspect topology.",
    )
    sub = parser.add_subparsers(dest="command")

    reg = sub.add_parser("register", help="Register a new tenant")
    reg.add_argument("--tenant-id", required=True, help="Tenant identifier")
    reg.add_argument(
        "--scope",
        choices=["isolated", "shared_read", "public"],
        default="isolated",
        help="Tenant scope",
    )
    reg.add_argument(
        "--summary",
        action="store_true",
        help="Print compact summary after registration",
    )

    sub.add_parser("list", help="List all active tenants")

    grant = sub.add_parser("grant", help="Grant a permission to a tenant")
    grant.add_argument("--tenant-id", required=True)
    grant.add_argument("--permission", required=True)

    revoke = sub.add_parser("revoke", help="Revoke a permission from a tenant")
    revoke.add_argument("--tenant-id", required=True)
    revoke.add_argument("--permission", required=True)

    topo = sub.add_parser("topology", help="Build tenant topology projection")
    topo.add_argument("--tenant-id", required=True)

    sub.add_parser("cross-tenant-summary", help="Build cross-tenant aggregate summary")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    match args.command:
        case "register":
            return cmd_register(args)
        case "list":
            return cmd_list(args)
        case "grant":
            return cmd_grant(args)
        case "revoke":
            return cmd_revoke(args)
        case "topology":
            return cmd_topology(args)
        case "cross-tenant-summary":
            return cmd_cross_tenant_summary(args)
        case None:
            print("No command specified. Use --help for usage.")
            return 1
        case _:
            print(f"Unknown command: {args.command}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

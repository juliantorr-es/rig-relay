#!/usr/bin/env python3
"""Rig Enterprise Fleet Admin — CLI for fleet management.

Usage:
    uv run python scripts/rig_enterprise_fleet_admin.py --start-all
    uv run python scripts/rig_enterprise_fleet_admin.py --status
    uv run python scripts/rig_enterprise_fleet_admin.py --restart-degraded
    uv run python scripts/rig_enterprise_fleet_admin.py --stop-all
"""

from __future__ import annotations

import argparse
import json

from rig_relay.enterprise.fleet_controller import FleetController


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rig Enterprise Fleet Admin")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--start-all",
        nargs="*",
        metavar="TENANT_ID",
        help="Start bridge instances for listed tenant IDs (or demo tenants if none listed).",
    )
    group.add_argument(
        "--status", action="store_true", help="Print fleet status as JSON."
    )
    group.add_argument(
        "--restart-degraded",
        action="store_true",
        help="Stop and restart all instances in DEGRADED or DISCONNECTED state.",
    )
    group.add_argument(
        "--stop-all", action="store_true", help="Stop all running bridge instances."
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    controller = FleetController()

    if args.start_all is not None:
        tenant_ids = (
            args.start_all if args.start_all else ["demo-tenant-1", "demo-tenant-2"]
        )
        for tid in tenant_ids:
            try:
                instance = controller.start_instance(tid)
                print(
                    f"Started instance_id={instance.instance_id} "
                    f"tenant={instance.tenant_id} port={instance.port} "
                    f"pid={instance.pid} state={instance.state.value}"
                )
            except RuntimeError as e:
                print(f"SKIP tenant={tid}: {e}")
        return 0

    if args.status:
        print(json.dumps(controller.fleet_status(), indent=2))
        return 0

    if args.restart_degraded:
        restarted = controller.restart_degraded()
        if restarted:
            print(f"Restarted {len(restarted)} instances: {restarted}")
        else:
            print("No degraded or disconnected instances to restart.")
        return 0

    if args.stop_all:
        if not controller.instances:
            print("No running instances to stop.")
            return 0
        count = len(controller.instances)
        controller.stop_all()
        print(f"Stopped {count} instances.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

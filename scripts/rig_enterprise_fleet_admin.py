#!/usr/bin/env python3
"""Rig Enterprise Fleet Admin — CLI for fleet management.

Usage:
    uv run python scripts/rig_enterprise_fleet_admin.py --start-all
    uv run python scripts/rig_enterprise_fleet_admin.py --status
    uv run python scripts/rig_enterprise_fleet_admin.py --restart-degraded
    uv run python scripts/rig_enterprise_fleet_admin.py --stop-all

All mutation operations default to dry-run.
Pass --execute to perform actual start/stop/restart operations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rig_relay.cli.governance_guard import (
    GovernedExecution,
    emit_structured_result,
    require_governed_execution_with_evidence,
)
from rig_relay.enterprise.fleet_controller import FleetController

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_JSON = REPO_ROOT / ".build" / "rig-relay" / "cli" / "fleet_admin_result.json"


def _write_json_output(data: dict) -> None:
    RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rig Enterprise Fleet Admin")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute fleet mutations. Default is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON output.",
    )
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


def _handle_governed_mutation(
    args: argparse.Namespace,
    governed: GovernedExecution,
    script_name: str,
    capability_id: str,
) -> int | None:
    """Handle governance result for a mutation operation.

    Returns 0 if dry-run, 1 if blocked, None if mutation should proceed.
    """
    if args.execute and governed.decision.decision.value in {
        "blocked",
        "requires_review",
    }:
        result = emit_structured_result(
            script_name=script_name,
            authority_tier="admin_configuration",
            capability_id=capability_id,
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=governed.can_execute,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            _write_json_output(result)
            print(json.dumps(result, indent=2))
        else:
            d = governed.decision
            print(f"BLOCKED: {d.decision.value}")
            for r in d.reasons:
                print(f"  {r.code}: {r.message}")
            if governed.evidence_status == "persistence_failed":
                print("  EVIDENCE: persistence failed — mutation blocked (fail-closed)")
        return 1

    if not args.execute:
        return 0

    if not governed.can_execute:
        result = emit_structured_result(
            script_name=script_name,
            authority_tier="admin_configuration",
            capability_id=capability_id,
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="blocked_by_governance",
            can_execute=False,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        if args.json:
            _write_json_output(result)
            print(json.dumps(result, indent=2))
        else:
            print(f"BLOCKED: evidence persistence failed (fail-closed)")
        return 1

    return None


def _emit_executed_result(
    args: argparse.Namespace,
    governed: GovernedExecution,
    script_name: str,
    capability_id: str,
) -> None:
    if args.json:
        result = emit_structured_result(
            script_name=script_name,
            authority_tier="admin_configuration",
            capability_id=capability_id,
            dry_run=False,
            execute_requested=True,
            decision=governed.decision,
            status="executed",
            can_execute=governed.can_execute,
            evidence_ref=governed.evidence_ref,
            evidence_status=governed.evidence_status,
        )
        _write_json_output(result)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    controller = FleetController()

    if args.start_all is not None:
        governed = require_governed_execution_with_evidence(
            script_name="rig_enterprise_fleet_admin/start",
            authority_tier="admin_configuration",
            capability_id="fleet_start",
            execute_requested=args.execute,
        )
        gate = _handle_governed_mutation(
            args, governed, "rig_enterprise_fleet_admin/start", "fleet_start"
        )
        if gate is not None:
            if gate == 0:
                tenant_ids_msg = (
                    args.start_all
                    if args.start_all
                    else ["demo-tenant-1", "demo-tenant-2"]
                )
                print(
                    f"DRY-RUN: Would start instances for tenants: {tenant_ids_msg}. "
                    f"Pass --execute to proceed."
                )
                if args.json:
                    result = emit_structured_result(
                        script_name="rig_enterprise_fleet_admin/start",
                        authority_tier="admin_configuration",
                        capability_id="fleet_start",
                        dry_run=True,
                        execute_requested=False,
                        decision=governed.decision,
                        status="dry_run",
                    )
                    _write_json_output(result)
                    print(json.dumps(result, indent=2))
            return gate

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
        _emit_executed_result(
            args, governed, "rig_enterprise_fleet_admin/start", "fleet_start"
        )
        return 0

    if args.status:
        status_json = controller.fleet_status()
        print(json.dumps(status_json, indent=2))
        return 0

    if args.restart_degraded:
        governed = require_governed_execution_with_evidence(
            script_name="rig_enterprise_fleet_admin/restart",
            authority_tier="admin_configuration",
            capability_id="fleet_restart",
            execute_requested=args.execute,
        )
        gate = _handle_governed_mutation(
            args, governed, "rig_enterprise_fleet_admin/restart", "fleet_restart"
        )
        if gate is not None:
            if gate == 0:
                print(
                    "DRY-RUN: Would restart degraded/disconnected instances. "
                    "Pass --execute to proceed."
                )
                if args.json:
                    result = emit_structured_result(
                        script_name="rig_enterprise_fleet_admin/restart",
                        authority_tier="admin_configuration",
                        capability_id="fleet_restart",
                        dry_run=True,
                        execute_requested=False,
                        decision=governed.decision,
                        status="dry_run",
                    )
                    _write_json_output(result)
                    print(json.dumps(result, indent=2))
            return gate
        restarted = controller.restart_degraded()
        if restarted:
            print(f"Restarted {len(restarted)} instances: {restarted}")
        else:
            print("No degraded or disconnected instances to restart.")
        return 0

    if args.stop_all:
        governed = require_governed_execution_with_evidence(
            script_name="rig_enterprise_fleet_admin/stop",
            authority_tier="admin_configuration",
            capability_id="fleet_stop",
            execute_requested=args.execute,
        )
        gate = _handle_governed_mutation(
            args, governed, "rig_enterprise_fleet_admin/stop", "fleet_stop"
        )
        if gate is not None:
            if gate == 0:
                print(
                    "DRY-RUN: Would stop all running instances. "
                    "Pass --execute to proceed."
                )
                if args.json:
                    result = emit_structured_result(
                        script_name="rig_enterprise_fleet_admin/stop",
                        authority_tier="admin_configuration",
                        capability_id="fleet_stop",
                        dry_run=True,
                        execute_requested=False,
                        decision=governed.decision,
                        status="dry_run",
                    )
                    _write_json_output(result)
                    print(json.dumps(result, indent=2))
            return gate
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

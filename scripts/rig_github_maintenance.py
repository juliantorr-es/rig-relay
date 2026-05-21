#!/usr/bin/env python3
"""Rig Relay GitHub integration periodic maintenance CLI."""

from __future__ import annotations

import argparse

from rig_relay.integrations.github_provider._github_maintenance import (
    refresh_claims_index,
    refresh_evidence_graph,
    refresh_profile_readme,
    refresh_security_queue,
    refresh_surface_probes,
    run_full_maintenance,
)


def _print_summary(results: dict[str, object]) -> None:
    print("\nGitHub Maintenance Report")
    print("-" * 26)
    summary = results.get("summary")
    if isinstance(summary, dict):
        print(f"  tasks_run:       {summary.get('tasks_run', 0)}")
        print(f"  tasks_refreshed: {summary.get('tasks_refreshed', 0)}")
    tasks = results.get("tasks")
    if isinstance(tasks, dict):
        for name, task in tasks.items():
            if isinstance(task, dict):
                status = "✓" if task.get("refreshed") else "✗"
                print(f"  {name}: {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-github-maintenance",
        description="GitHub integration periodic maintenance.",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("all", help="Run all maintenance tasks.")
    sub.add_parser("claims", help="Refresh claims index.")
    sub.add_parser("queue", help="Refresh security queue.")
    sub.add_parser("graph", help="Refresh codebase evidence graph.")
    sub.add_parser("profile", help="Refresh profile README.")
    sub.add_parser("surfaces", help="Refresh surface probes.")
    args = parser.parse_args(argv)

    if args.cmd == "claims":
        r = refresh_claims_index()
        print(r)
    elif args.cmd == "queue":
        r = refresh_security_queue()
        print(r)
    elif args.cmd == "graph":
        r = refresh_evidence_graph()
        print(r)
    elif args.cmd == "profile":
        r = refresh_profile_readme()
        print(r)
    elif args.cmd == "surfaces":
        r = refresh_surface_probes()
        print(r)
    else:
        r = run_full_maintenance()
        _print_summary(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

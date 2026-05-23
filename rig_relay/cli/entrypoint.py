"""Relay-owned entry point dispatcher.

Launches the Rig Relay Desktop by default.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path

_STEWARD_TERMINAL_STATES = frozenset({"no_action", "blocked", "audit_unblock_plan"})


def _steward_project_root(args_list: list[str]) -> Path:
    if "--project-root" in args_list:
        index = args_list.index("--project-root")
        if index + 1 < len(args_list):
            return Path(args_list[index + 1]).resolve()
    return Path.cwd().resolve()


def _steward_last_run_path(project_root: Path) -> Path:
    return (
        project_root
        / ".build"
        / "rig-relay"
        / "derived"
        / "opencode_idle_steward_last_run_v1.json"
    )


def _steward_state_from_last_run(last_run_path: Path) -> str:
    try:
        payload = json.loads(last_run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(payload.get("steward_state", ""))


def _print_steward_cycle_summary(cycle: int, last_run_path: Path) -> str:
    try:
        payload = json.loads(last_run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"steward cycle {cycle}: unknown")
        return "unknown"

    state = str(payload.get("steward_state", "")) or "unknown"
    dry_run = bool(payload.get("dry_run"))
    selected = payload.get("selected_task") or {}
    selected_task_id = str(selected.get("task_id", "")).strip()
    title = str(selected.get("title", "")).strip()

    if state == "advance_to_next_lane":
        action = "planned next task" if dry_run else "dispatched next task"
        task_bits: list[str] = []
        if selected_task_id:
            task_bits.append(selected_task_id)
        if title and title != selected_task_id:
            task_bits.append(title)
        task_text = " - ".join(task_bits)
        if task_text:
            print(f"steward cycle {cycle}: {action} {task_text}")
        else:
            print(f"steward cycle {cycle}: {action}")
        return state

    if state == "no_action":
        print(f"steward cycle {cycle}: no runnable work remains")
        return state

    if state == "blocked":
        reasons = [
            str(reason).strip() for reason in payload.get("blocker_reasons") or []
        ]
        reasons_text = ", ".join(reason for reason in reasons if reason)
        if reasons_text:
            print(f"steward cycle {cycle}: blocked ({reasons_text})")
        else:
            print(f"steward cycle {cycle}: blocked")
        return state

    if state == "audit_unblock_plan":
        print(f"steward cycle {cycle}: needs unblock plan")
        return state

    print(f"steward cycle {cycle}: {state}")
    return state


def _run_steward_until_terminal(args_list: list[str]) -> int:
    from rig_relay.cli.steward import main as steward_main

    subcommands = {
        "impact",
        "explain",
        "validate-plan",
        "handoff",
        "check-write",
        "record-observation",
    }
    if args_list and args_list[0] in subcommands:
        return steward_main(args_list)

    project_root = _steward_project_root(args_list)
    last_run_path = _steward_last_run_path(project_root)
    dry_run = "--dry-run" in args_list
    cycle = 0

    while True:
        cycle += 1
        exit_code = steward_main(args_list)
        state = _print_steward_cycle_summary(cycle, last_run_path)
        if exit_code != 0 or dry_run:
            return exit_code
        if state in _STEWARD_TERMINAL_STATES:
            return exit_code


def main(argv: Sequence[str] | None = None) -> None:
    import sys as _sys

    args_list = list(argv) if argv is not None else _sys.argv[1:]

    if args_list:
        match args_list[0]:
            case "start":
                from rig_relay.cli.desktop_cockpit import main as cockpit_main

                cockpit_main(args_list[1:])
                return
            case "stop":
                print(
                    "Service stop requested. Use SIGTERM or close the cockpit window."
                )
                return
            case "status":
                import json as _json

                from rig_relay.governance.service_state import get_capability_gate

                gate = get_capability_gate()
                summary = gate.state_summary()
                print(_json.dumps(summary, indent=2))
                return
            case "doctor":
                from rig_relay.cli.doctor import main as doctor_main

                doctor_main(args_list[1:])
                return
            case "steward":
                _sys.exit(_run_steward_until_terminal(args_list[1:]))
                return
            case "issues":
                from rig_relay.cli.issues import main as issues_main

                _sys.exit(issues_main(args_list[1:]))
                return

    from rig_relay.cli.desktop_cockpit import main as cockpit_main

    cockpit_main(args_list)


__all__ = ["main"]


if __name__ == "__main__":
    main()

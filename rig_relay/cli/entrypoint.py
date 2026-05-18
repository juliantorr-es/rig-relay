"""Relay-owned entry point dispatcher.

Launches the Rig Relay Desktop by default.
"""

from __future__ import annotations

from collections.abc import Sequence


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

    from rig_relay.cli.desktop_cockpit import main as cockpit_main

    cockpit_main(args_list)


__all__ = ["main"]

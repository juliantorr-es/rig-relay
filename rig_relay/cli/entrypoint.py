"""Relay-owned entry point dispatcher.

Launches the Rig Relay Desktop by default.
"""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    import sys as _sys

    args_list = list(argv) if argv is not None else _sys.argv[1:]
    from rig_relay.cli.desktop_cockpit import main as cockpit_main

    cockpit_main(args_list)


__all__ = ["main"]

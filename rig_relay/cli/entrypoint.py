"""Relay-owned entry point dispatcher.

Default: launch the Textual Rig Console cockpit.
Explicit legacy path: ``rig-relay legacy`` or ``rig-relay run``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import sys

from vibe.cli.entrypoint import main as legacy_cli_main
from vibe.cli.textual_ui.rig_console.console_app import main as rig_console_main


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rig-relay",
        description="Rig Relay default cockpit launcher.",
        epilog=(
            "Default behavior: launch the Textual Rig Console.\n"
            "Use `rig-relay legacy` or `rig-relay run` for the legacy CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "legacy", help="Run the legacy interactive/programmatic CLI entrypoint"
    )
    subparsers.add_parser(
        "run", help="Alias for the legacy interactive/programmatic CLI entrypoint"
    )
    return parser


def _dispatch(command: str | None, argv: list[str]) -> None:
    if command in {"legacy", "run"}:
        with _argv(argv):
            legacy_cli_main()
        return
    rig_console_main(argv)


@contextmanager
def _argv(argv: list[str]) -> Iterator[None]:
    original = sys.argv
    sys.argv = [original[0], *argv]
    try:
        yield
    finally:
        sys.argv = original


def main(argv: Sequence[str] | None = None) -> None:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_arg_parser()
    args, remainder = parser.parse_known_args(args_list)
    _dispatch(args.command, remainder)


__all__ = ["build_arg_parser", "main"]

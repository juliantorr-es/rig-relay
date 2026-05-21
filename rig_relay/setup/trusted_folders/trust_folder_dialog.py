"""Console-based trusted folder dialog — replacement for deleted Textual TUI version."""

from __future__ import annotations

from pathlib import Path

from rich import print as rprint
from rich.panel import Panel


class TrustDialogQuitException(Exception):
    pass


def ask_trust_folder(cwd: Path, detected_files: list[Path]) -> bool:
    """Ask the user whether to trust the current working directory.

    Args:
        cwd: The working directory to check.
        detected_files: Trustable files found in the directory.

    Returns:
        True if the folder is trusted, False otherwise.
    """
    rprint()
    rprint(
        Panel(
            f"[bold]Untrusted directory: {cwd}[/]\n\n"
            f"This directory contains {len(detected_files)} trustable file(s).\n\n"
            "Trust this directory to allow Rig Relay to read and write files here?",
            border_style="yellow",
        )
    )
    rprint()
    rprint(
        "[bold]Trust this directory?[/] ([green]y[/]/[red]n[/], default: n): ", end=""
    )
    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise TrustDialogQuitException() from None

    if choice in {"y", "yes"}:
        rprint("[green]Directory trusted.[/]")
        return True

    rprint("[yellow]Directory not trusted.[/]")
    return False

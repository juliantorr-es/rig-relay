from __future__ import annotations

# Derived from mistralai/mistral-vibe. Modified for Rig Relay.
import argparse
import os
from pathlib import Path
import sys

from rich import print as rprint

from vibe import __version__
from vibe.core.config.harness_files import init_harness_files_manager
from vibe.core.trusted_folders import find_trustable_files, trusted_folders_manager
from vibe.setup.trusted_folders.trust_folder_dialog import (
    TrustDialogQuitException,
    ask_trust_folder,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Rig Relay interactive CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  RIG_RELAY_HOME  Override the Rig Relay home directory (default: ~/.rig/relay)\n"
            "  VIBE_HOME       Legacy override for the Rig Relay home directory\n"
            "  RIG_RELAY_DISABLE_LEGACY_CONFIG=1  Strictly isolate from legacy Vibe config\n"
            "  LOG_LEVEL       Logging level: DEBUG, INFO, WARNING (default), ERROR, CRITICAL.\n"
            "                  Logs are written to $RIG_RELAY_HOME/logs/vibe.log.\n"
            "  LOG_MAX_BYTES   Max size of vibe.log before rotation (default: 10485760).\n"
            "  RIG_RELAY_*     Override any config field (e.g. RIG_RELAY_ACTIVE_MODEL=local).\n"
            "  VIBE_*          Legacy override for config fields.\n\n"
            "Legacy support:\n"
            "  rig-relay is the primary command. vibe is a legacy alias.\n"
            "  If upstream Mistral Vibe is also installed, use rig-relay to avoid ambiguity."
        ),
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Run read-only diagnostics for a selected session"
    )
    doctor_subparsers = doctor_parser.add_subparsers(dest="doctor_command")
    evidence_parser = doctor_subparsers.add_parser(
        "evidence", help="Validate evidence integrity for one session"
    )
    evidence_parser.add_argument(
        "--evidence-root",
        type=Path,
        required=True,
        metavar="PATH",
        help="Evidence root that owns the selected session.",
    )
    evidence_parser.add_argument(
        "--session", required=True, metavar="SESSION_ID", help="Session id to validate."
    )
    evidence_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output."
    )

    parser.add_argument(
        "--show-config-paths",
        action="store_true",
        help="Show active configuration paths and isolation status, then exit.",
    )
    parser.add_argument(
        "initial_prompt",
        nargs="?",
        metavar="PROMPT",
        help="Initial prompt to start the interactive session with.",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        nargs="?",
        const="",
        metavar="TEXT",
        help="Run in programmatic mode: send prompt, use the configured automation "
        "agent/policy, output response, and exit.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        metavar="N",
        help="Maximum number of assistant turns "
        "(only applies in programmatic mode with -p).",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        metavar="DOLLARS",
        help="Maximum cost in dollars (only applies in programmatic mode with -p). "
        "Session will be interrupted if cost exceeds this limit.",
    )
    parser.add_argument(
        "--enabled-tools",
        action="append",
        metavar="TOOL",
        help="Enable specific tools. In programmatic mode (-p), this disables "
        "all other tools. "
        "Can use exact names, glob patterns (e.g., 'bash*'), or "
        "regex with 're:' prefix. Can be specified multiple times.",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json", "streaming"],
        default="text",
        help="Output format for programmatic mode (-p): 'text' "
        "for human-readable (default), 'json' for all messages at end, "
        "'streaming' for newline-delimited JSON per message.",
    )
    parser.add_argument(
        "--agent",
        metavar="NAME",
        default=None,
        help="Agent to use (builtin: default, plan, accept-edits, auto-approve, "
        "or custom from ~/.rig/relay/agents/NAME.toml). In interactive mode, "
        "defaults to the 'default_agent' config setting. In programmatic "
        "mode (-p/--prompt), defaults to 'auto-approve' (legacy compatibility "
        "implementation detail) and 'default_agent' is ignored.",
    )
    parser.add_argument("--setup", action="store_true", help="Setup API key and exit")
    parser.add_argument(
        "--workdir",
        type=Path,
        metavar="DIR",
        help="Change to this directory before running",
    )
    parser.add_argument(
        "--trust",
        action="store_true",
        help="Trust the working directory for this invocation only (not "
        "persisted to trusted_folders.toml). Skips the trust prompt. "
        "Use this for non-interactive automation.",
    )

    # Feature flag for teleport, not exposed to the user yet
    parser.add_argument("--teleport", action="store_true", help=argparse.SUPPRESS)

    continuation_group = parser.add_mutually_exclusive_group()
    continuation_group.add_argument(
        "-c",
        "--continue",
        action="store_true",
        dest="continue_session",
        help="Continue from the most recent saved session",
    )
    continuation_group.add_argument(
        "--resume",
        nargs="?",
        const=True,
        default=None,
        metavar="SESSION_ID",
        help="Resume a session. Without SESSION_ID, shows an interactive picker.",
    )
    return parser.parse_args()


def check_and_resolve_trusted_folder(cwd: Path) -> None:
    if cwd.resolve() == Path.home().resolve():
        return

    detected_files = find_trustable_files(cwd)

    if not detected_files:
        return

    is_folder_trusted = trusted_folders_manager.is_trusted(cwd)

    if is_folder_trusted is not None:
        return

    try:
        is_folder_trusted = ask_trust_folder(cwd, detected_files)
    except (KeyboardInterrupt, EOFError, TrustDialogQuitException):
        sys.exit(0)
    except Exception as e:
        rprint(f"[yellow]Error showing trust dialog: {e}[/]")
        return

    if is_folder_trusted is True:
        trusted_folders_manager.add_trusted(cwd)
    elif is_folder_trusted is False:
        trusted_folders_manager.add_untrusted(cwd)


def _show_diagnostics() -> None:
    from vibe.core.config import VibeConfig
    from vibe.core.config.harness_files import get_harness_files_manager
    from vibe.core.paths import VIBE_HOME, get_vibe_home_diagnostics

    init_harness_files_manager("user", "project")
    cfg = VibeConfig.load()
    mgr = get_harness_files_manager()
    home_diag = get_vibe_home_diagnostics()

    rprint("[bold blue]Rig Relay Diagnostics[/]")
    rprint(f"  Version:        {__version__}")
    rprint(f"  Home Path:      {VIBE_HOME.path}")
    rprint(f"  Legacy Home:    {home_diag['legacy_home'] or 'None'}")
    rprint(f"  Is Legacy:      {home_diag['is_legacy']}")
    rprint(f"  Legacy Disabled: {home_diag['legacy_disabled']}")
    rprint(f"  Config Source:  {mgr.config_source}")
    rprint(f"  Config File:    {mgr.config_file or 'None (using defaults)'}")
    rprint(f"  Active Model:   {cfg.active_model}")
    rprint(f"  Model Alias:    {cfg.get_active_model().alias}")
    rprint(f"  Provider:       {cfg.get_active_provider().name}")
    rprint(f"  All Providers:  {', '.join(p.name for p in cfg.providers)}")
    rprint(f"  All Models:     {', '.join(m.alias for m in cfg.models)}")


def main() -> None:
    # Legacy alias warning
    cmd_name = Path(sys.argv[0]).name
    if cmd_name == "vibe" or cmd_name.endswith("-vibe"):
        rprint(
            "[dim]`vibe` is a legacy compatibility alias for Rig Relay. Prefer `rig-relay`.[/]"
        )

    args = parse_arguments()

    if args.show_config_paths:
        _show_diagnostics()
        sys.exit(0)

    if args.workdir:
        workdir = args.workdir.expanduser().resolve()
        if not workdir.is_dir():
            rprint(
                f"[red]Error: --workdir does not exist or is not a directory: {workdir}[/]"
            )
            sys.exit(1)
        os.chdir(workdir)

    try:
        cwd = Path.cwd()
    except FileNotFoundError:
        rprint(
            "[red]Error: Current working directory no longer exists.[/]\n"
            "[yellow]The directory you started Rig Relay from has been deleted. "
            "Please change to an existing directory and try again, "
            "or use --workdir to specify a working directory.[/]"
        )
        sys.exit(1)

    if args.trust:
        trusted_folders_manager.trust_for_session(cwd)

    is_interactive = args.prompt is None
    if is_interactive:
        check_and_resolve_trusted_folder(cwd)
    init_harness_files_manager("user", "project")

    from vibe.cli.cli import run_cli

    run_cli(args)


if __name__ == "__main__":
    main()

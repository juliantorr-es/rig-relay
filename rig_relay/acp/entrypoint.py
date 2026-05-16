from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys

import tomli_w

from rig_relay import __version__
from rig_relay.core.config import VibeConfig
from rig_relay.core.config.harness_files import (
    get_harness_files_manager,
    init_harness_files_manager,
)
from rig_relay.core.logger import logger
from rig_relay.core.paths import resolve_history_path
from rig_relay.core.telemetry.build_metadata import build_entrypoint_metadata

# Configure line buffering for subprocess communication
sys.stdout.reconfigure(line_buffering=True)  # pyright: ignore[reportAttributeAccessIssue]
sys.stderr.reconfigure(line_buffering=True)  # pyright: ignore[reportAttributeAccessIssue]
sys.stdin.reconfigure(line_buffering=True)  # pyright: ignore[reportAttributeAccessIssue]


@dataclass
class Arguments:
    setup: bool


def parse_arguments() -> Arguments:
    parser = argparse.ArgumentParser(description="Run Rig Relay in ACP mode")
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--setup", action="store_true", help="Setup API key and exit")
    args = parser.parse_args()
    return Arguments(setup=args.setup)


def bootstrap_config_files() -> None:
    mgr = get_harness_files_manager()
    config_file = mgr.user_config_file
    if not config_file.exists():
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with config_file.open("wb") as f:
                tomli_w.dump(VibeConfig.create_default(), f)
        except Exception as e:
            logger.error(f"Could not create default config file: {e}")
            raise

    history_file = resolve_history_path()
    if not history_file.exists():
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.write_text("", "utf-8")
        except Exception as e:
            logger.error(f"Could not create history file: {e}")
            raise


# When DEBUG_MODE=true, attaches debugpy on localhost:5678.
def handle_debug_mode() -> None:
    if os.environ.get("DEBUG_MODE") != "true":
        return

    try:
        import debugpy
    except ImportError:
        return

    debugpy.listen(("localhost", 5678))
    # uncomment this to wait for the debugger to attach
    # debugpy.wait_for_client()


def main() -> None:
    # Legacy alias warning
    cmd_name = Path(sys.argv[0]).name
    if "vibe" in cmd_name.lower():
        print(
            "`vibe-acp` is a legacy compatibility alias for Rig Relay. Prefer `rig-relay-acp`.",
            file=sys.stderr,
        )

    handle_debug_mode()
    init_harness_files_manager("user", "project")

    from rig_relay.acp.acp_agent_loop import run_acp_server
    from rig_relay.core.config import VibeConfig, load_dotenv_values
    from rig_relay.core.tracing import setup_tracing

    load_dotenv_values()
    bootstrap_config_files()
    args = parse_arguments()
    if args.setup:
        from rig_relay.setup.onboarding import run_onboarding

        run_onboarding(
            entrypoint_metadata=build_entrypoint_metadata(
                agent_entrypoint="acp",
                agent_version=__version__,
                client_name="rig_relay_acp",
                client_version=__version__,
            )
        )
        sys.exit(0)

    try:
        config = VibeConfig.load()
        setup_tracing(config)
    except Exception:
        pass  # tracing disabled

    run_acp_server()


if __name__ == "__main__":
    main()

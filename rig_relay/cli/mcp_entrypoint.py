"""rig_relay.cli.mcp_entrypoint — Rig Relay MCP server entry point.

Launches the RigMCPServer with stdio transport. Read-only by default.
Mutation-tier tools require HMAC-signed authorization receipts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from rig_relay.core.logger import logger


async def _serve(workspace_root: Path | None = None) -> None:
    from rig_relay.protocols.mcp.server import RigMCPServer

    server = RigMCPServer(workspace_root=workspace_root)
    logger.info("Rig Relay MCP server starting on stdio transport")
    await server.serve_stdio()


def main(argv: Sequence[str] | None = None) -> None:
    import sys as _sys

    args = list(argv) if argv is not None else _sys.argv[1:]
    workspace_root: Path | None = None

    i = 0
    while i < len(args):
        match args[i]:
            case "--workspace-root":
                if i + 1 < len(args):
                    workspace_root = Path(args[i + 1]).resolve()
                    i += 2
                else:
                    i += 1
            case "--help":
                print("Usage: rig-relay-mcp [--workspace-root DIR]")
                print()
                print(
                    "  --workspace-root DIR   Workspace root directory (default: cwd)"
                )
                return
            case _:
                i += 1

    asyncio.run(_serve(workspace_root=workspace_root))


__all__ = ["main"]

if __name__ == "__main__":
    main()

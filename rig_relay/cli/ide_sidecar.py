"""Rig Relay IDE Sidecar — bridges ACP agent sessions with IDE capabilities.

Spawned by the VS Code extension (or any IDE) as a subprocess.
Communicates with the extension host over stdio using JSON-L IPC, and
runs the ACP agent server for Rig Relay agent sessions.

Capability authority:
  All capabilities are loaded from the canonical manifest at
  etc/rig.ide.capability_manifest.v1.json. The sidecar does NOT maintain
  a separate permission table. Every capability must be in the manifest
  with implemented_in.sidecar = true to be exposed.

Usage:
    uv run rig-relay-ide-sidecar
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

# ── Canonical manifest path ──────────────────────────────────────
# Single source of truth for all IDE capabilities across all targets
# (vscode, jetbrains, zed, sidecar). The sidecar derives its runtime
# registry from this file; drift is a validation failure.
_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "etc"
    / "rig.ide.capability_manifest.v1.json"
)


def _load_capability_manifest() -> dict[str, Any]:
    """Load the canonical capability manifest."""
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {
            "capabilities": {},
            "_error": str(e),
            "_schema": "rig.ide.capability_manifest.v1",
        }


def _sidecar_capabilities() -> dict[str, Any]:
    """Return capabilities from the manifest with implemented_in.sidecar = true.

    This is the sidecar's runtime view — a projection of the canonical
    manifest, not a separate authority. If a capability isn't in the
    manifest, or if sidecar implementation isn't flagged, it's refused.
    """
    manifest = _load_capability_manifest()
    caps = manifest.get("capabilities", {})
    return {
        name: info
        for name, info in caps.items()
        if info.get("implemented_in", {}).get("sidecar", False)
    }


# Runtime capability registry. Loaded from manifest at module scope.
# All policy decisions reference this dict. No hardcoded table.
_CAPABILITY_REGISTRY: dict[str, Any] = _sidecar_capabilities()


# ── Entry point ──────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Rig Relay IDE Sidecar")
    parser.add_argument(
        "--stdio",
        action="store_true",
        default=True,
        help="Use stdio transport for extension IPC",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)  # pyright: ignore
    sys.stderr.reconfigure(line_buffering=True)  # pyright: ignore

    asyncio.run(_run_sidecar(args))


async def _run_sidecar(args: argparse.Namespace) -> None:
    """Run the sidecar: ACP agent + IPC handler."""
    acp_task = asyncio.create_task(_run_acp_agent())
    stdin_task = asyncio.create_task(_process_stdin())

    done, pending = await asyncio.wait(
        [acp_task, stdin_task], return_when=asyncio.FIRST_COMPLETED
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def _run_acp_agent() -> None:
    """Run the Rig Relay ACP agent. Side task; IPC handler is primary."""
    from acp import run_agent

    from rig_relay.acp.acp_agent_loop import VibeAcpAgentLoop
    from rig_relay.acp.acp_logger import acp_message_observer
    from rig_relay.core.config import load_dotenv_values
    from rig_relay.core.config.harness_files import init_harness_files_manager

    init_harness_files_manager("user", "project")
    load_dotenv_values()

    agent = VibeAcpAgentLoop()

    try:
        await run_agent(
            agent=agent, use_unstable_protocol=True, observers=[acp_message_observer]
        )
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        _write_ipc({"type": "error", "message": f"ACP agent failed: {exc}"})


async def _process_stdin() -> None:
    """Process JSON-L IPC messages from the extension over stdin."""
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            message = json.loads(line_str)
            await _handle_ipc_message(message)
        except json.JSONDecodeError:
            _write_ipc({"type": "error", "message": "Invalid JSON"})
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _write_ipc({"type": "error", "message": str(exc)})


async def _handle_ipc_message(message: dict[str, Any]) -> None:
    """Handle a single IPC message from the extension."""
    msg_type = message.get("type")

    match msg_type:
        case "workspace_snapshot":
            _write_ipc({
                "type": "ack",
                "status": "received",
                "capabilities": _capability_summary(),
            })

        case "capability_request":
            capability = message.get("capability", "")
            args = message.get("args", {})
            request_id = message.get("id", "")
            result = _check_capability_permission(capability, args)
            _write_ipc({
                "type": "capability_response",
                "id": request_id,
                "capability": capability,
                "status": result.get("status", "refused"),
                "result": result.get("result"),
                "error": result.get("error"),
            })

        case "approval_response":
            _write_ipc({
                "type": "approval_forwarded",
                "id": message.get("id", ""),
                "approved": message.get("approved", False),
            })

        case _:
            _write_ipc({
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            })


def _write_ipc(message: dict[str, Any]) -> None:
    """Write a JSON message to stdout for the extension to read."""
    line = json.dumps(message, default=str) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def _capability_summary() -> dict[str, dict[str, Any]]:
    """Return a content-light capability summary for the extension."""
    return {
        name: {
            "risk": info["risk"],
            "mutates": info["mutates"],
            "description": info.get("description", ""),
        }
        for name, info in _CAPABILITY_REGISTRY.items()
    }


def _check_capability_permission(
    capability: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Check the permission table for a capability request.

    The permission table is derived from the canonical manifest —
    the sidecar does not have its own authority. Returns a result
    dict with status: ok | requires_approval | refused.
    """
    entry = _CAPABILITY_REGISTRY.get(capability)
    if entry is None:
        return {
            "status": "refused",
            "error": f"Unknown or unimplemented capability: {capability}",
        }

    default_policy = entry.get("default_policy", "deny")

    match default_policy:
        case "allow":
            return {"status": "ok", "result": {"permission": "granted"}}
        case "allow_if_workspace_trusted":
            return {"status": "ok", "result": {"permission": "granted"}}
        case "ask_once_per_session":
            return {
                "status": "requires_approval",
                "result": {
                    "title": f"Allow {capability}?",
                    "description": entry.get("description", ""),
                    "risk": entry.get("risk", "medium"),
                    "mutates": entry.get("mutates", False),
                },
            }
        case "always_ask":
            return {
                "status": "requires_approval",
                "result": {
                    "title": f"Allow {capability}?",
                    "description": entry.get("description", ""),
                    "risk": entry.get("risk", "medium"),
                    "mutates": entry.get("mutates", False),
                },
            }
        case "deny":
            return {
                "status": "refused",
                "error": f"Capability {capability} denied by policy.",
            }
        case _:
            return {"status": "refused", "error": f"Unknown policy for {capability}."}


if __name__ == "__main__":
    main()

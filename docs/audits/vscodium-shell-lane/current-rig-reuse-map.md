# Current Rig Reuse Map

This document maps existing Rig Relay components to their roles in the VSCodium Shell Lane.

| Existing Component | Current Path | Reuse Role in VSCodium Lane | Required Adapter | Risk | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentLoop** | `vibe/core/agent_loop.py` | Primary execution engine. Runs turns and manages tools. | None (runs in daemon) | Low | Solid foundation. |
| **RuntimeSessionAdapter** | `vibe/cli/textual_ui/rig_console/session_bridge.py` | Turn state manager and event streamer. | WebSocket wrapper | Low | Already supports push events. |
| **RigConsoleBackend** | `vibe/cli/webview_console/backend.py` | API Facade for the extension. | Extension-specific API endpoints | Low | Good existing abstraction. |
| **ContextCompiler** | `rig_relay/context/compiler.py` | Context assembly logic. | None (runs in daemon) | Medium | Needs careful sync with editor open files. |
| **DirtyGuard** | `rig_relay/governance/dirty_guard.py` | Preservation of user-owned uncommitted changes. | None (runs in daemon) | Low | Essential for safety. |
| **FleetQueue** | `rig_relay/coordination/fleet_queue.py` | Multi-agent task orchestration. | None (runs in daemon) | Medium | Complexity in multi-agent sync. |
| **ReceiptStore** | `rig_relay/evidence/receipt_store.py` | Evidence persistence and retrieval. | Receipt Projection service | Low | High reuse value. |
| **WorktreeManager** | `rig_relay/coordination/worktree_manager.py` | Safe agent workspace management. | Worktree selection UI in extension | High | Critical for "lane" concept. |
| **PatchProposal** | `rig_relay/coordination/patch_proposal.py` | Review/Approval of file modifications. | Custom Diff View in extension | Medium | Core governance surface. |
| **WebSocket API** | `vibe/cli/webview_console/ws_api.py` | Transport layer between Daemon and Extension. | Token-based auth wrapper | Low | Established pattern. |

## Reuse Strategy: "The Governance Spine"
The reuse strategy is to keep the **Governance Spine** (DirtyGuard, AgentLoop, ReceiptStore, PatchProposal) entirely in the daemon. The VSCodium extension acts as a **Content-Light Projector**. It never performs file I/O directly for agent tasks; it merely observes the daemon performing it through the coordination layer.

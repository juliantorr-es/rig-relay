# Rig Relay Update Policy

## Principles

1. **Notification-first**: Update checks are informational. The user or parent
   orchestrator decides when to act.
2. **No restart during active sessions**: Sessions MUST NOT be interrupted.
   Restart is deferred to idle/session boundaries.
3. **Install-channel-aware**: The recommended update command depends on how Rig
   Relay was installed.
4. **User-controlled**: Automatic restart is opt-in only (`auto_restart_at_idle`).
5. **Structured events**: Agents receive `update_status` via current_state, not
   random terminal spam.

## Update State Machine

```
up_to_date → update_available → update_downloaded → restart_pending
                                                      ↓
                    restart_blocked_active_sessions ← restart_pending
                                                      ↓
                                              restart_ready
                                                      ↓
                                            restart_completed
```

| State | Meaning |
|---|---|
| `up_to_date` | Current version matches latest known |
| `update_available` | New version detected, not yet downloaded |
| `update_downloaded` | Package downloaded, awaiting restart |
| `restart_pending` | Restart queued |
| `restart_blocked_active_sessions` | Restart deferred because sessions > 0 |
| `restart_ready` | No active sessions, restart can proceed |
| `restart_completed` | Restart finished successfully |

## Recommended Update Commands

| Install Source | Update Command |
|---|---|
| `uv_tool` | `uv tool upgrade rig-relay` |
| `pipx` | `pipx upgrade rig-relay` |
| `pip` | `pip install --upgrade rig-relay` |
| `homebrew` | `brew upgrade rig-relay` |
| `npm` | `npm update -g rig-relay` |
| `source` | `git pull && uv sync` |

## Safe Restart Flow

1. Update check detects new version.
2. Emit `rig.relay.update.available` event.
3. Parent/reviewer sees `update_status` in `current_state`.
4. If `active_sessions > 0`, mark `restart_blocked_active_sessions`.
5. When all child sessions finish:
   - Checkpoint if allowed.
   - Export pending artifacts.
   - Prompt user or orchestrator.
6. If `auto_restart_at_idle` is enabled, restart automatically.
7. After restart, emit `restart_completed`.

## Agent Visibility

Agents see updates via `current_state`:

```json
{
  "update_status": {
    "current_version": "0.1.0a1",
    "latest_version": "0.1.0a2",
    "update_available": true,
    "install_source": "uv_tool",
    "recommended_update_command": "uv tool upgrade rig-relay",
    "restart_required": false,
    "restart_safe": false,
    "blocked_by_active_sessions": 2,
    "update_state": "restart_blocked_active_sessions",
    "checked_at": "..."
  }
}
```

## CLI Update Check

```bash
rig-relay update check           # Check for update, print status
rig-relay update status          # Show current update state
```

These commands do not modify the system. They only check and report.

## Cross-References

- [Versioning Policy](release/versioning-policy.md)
- [Install Channels](../install.md)
- [Current State Pulse](../../scripts/rig_relay_current_state.py)

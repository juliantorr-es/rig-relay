# IDE Capability Map

Canonical capability registry for Rig Relay IDE bridges. Generated from `etc/rig.ide.capability_manifest.v1.json`. Do not edit by hand.

**Total capabilities:** 42

---

## IDE Capabilities

| Capability | Risk | Mutates | Policy | Workspace Trust | Implemented |
|---|---|---|---|---|---|
| `ide.buffer.apply_preview_patch` | 🔴 High | Yes | Always ask | Required | ⬜ Not implemented |
| `ide.buffer.get_unsaved_changes` | 🟡 Medium | No | Allow (trusted) | — | ⬜ Not implemented |
| `ide.buffer.read` | 🟡 Medium | No | Allow (trusted) | Required | ✅ VS Code • ✅ Sidecar |
| `ide.buffer.read_range` | 🟡 Medium | No | Allow (trusted) | Required | ✅ VS Code • ✅ Sidecar |
| `ide.call_hierarchy` | 🟡 Medium | No | Allow | — | ⬜ Not implemented |
| `ide.debug.breakpoints.list` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.debug.evaluate_readonly` | 🔴 High | Possible | Always ask | — | ⬜ Not implemented |
| `ide.debug.sessions` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.debug.stack` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.debug.variables` | 🟡 Medium | No | Ask once/session | — | ✅ VS Code • ✅ Sidecar |
| `ide.definition.goto` | 🟡 Medium | No | Allow (trusted) | Required | ✅ Sidecar |
| `ide.diagnostics.file` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.diagnostics.range` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.diagnostics.workspace` | 🟢 Low | No | Allow | — | ✅ Sidecar |
| `ide.quickfixes.list` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.references.find` | 🟡 Medium | No | Allow (trusted) | Required | ✅ VS Code • ✅ Sidecar |
| `ide.rename_preview` | 🟡 Medium | No | Ask once/session | — | ⬜ Not implemented |
| `ide.symbols.document` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.symbols.workspace` | 🟡 Medium | No | Allow (trusted) | — | ✅ Sidecar |
| `ide.tasks.list` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.tests.discover` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.tests.run_at_cursor` | 🟡 Medium | Possible | Ask once/session | Required | ✅ Sidecar |
| `ide.tests.run_failed` | 🟡 Medium | Possible | Ask once/session | — | ⬜ Not implemented |
| `ide.tests.run_file` | 🟡 Medium | Possible | Ask once/session | Required | ✅ VS Code • ✅ Sidecar |
| `ide.type_hierarchy` | 🟡 Medium | No | Allow | — | ⬜ Not implemented |
| `ide.vcs.annotate` | 🟡 Medium | No | Allow (trusted) | — | ⬜ Not implemented |
| `ide.vcs.changed_files` | 🟢 Low | No | Allow | — | ✅ Sidecar |
| `ide.vcs.diff_file` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.vcs.diff_selection` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.vcs.status` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.workspace.active_file` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.workspace.describe` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.workspace.open_tabs` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.workspace.selection` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.workspace.visible_ranges` | 🟢 Low | No | Allow | — | ⬜ Not implemented |

## UI Capabilities

| Capability | Risk | Mutates | Policy | Workspace Trust | Implemented |
|---|---|---|---|---|---|
| `ide.buffer.show_diff` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.ui.notify` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.ui.request_approval` | 🔴 High | No | Always ask | — | ✅ VS Code • ✅ Sidecar |
| `ide.ui.show_consult_result` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.ui.show_context_packet` | 🟢 Low | No | Allow | — | ⬜ Not implemented |
| `ide.ui.show_diff` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |
| `ide.ui.show_receipt` | 🟢 Low | No | Allow | — | ✅ VS Code • ✅ Sidecar |

---

## Policy Meanings

| Policy | Behavior |
|---|---|
| `allow` | No prompt. Capability executes immediately. |
| `allow_if_workspace_trusted` | No prompt in trusted workspaces. Refused in untrusted. |
| `ask_once_per_session` | Prompts the first time per session. Auto-allows subsequent calls. |
| `always_ask` | Prompts every time. Never auto-allows. |
| `deny` | Always blocked. Agent receives `refused`. |

## Workspace Trust

Some capabilities require VS Code Workspace Trust. If the workspace is not trusted, capabilities with `requires_workspace_trust: true` are refused and the receipt records `workspace_trusted: false`.

## Receipt Model

Every capability execution emits a receipt (schema: `rig.ide.capability.receipt.v1`). Receipts record: capability name, input/output SHA256, user approval status, approval method, mutation status, workspace trust, and timestamp.

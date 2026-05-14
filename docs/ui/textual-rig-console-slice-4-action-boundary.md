# Textual Rig Console — Slice 4: Read-Only Action Surface and Projection Provider Boundary

## Status

**Draft.** Introduces the seam between Textual UI (projection consumer) and
backend/control-plane (projection producer). Adds typed read-only actions
and a provider protocol so the DashboardScreen can refresh projections
without owning runtime/workflow logic.

## Provider Boundary

### Why a Provider Protocol

Slice 3's DashboardScreen accepted a fixed `DashboardProjection` and a
no-op `action_refresh`. Slice 4 adds an optional provider seam:

- **`DashboardProjectionProvider`** (Protocol): one async method
  `dashboard_projection() → DashboardProjection`
- **`FixtureDashboardProjectionProvider`**: returns a fixed projection
  for preview/testing, with `set_projection()` to swap fixture data

The provider is the **only** way the DashboardScreen gets new projection
data. The screen never reads backend stores, coordination state, receipt
indices, or JSONL directly.

### Protocol

```python
class DashboardProjectionProvider(Protocol):
    async def dashboard_projection(self) -> DashboardProjection:
        """Must not mutate files, run tools, or expose raw content."""
        ...
```

### Fixture Provider

```python
class FixtureDashboardProjectionProvider:
    def __init__(self, projection: DashboardProjection) -> None: ...
    async def dashboard_projection(self) -> DashboardProjection: ...
    def set_projection(self, projection: DashboardProjection) -> None: ...
```

### Why Not Just a Callback

A Protocol ensures:
- Type safety across async boundaries
- Single responsibility (provider produces projections, UI consumes them)
- Testability (mock the protocol, not the screen internals)
- Future swap: replace fixture with a runtime adapter that reads
  coordination state and receipt indices

## Read-Only Action Model

### DashboardActionResult

A lightweight Pydantic model for action feedback:

| Field | Type | Description |
|---|---|---|
| `action_name` | str | Human-readable action name |
| `status` | str | One of `ok`, `info`, `error` |
| `message` | str \| None | Optional footer display message |

Convenience constructors:
- `DashboardActionResult.ok(action_name, message=None)`
- `DashboardActionResult.info(action_name, message=None)`
- `DashboardActionResult.error(action_name, message=None)`

All fields are content-light with `extra="forbid"`.

### Why Not Full Intent Types

Future slices may add typed intent classes (e.g. `RefreshDashboardIntent`,
`ShowHelpIntent`). For now, a single result model is sufficient to
route feedback through the footer. Intent types will be added when the
dispatcher/adapter layer is built (Slice 5+).

## DashboardScreen Updates

### Provider Acceptance

```python
class DashboardScreen(Screen):
    def __init__(
        self,
        projection: DashboardProjection,
        provider: DashboardProjectionProvider | None = None,
        *args, **kwargs,
    ) -> None: ...
```

### Keybindings

| Key | Action | Description |
|---|---|---|
| `q` | `action_quit` | Exit the application |
| `r` | `action_refresh` | Fetch new projection from provider (no-op without provider) |
| `?` | `action_show_help` | Show available keybindings in footer + backlog |
| `e` | `action_focus_evidence` | Placeholder: evidence focus (read-only, no mutation) |
| `v` | `action_validate_current` | Placeholder: validate status (read-only, no tool execution) |

### Action Behavior

- **`action_refresh`**: calls `provider.dashboard_projection()` if provider
  is set. Updates all child widgets via `update_projection()`. No
  remounting. Without provider, no-op.
- **`action_show_help`**: updates footer_hint with keybinding summary and
  backlog_items with action descriptions. Re-renders in place.
- **`action_focus_evidence`**: sets footer status to a placeholder message.
  Read-only — does not actually focus or mutate.
- **`action_validate_current`**: sets footer status to a placeholder message.
  Read-only — does not run validate or call any tool.

### Refresh Flow

```
User presses 'r'
→ DashboardScreen.action_refresh()
  → if provider exists:
    → await provider.dashboard_projection()
    → update_projection(new_proj)
      → _render_all()
        → header.update_projection(proj)
        → session_pane.update_projection(proj.session)
        → evidence_rail.update_projection(proj.evidence)
        → footer.update_projection(proj)
    → _set_status("ok", "refresh", "Projection refreshed")
  → if no provider: no-op (no status change)
```

### What Actions Intentionally Do NOT Do

- Do not call tools directly
- Do not read raw logs, files, or diffs
- Do not mutate files or state
- Do not execute validate
- Do not parse JSONL or receipt indices
- Do not modify VibeApp or any TCSS files
- Do not remount child widgets on refresh

## Project Structure

```
vibe/cli/textual_ui/rig_console/
├── __init__.py              # +DashboardActionResult, +DashboardProjectionProvider, +FixtureDashboardProjectionProvider
├── projections.py           # (unchanged)
├── providers.py             # DashboardProjectionProvider protocol + FixtureDashboardProjectionProvider (NEW)
├── intents.py               # DashboardActionResult model (NEW)
├── console_app.py           # +FixtureDashboardProjectionProvider usage, +_sample_altered_dashboard()
├── screens/
│   ├── __init__.py
│   └── dashboard.py         # +provider param, +?, +e, +v keybindings
└── widgets/
    ├── __init__.py
    ├── session_pane.py
    ├── evidence_rail.py
    ├── operator_header.py
    └── footer_status.py
```

## Tests

```
tests/cli/textual_ui/rig_console/
├── __init__.py
├── test_session_pane_projection.py
├── test_session_pane_widget.py
├── test_evidence_rail.py
├── test_dashboard_projection.py
├── test_dashboard_screen.py        # +provider/action tests, +_render_all mocking
├── test_operator_header.py
├── test_footer_status.py
├── test_intents.py                 # DashboardActionResult tests (NEW)
└── test_providers.py               # Provider protocol + fixture tests (NEW)
```

Test coverage includes:
- Provider protocol structural compatibility
- Fixture provider sync/async returns
- Fixture provider set_projection/replace
- Content-light assertion on provider output
- DashboardActionResult construction, convenience, unknown field rejection
- DashboardScreen instantiation with/without provider
- All 5 actions exist as methods
- action_show_help updates footer_hint + backlog
- action_focus_evidence sets status (patched _render_all)
- action_validate_current sets status (patched _render_all)
- action_refresh without provider is safe no-op
- _set_status creates correct footer text
- No forbidden raw field names on any model/screen/provider

## Next Slices

| Slice | Component | Description |
|---|---|---|
| 5 | Runtime adapter | Replace FixtureDashboardProjectionProvider with real backend adapter |
| 6 | Multi-session grid | Grid of SessionPaneWidget instances for fleet/delegate views |
| 7 | Backend feed | Live projection updates from coordination store |
| 8 | pywebview port | Migrate projection models to desktop cockpit backend |

## Cross-References

- [Slice 1: SessionPaneWidget](textual-rig-console-slice-1.md)
- [Slice 2: EvidenceRailWidget](textual-rig-console-slice-2-evidence-rail.md)
- [Slice 3: DashboardScreen](textual-rig-console-slice-3-dashboard.md)
- [Desktop Projection Contract](../governance/relay-desktop-projection-contract.md)
- [Textual Retirement Policy](../governance/textual-retirement-policy.md)

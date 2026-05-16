# Desktop Golden Path — Audit Proof

**Date**: 2026-05-16
**Branch**: main
**HEAD**: 8d0b13c

## Source-Mode Evidence

### Backend Probe Ladder (bridge:01–10)

All 10 backend startup probes pass with live echo:

```
✅ [bridge:01] resolve frontend_dir: frontend/desktop
✅ [bridge:02] resolve index.html: 3.7 KB
✅ [bridge:03] verify asset files: js/main.js=11.3KB, css dir ok
✅ [bridge:04] build runtime_config: Local Loopback Bridge, token=yes
✅ [bridge:05] create WS server: ProjectionWebSocketServer ready
✅ [bridge:06] bind host/port: http://127.0.0.1:64060
✅ [bridge:07] probe /healthz: HTTP 200, ok=True
✅ [bridge:08] probe /index.html: HTTP 200, text/html
✅ [bridge:09] probe /js/main.js: HTTP 200, text/javascript
✅ [bridge:10] probe /css/chat.css: HTTP 200, text/css
```

### Config / Token Path

```
runtime_config.to_dict():
  token: <31 chars> ✓
  auth_token: <31 chars> ✓
  ws_url: ws://127.0.0.1:{port}/ws ✓

CockpitAPI.get_runtime_config():
  token present: YES (30 chars) ✓
  ws_url: ws://127.0.0.1:9876/ws ✓
```

### WebSocket E2E

```
WS URL: ws://127.0.0.1:9878/ws
Auth: auth_ok ✓
Projection: type=projection, schema=rig.relay.desktop_projection.v1 ✓
E2E WebSocket auth + projection: PASS
```

### Healthz

```json
{
  "ok": true,
  "frontend_dir_exists": true,
  "index_exists": true,
  "main_js_exists": true,
  "css_dir_exists": true,
  "active_ws_clients": 0,
  "last_ws_error": null,
  "frontend_url": "http://127.0.0.1:64060/index.html",
  "ws_url": "ws://127.0.0.1:64060/ws"
}
```

No token in healthz output ✓

### Regression Tests

```
tests/desktop/test_golden_path.py ...... (6/6 passed)
tests/desktop/test_bridge_diagnostics.py ....................... (23/23 passed)
```

### Demo Doctor

```
All 22 checks passed. Demo ready.
```

## Packaged-Mode Evidence

### App Build

```
dist/Rig Relay.app — 98 MB
dist/Rig Relay.app.zip — 45 MB
```

### Helper Commands

```
--demo-doctor: 22/22 passed
--demo-seed: All artifacts created
--demo-render-docs: ok=docs
```

### Application Support

```
~/Library/Application Support/Rig Relay/
  artifacts/
  certs/
  demo/          — adoption_proposals, bash_analytics, mission_board, ralph_lifecycle, ...
  docs-site/     — index.html
  logs/          — startup.log, bridge_probe.json, bridge.log
  runtime/
```

## Known Limitations

- Full GUI smoke (pywebview window, button clicks, visual widget confirmation) requires manual tester in macOS GUI session
- Notarization not performed
- Frontend console logs (`[bridge:frontend]`) require `webview.start(debug=True)` to view in Safari Web Inspector

## Files Changed (this mission)

| File | Change |
|---|---|
| `rig_relay/desktop/bridge_diagnostics.py` | Added `enable_echo()` + `_echo` flag for live step printing |
| `rig_relay/cli/desktop_cockpit.py` | Wire `bridge_probe.enable_echo()` |
| `rig_relay/desktop/bridge_state_machine.py` | Explicit bridge lifecycle state machine for startup and probe transitions |
| `rig_relay/desktop/bridge_server.py` | Bridge lifecycle now emits state transitions and exposes state in `/healthz` |
| `frontend/desktop/js/main.js` | pywebviewready wait, config diagnostics, duplicate call fix |
| `frontend/desktop/js/transport.js` | `token_missing` state, `authenticating` state |
| `frontend/desktop/js/status.js` | Connection chip labels for all states |
| `frontend/desktop/js/transportState.js` | Explicit frontend transport lifecycle state machine |
| `tests/desktop/test_golden_path.py` | 6 regression tests |
| `docs/demo/desktop-golden-path.md` | Golden path documentation |
| `docs/audits/desktop/desktop-golden-path-proof.md` | This audit proof |

## Validation Summary

| Check | Result |
|---|---|
| Backend probes bridge:01–10 | All OK (live echo) |
| Bridge lifecycle state machine | Explicit lifecycle projection exposed in `/healthz` |
| Frontend transport state machine | Explicit frontend transport projection and status copy |
| Config token chain | token present in runtime_config → CockpitAPI → frontend |
| WebSocket auth + projection | E2E protocol test passes |
| Healthz asset fields | All present, no token |
| Bridge diagnostics tests | 23/23 passed |
| Golden path tests | 6/6 passed |
| demo-doctor | 22/22 passed |
| ruff | All checks passed |
| pyright | 0 errors, 0 warnings |

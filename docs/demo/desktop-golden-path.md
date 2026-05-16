# Desktop Golden Path

The first reproducible source-mode and packaged-mode golden path for Rig Relay desktop.

## Source Mode

### Command

```bash
RIG_RELAY_BRIDGE_DEBUG=1 uv run rig-relay
```

### Expected Probe Ladder (18 steps)

```
  ✅ [bridge:01] resolve frontend_dir: frontend/desktop
  ✅ [bridge:02] resolve index.html: 3.7 KB
  ✅ [bridge:03] verify asset files: js/main.js=11KB, css dir ok
  ✅ [bridge:04] build runtime_config: Loopback Token Bridge, token_present=True
  ✅ [bridge:05] create WS server: ProjectionWebSocketServer ready
  ✅ [bridge:06] bind host/port: http://127.0.0.1:{port}
  ✅ [bridge:07] probe /healthz: HTTP 200, ok=True
  ✅ [bridge:08] probe /index.html: HTTP 200, text/html
  ✅ [bridge:09] probe /js/main.js: HTTP 200, text/javascript
  ✅ [bridge:10] probe /css/chat.css: HTTP 200, text/css
  ✅ [bridge:11] create pywebview window: window → http://127.0.0.1:{port}/index.html
  ✅ [bridge:12] pywebview start called: webview.start(gui=cocoa)
  ✅ [bridge:13] frontend runtime config loaded: source=pywebview_api token=present,len=32
  ✅ [bridge:14] websocket upgrade accepted
  ✅ [bridge:15] auth message received: token_present=true
  ✅ [bridge:16] websocket auth accepted
  ✅ [bridge:17] first projection sent
  ✅ [bridge:18] first projection rendered: digest=...
```

### Expected UI

| Widget | Status |
|---|---|
| Transport chip | **Connected** (green) or **Loopback Token Bridge** |
| Mission Board | Visible with active missions |
| Ralph Lifecycle | Visible with completed lanes |
| ToolRuntime Summary | Visible with demo entries |
| Reports | Visible |
| No white screen | Rich frontend loads |

## Packaged Mode

### Steps

1. `open "dist/Rig Relay.app"`
2. If macOS blocks: **System Settings → Privacy & Security → Open Anyway**
3. Click **Start Demo** → wait for status update
4. Click **Run Doctor** → see 22/22 checks
5. Click **Launch Cockpit** → rich frontend opens
6. Verify **Loopback Token Bridge** connects
7. Verify projections update

### Requirements

- No Terminal
- No Python/uv
- No API keys
- No external network
- Merge/push disabled

## Log Files

### Source Mode
- Terminal: bridge probe ladder printed live (steps 01-18)
- `~/Library/Application Support/Rig Relay/logs/bridge_probe.json`
- `~/Library/Application Support/Rig Relay/logs/bridge.log`

### Packaged Mode
- SwiftUI → Reveal Logs opens logs folder
- Same log paths as source mode under `~/Library/Application Support/Rig Relay/logs/`

## Config Flow

```
DesktopBridgeServer.start()
  → DesktopBridgeRuntimeConfig.to_dict()
  → includes `token_present` plus token fields for backend-only use
  → CockpitAPI.set_runtime_config(config)
  → pywebview.js_api = CockpitAPI instance
  → frontend calls window.pywebview.api.get_runtime_config()
    → returns config with token
  → frontend opens WebSocket with token
  → ProjectionWebSocketServer._handle_auth() validates token
  → auth_ok → get_projection → projection rendered
```

## Troubleshooting by Bridge Step

| Step Fails | Symptom | Check |
|---|---|---|
| bridge:01 | frontend_dir missing | FRONTEND_DIR constant or packaging path |
| bridge:02 | index.html missing | frontend build step |
| bridge:03 | js/main.js missing | frontend build step |
| bridge:04 | runtime_config bad | token generation, TLS config |
| bridge:06 | port bind failure | port in use, try another port |
| bridge:07-10 | static probes fail | file serving path or MIME type |
| bridge:11 | pywebview import fail | `uv add pywebview` |
| bridge:13 | no token in config | pywebview API not ready, check RIG_RELAY_BRIDGE_DEBUG=1 |
| bridge:14-16 | WS auth fail | token mismatch, check ws_url |
| bridge:17-18 | no projection | projection build error, check demo-seed |

## Protocol Verification

```python
# E2E test: WebSocket auth + projection
ws_url = bridge.runtime_config.ws_url
ws = websockets.connect(ws_url)
ws.send({"type": "auth", "token": "..."})
# → {"type": "auth_ok"}
ws.send({"type": "get_projection"})
# → {"type": "projection", "data": {...}}
```

## Regression Tests

```bash
uv run pytest tests/desktop/test_golden_path.py -v
# 6 tests: config token, fallback tokenless, WS auth, WS projection, healthz, probe ladder
```

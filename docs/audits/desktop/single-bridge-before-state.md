# Desktop Transport — Before State (Split Pywebview + WebSocket)

## Architecture

```
pywebview window
  └─ url=file://... (or http_server=True internal port)
       └─ Static HTML/JS/CSS served by pywebview internal HTTP server

Separate WebSocket server (websockets library)
  └─ ws://127.0.0.1:9876 (or wss with separate SSL context)
```

## Components

1. **pywebview static frontend**: `rig_relay/cli/desktop_cockpit.py: _open_window()`
   - Creates `webview.create_window(url=str(index_path), http_server=True, ssl=...)`
   - pywebview runs its own internal HTTP server on a random port
   - Serves `frontend/desktop/index.html` and all JS/CSS assets
   - TLS: pywebview `ssl=True` parameter, separate from WebSocket

2. **WebSocket server**: `rig_relay/desktop/websocket_server.py: ProjectionWebSocketServer`
   - Binds to `127.0.0.1:9876` (customizable)
   - Token-gated auth
   - Projection stream, chat state, intent dispatcher
   - TLS: `ssl_context` parameter, separate from pywebview

3. **TLS**: `rig_relay/desktop/tls.py`
   - `resolve_tls_config()` determines TLS mode (auto/1/0)
   - `load_ssl_context()` creates SSL context
   - Cert material lives in app_support_dir or BUILD_ROOT
   - Two separate SSL contexts: pywebview (ssl param) and WebSocket (ssl_context)

4. **Runtime config delivery**: JS API bridge
   - `CockpitAPI.get_runtime_config()` returns config dict
   - Frontend calls `window.pywebview.api.get_runtime_config()`
   - Config includes `ws_url`, `frontend_origin`, `tls_enabled`, etc.

5. **Frontend transport**: `frontend/desktop/js/main.js`
   - Uses `config.ws_url` for WebSocket connection
   - Fallback: `ws://127.0.0.1:9876`

## Problems

1. **Split origins**: pywebview serves HTML from one origin (internal port), WebSocket from another (9876). On macOS WebKit, this triggers serverTrust warnings and WSS failures.

2. **Two TLS endpoints**: pywebview's internal HTTPS server + project WebSocket server need separate cert management. WebKit only trusts the pywebview origin's cert.

3. **Port discovery**: pywebview's internal HTTP port is random and opaque to the frontend. Runtime config must bridge the gap.

4. **http_server=True fragility**: pywebview's internal HTTP server has platform-specific behavior. On macOS, it works; on other platforms, unknown.

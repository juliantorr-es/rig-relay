# macOS App Bundle — Rig Relay

## Quick Build

```bash
cd packaging/macos
chmod +x build_pyinstaller.sh
./build_pyinstaller.sh
```

Output:
- `dist/Rig Relay.app` — self-contained macOS app
- `dist/Rig Relay.app.zip` — distributable archive

## What's included

- Python runtime (no Python install required)
- Rig Relay Python package
- pywebview desktop cockpit
- Local HTTPS frontend bridge
- Local WSS projection/event bridge
- Frontend assets (HTML, JS, CSS)
- Demo data seeder (auto-runs on first launch)
- Docs site renderer
- All required dependencies (duckdb, pydantic, httpx, etc.)

## What's NOT required on target machine

- No Terminal
- No `uv`
- No Python
- No repo checkout
- No OAuth
- No provider API keys
- No network (local demo mode)

## First Launch

On first launch, the app automatically:
1. Creates `~/Library/Application Support/Rig Relay/`
2. Seeds demo data
3. Builds a local docs site
4. Opens the pywebview cockpit
5. Shows mission board, Ralph lifecycle, ToolRuntime, reports

## Distribution

Share `dist/Rig Relay.app.zip`. Recipients:
1. Unzip
2. Right-click → Open (first launch)
3. Approve Gatekeeper prompt
4. App opens with demo data

## Gatekeeper

Unsigned apps show a Gatekeeper warning on first launch. Users can
right-click → Open to bypass.

Future: Apple Developer ID signing + notarization removes the prompt.

## App structure (inside the bundle)

```
Rig Relay.app/
  Contents/
    MacOS/
      Rig Relay           # PyInstaller executable
    Resources/
      frontend/desktop/   # HTML, JS, CSS
      docs/demo/          # Demo docs (rendered on first launch)
      docs/schemas/       # JSON schemas
      etc/                # Config files
```

## User data (outside the bundle)

```
~/Library/Application Support/Rig Relay/
  demo/                   # Demo seed artifacts
  docs-site/              # Rendered docs
  runtime/                # Build artifacts (.build/ equivalent)
  certs/                  # Local TLS material for HTTPS/WSS bridges
  logs/                   # startup.log, app logs
  artifacts/              # User-generated artifacts
  .first_run_complete     # Marker file
```

## Troubleshooting

**App won't open (Gatekeeper):**
Right-click → Open, or System Settings → Privacy & Security → Open Anyway.

**Blank window on launch:**
Check `~/Library/Application Support/Rig Relay/logs/startup.log`.

**Secure bridge failed:**
Check whether local TLS is enabled in the startup log. `RIG_RELAY_DESKTOP_TLS=0`
is a development-only fallback that downgrades to HTTP/WS.

**Demo data not showing:**
Delete `~/Library/Application Support/Rig Relay/.first_run_complete` and relaunch.

**Want to build from source instead:**
```
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync
uv run rig-relay
```

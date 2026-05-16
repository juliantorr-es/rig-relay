# Rig Relay — macOS App (Tester Build)

## What this is

Rig Relay is a local governed runtime for agent work. It runs entirely on your
Mac without any account, API key, network connection, merge, or push.

## How to open

1. Download `Rig Relay.app.zip`
2. Unzip it
3. **Right-click** `Rig Relay.app` → **Open**
4. Click **Open** in the Gatekeeper dialog

macOS warns about apps from unidentified developers. Rig Relay is not yet
signed with an Apple Developer ID. Right-click → Open bypasses this warning.

## What you'll see

### SwiftUI shell
- A native Mac window with the Rig Relay logo
- Safety badges showing Local Demo is active
- Buttons: Run Doctor, Start Demo, Launch Cockpit, Build Docs, Open Docs, Reveal Logs

### Pywebview cockpit
- Click **Launch Cockpit** to open the full desktop app
- The cockpit loads the frontend over local HTTPS
- Projection and event traffic uses local WSS when TLS is enabled
- Mission Board — 3 active orchestrator missions
- ToolRuntime Summary — tool execution outcomes (completed, cached, refused)
- Ralph Lifecycle — background agent lanes and review bundles
- Reports — structured findings across 5 categories

## What this app does NOT do

- ❌ No account required
- ❌ No API key required
- ❌ No network access
- ❌ No merge to main branch
- ❌ No push to remote
- ❌ No background processes that modify your files
- ✅ Local demo mode only

## Troubleshooting

**App won't open (Gatekeeper):**
Right-click the app → Open, then click Open in the dialog.

**Buttons don't work:**
The helper executable might be missing. Check that `Rig Relay.app/Contents/Resources/RigRelayHelper/RigRelay` exists.

**Cockpit shows blank window:**
Click **Run Doctor** first, then **Start Demo**, then **Launch Cockpit**.

**Secure bridge fails:**
Check `~/Library/Application Support/Rig Relay/logs/startup.log`. The
development-only fallback is `RIG_RELAY_DESKTOP_TLS=0`.

**Where are logs?**
`~/Library/Application Support/Rig Relay/logs/startup.log`
Or click **Reveal Logs** in the shell.

**Want to reset demo data?**
Delete `~/Library/Application Support/Rig Relay/.first_run_complete` and relaunch.

## Feedback

This is a tester build. Report issues, suggestions, or questions to the Rig Relay repository.

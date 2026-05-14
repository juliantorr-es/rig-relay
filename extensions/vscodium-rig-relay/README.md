# Rig Relay VSCodium Extension Spike

This is a feasibility spike to prove that a VSCodium extension can serve as a governed workbench shell for the Rig Relay daemon.

## Goal
Prove connectivity, authentication, and content-light projection (transcripts/receipts) without editor forks or local tool execution in the extension host. This is now an MVP-hardened client with secure token storage and theme integration.

## Features
- **Mission Control Sidebar**: Activity bar view for agent interaction.
- **WebSocket Bridge**: Connects to `127.0.0.1` Rig daemon with protocol version negotiation.
- **Secure Token Storage**: Uses VS Code `SecretStorage` instead of plain-text settings.
- **Daemon Discovery**: Automatically detects local daemon configuration in `.rig/daemon/console.json`.
- **Theme Integration**: Follows VS Code's active color theme (Light/Dark/High Contrast).
- **Content-Light Invariant**: Strict filtering of raw data (stdout/stderr/diffs) to maintain the governance boundary.
- **Security**: Strict Content Security Policy (CSP) and nonce-based script execution in Webview.

## Development
1. Install dependencies: `npm install` (requires Node.js).
2. Build: `npm run compile`.
3. Launch: Open this folder in VSCodium and press `F5` (Extension Development Host).

## Configuration
- `rig-relay.daemon.host`: Default `127.0.0.1`.
- `rig-relay.daemon.port`: Default `5000`.
- Token: Must be set via the command `Rig Relay: Set Daemon Token`.

## Commands
- `Rig Relay: Set Daemon Token`: Store the daemon token securely.
- `Rig Relay: Clear Daemon Token`: Remove the stored token.
- `Rig Relay: Reconnect`: Force a reconnection to the daemon.
- `Rig Relay: Show Connection Status`: Display current status and protocol details.

## Manual Smoke Steps
1. Start Rig Relay daemon.
2. Run command `Rig Relay: Set Daemon Token` and paste the token.
3. Open a workspace with a `.rig/daemon/console.json` or configure host/port in settings.
4. Click "Rig Relay" icon in Activity Bar.
5. Click "RECONNECT".
6. Verify status changes to "READY" and the UI matches your theme.
7. Enter a prompt and verify the agent response appears.

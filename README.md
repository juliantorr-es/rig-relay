# Rig Relay

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/release/python-3120/)
[![License](https://img.shields.io/github/license/juliantorr-es/rig-relay)](https://github.com/juliantorr-es/rig-relay/blob/main/LICENSE)

```
██████████████████░░
██████████████████░░
████  ██████  ████░░
████    ██    ████░░
████          ████░░
████  ██  ██  ████░░
██      ██      ██░░
██████████████████░░
██████████████████░░
```

**Rig Relay v0.1.0-alpha.1 — a governed local coding harness for Rig.**

Rig Relay is a Relay-native local agent cockpit with a CLI compatibility
surface. It provides a governed control plane, desktop cockpit, terminal
cockpit, and durable local evidence for safe development work.

> [!WARNING]
> Rig Relay works on Windows, but we officially support and target UNIX environments.

## Current Status

Rig Relay is a standalone, provider-neutral local coding harness with a different runtime home, primary executable names, and default operational posture. It is being shaped into a governed control plane suitable for Rig workflows.

## Install

### From source

1. Clone the repository:
   ```bash
   git clone https://github.com/juliantorr-es/rig-relay
   cd rig-relay
   ```

2. Sync dependencies using [uv](https://github.com/astral-sh/uv):
   ```bash
   uv sync
   ```

3. Run from source:
   ```bash
   uv run rig-relay
   ```

### Global install

Preferred:

```bash
uv tool install git+https://github.com/juliantorr-es/rig-relay.git --force
```

Local checkout:

```bash
cd ~/Developer/GitHub/rig-relay
uv tool install . --force
```

Confirm:

```bash
which rig-relay
rig-relay --version
rig-relay --help
```

4. (Optional) Install as a global tool:
   ```bash
   uv tool install .
   ```

## Configure DeepSeek

Rig Relay needs a provider key before it can run model turns. DeepSeek is the default backend in the current distribution.

1. Obtain an API key from [platform.deepseek.com](https://platform.deepseek.com).
2. Set the environment variable:
   ```bash
   export DEEPSEEK_API_KEY="your_api_key_here"
   ```
   Or run `rig-relay --setup` to configure it interactively.

## Run Rig Relay

### Interactive Mode

Run the primary executable to start the Textual cockpit in your current
directory:
```bash
rig-relay
```

`rig-relay` now opens the Textual Rig Console by default. The legacy CLI
remains available explicitly:

```bash
rig-relay legacy
```

### Programmatic Mode

Use the `--prompt` (or `-p`) flag for non-interactive tasks:
```bash
rig-relay --prompt "Analyze the project structure and summarize the core modules."
```

## Features

- **Interactive Chat**: Conversational agent loop for codebase exploration and controlled edits.
- **Powerful Toolset**: File, search, git, and shell tools with explicit permissions and evidence capture.
- **Project-Aware Context**: Scans trusted project structure and git state for relevant context.
- **Highly Configurable**: Customize models, providers, and tool permissions through `config.toml`.
- **Safety First**: Tool execution approval and a trust-based folder system.

### Built-in Agents

Rig Relay includes several built-in agent profiles:

- **`default`**: Standard agent requiring approval for tool executions.
- **`plan`**: Read-only agent for exploration and planning.
- **`accept-edits`**: Auto-approves file edits only.
- **`auto-approve`**: Legacy compatibility profile that auto-approves tool executions. Use with caution.

Select an agent with the `--agent` flag:
```bash
rig-relay --agent plan
```

## Desktop Cockpit

Rig Relay now supports two cockpit surfaces:

- `rig-console` for the terminal-native Textual coding cockpit
- `uv run python scripts/rig_relay_desktop_cockpit.py` for the pywebview desktop cockpit

The desktop cockpit remains the primary graphical operator surface:

```bash
uv run python scripts/rig_relay_desktop_cockpit.py
```

Use `--dry-run` for a non-mutating projection dump:

```bash
uv run python scripts/rig_relay_desktop_cockpit.py --dry-run
```

### Textual Rig Console

Launch the terminal-native coding cockpit with `rig-relay` or the explicit
alias:

```bash
uv run rig-console
```

Fixture mode is the safe default. It renders canned projections and is useful
for smoke testing the layout without any runtime roots.

Runtime mode reads existing projection, audit, and coordination artifacts in a
read-only way:

```bash
uv run rig-console \
  --mode runtime \
  --session-id <session-id> \
  --session-path <path> \
  --workspace-root <path> \
  --coordination-root <path> \
  --audit-root <path>
```

The Textual console is read-only at startup. It shows session identity, runtime
adapter state, recent execution events, progress, active blockers or leases,
evidence receipts, validation summaries, and a safe footer with keybindings.
It does not display raw stdout, stderr, prompts, diffs, patches, secrets, or
other raw tool payloads.

## Configuration

### Configuration File Location

Rig Relay looks for its configuration in the following order:
1. `./.rig/relay/config.toml` (Project-specific)
2. `./.rig-relay/config.toml` (Legacy project-specific)
3. `./.vibe/config.toml` (Legacy project-specific, compatibility fallback)
4. `~/.rig/relay/config.toml` (User-global)
5. `~/.rig-relay/config.toml` (Legacy user-global)
6. `~/.vibe/config.toml` (Legacy user-global, compatibility fallback)

### Rig Relay Home Directory

By default, Rig Relay stores its configuration, logs, and history in `~/.rig/relay/`. You can override this by setting the `RIG_RELAY_HOME` environment variable:

```bash
export RIG_RELAY_HOME="/path/to/custom/home"
```

Recommended env:

```bash
export RIG_RELAY_HOME="$HOME/.rig/relay"
export RIG_RELAY_DISABLE_LEGACY_CONFIG=1
export DEEPSEEK_API_KEY="sk-..."
```

If upstream Mistral Vibe is also installed, use `rig-relay` instead of `vibe` to avoid command ambiguity.

### Brand direction

- Rig Relay is the product; providers are interchangeable backends.
- Visual direction: Bauhaus structure plus green phosphor terminal nostalgia.
- Animation should stay small, decorative, and automation-safe.
- Evidence, manifests, receipts, and doctor output stay first-class and legible.

## Maintenance and Updates

Rig Relay **disables automatic updates and remote version checks by design**. As a forked derivative, Rig Relay must be updated manually to ensure local enhancements and governance policies are preserved.

To update Rig Relay:
1. Fetch latest changes from the origin:
   ```bash
   git fetch origin
   ```
2. Inspect and merge manually:
   ```bash
   git merge origin/main
   ```

Do **not** use `uv tool upgrade mistral-vibe` or similar upstream commands, as they will replace Rig Relay with the upstream product.

## Legacy Compatibility

Rig Relay maintains backward compatibility for users transitioning from Mistral Vibe.
`vibe` remains a legacy compatibility alias, not the product identity.

### Commands
- `rig-relay` is the primary executable and launches the Textual cockpit.
- `rig-relay-acp` is the primary ACP executable.
- `vibe` is a legacy compatibility alias for `rig-relay`.
- `vibe-acp` is a legacy compatibility alias for `rig-relay-acp`.
- `rig-relay legacy` and `rig-relay run` explicitly invoke the legacy CLI.

## Upstream and License

Rig Relay is a derivative work of [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe), originally licensed under the Apache License, Version 2.0. 

This project is an independent derivative and is not affiliated with, endorsed by, or sponsored by Mistral AI. We have modified the upstream codebase to create a neutral, standalone agent harness.

For more details on the project's origin and third-party attributions, please see:
- [UPSTREAM.md](UPSTREAM.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

### License

Copyright 2025 Mistral AI

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the [LICENSE](LICENSE) file for the full license text.

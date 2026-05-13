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

**Rig Relay is a governed local coding harness for Rig.**

Rig Relay is a command-line coding assistant harness. It provides a conversational interface to your codebase, allowing you to use natural language to explore, modify, and inspect projects through a controlled set of tools and durable local evidence.

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

Run the primary executable to start a session in your current directory:
```bash
rig-relay
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

### Commands
- `rig-relay` is the primary executable.
- `rig-relay-acp` is the primary ACP executable.
- `vibe` is a legacy compatibility alias for `rig-relay`.
- `vibe-acp` is a legacy compatibility alias for `rig-relay-acp`.

### Paths and Environment Variables
- `VIBE_HOME` is supported as a legacy fallback for `RIG_RELAY_HOME`.
- `RIG_RELAY_DISABLE_LEGACY_CONFIG=1` disables fallback to `VIBE_HOME`, `~/.rig-relay/`, `~/.vibe/`, `./.rig-relay/`, and `./.vibe/`.
- `~/.rig/relay/` is the primary home; `~/.rig-relay/` and `~/.vibe/` are searched as legacy fallbacks only when legacy config is allowed.
- `./.rig/relay/` is the primary project-local root; `./.rig-relay/` and `./.vibe/` are searched as legacy fallbacks only when legacy config is allowed.

### Environment Prefixes
- `VIBE_*` environment variables (e.g., `VIBE_ACTIVE_MODEL`) are supported as legacy fallbacks for `RIG_RELAY_*`.

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

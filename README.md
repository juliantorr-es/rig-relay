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

**Rig Relay is an agent harness intended to become part of Rig’s governed control plane.**

Rig Relay is a command-line coding assistant harness. It provides a conversational interface to your codebase, allowing you to use natural language to explore, modify, and interact with your projects through a powerful set of tools.

> [!WARNING]
> Rig Relay works on Windows, but we officially support and target UNIX environments.

## Current Status

Rig Relay is currently in active development as a standalone derivative of Mistral Vibe. It is being transitioned into a neutral, provider-agnostic harness suitable for governed agentic workflows.

## Install from Source

1. Clone the repository:
   ```bash
   git clone https://github.com/juliantorr-es/rig-relay
   cd rig-relay
   ```

2. Sync dependencies using [uv](https://github.com/astral-sh/uv):
   ```bash
   uv sync
   ```

3. (Optional) Install as a global tool:
   ```bash
   uv tool install .
   ```

## Configure DeepSeek

Rig Relay prefers DeepSeek for its high-performance reasoning capabilities.

1. Obtain an API key from [platform.deepseek.com](https://platform.deepseek.com).
2. Set the environment variable:
   ```bash
   export DEEPSEEK_API_KEY="your_api_key_here"
   ```
   Or run `rig-relay --setup` to configure it interactively.

## Run Rig Relay

### Interactive Mode

Simply run the command to start a session in your current directory:
```bash
rig-relay
```

### Programmatic Mode

Use the `--prompt` (or `-p`) flag for non-interactive tasks:
```bash
rig-relay --prompt "Analyze the project structure and summarize the core modules."
```

## Features

- **Interactive Chat**: A conversational AI agent that understands your requests and breaks down complex tasks.
- **Powerful Toolset**: A suite of tools for file manipulation, code searching, version control, and command execution.
  - Read, write, and patch files (`read_file`, `write_file`, `search_replace`).
  - Execute shell commands in a stateful terminal (`bash`).
  - Recursively search code with `grep`.
  - Manage a `todo` list to track progress.
- **Project-Aware Context**: Automatically scans your project's file structure and Git status to provide relevant context.
- **Highly Configurable**: Customize models, providers, and tool permissions through a simple `config.toml` file.
- **Safety First**: Features tool execution approval and a trust-based folder system.

### Built-in Agents

Rig Relay includes several built-in agent profiles:

- **`default`**: Standard agent requiring approval for tool executions.
- **`plan`**: Read-only agent for exploration and planning.
- **`accept-edits`**: Auto-approves file edits only.
- **`auto-approve`**: Auto-approves all tool executions. Use with caution.

Select an agent with the `--agent` flag:
```bash
rig-relay --agent plan
```

## Configuration

### Configuration File Location

Rig Relay looks for its configuration in the following order:
1. `./.rig/relay/config.toml` (Project-specific)
2. `./.rig-relay/config.toml` (Legacy project-specific)
3. `~/.rig/relay/config.toml` (User-global)
4. `~/.rig-relay/config.toml` (Legacy user-global)

### Rig Relay Home Directory

By default, Rig Relay stores its configuration, logs, and history in `~/.rig/relay/`. You can override this by setting the `RIG_RELAY_HOME` environment variable:

```bash
export RIG_RELAY_HOME="/path/to/custom/home"
```

## Legacy Compatibility

Rig Relay maintains backward compatibility for users transitioning from Mistral Vibe.

### Commands
- `vibe` is a legacy alias for `rig-relay`.
- `vibe-acp` is a legacy alias for `rig-relay-acp`.

### Paths and Environment Variables
- `VIBE_HOME` is supported as a legacy fallback for `RIG_RELAY_HOME`.
- `~/.rig/relay/` is the primary home; `~/.rig-relay/` and `~/.vibe/` are searched as legacy fallbacks.
- `./.rig/relay/` is the primary project-local root; `./.rig-relay/` and `./.vibe/` are searched as legacy fallbacks.

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

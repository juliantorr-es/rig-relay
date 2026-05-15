# Rig Relay

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/release/python-3120/)
[![License](https://img.shields.io/github/license/juliantorr-es/rig-relay)](https://github.com/juliantorr-es/rig-relay/blob/main/LICENSE)

**Rig Relay — a governed local coding harness.**

A desktop cockpit for governed agentic development. Chat-first interface,
receipt-backed evidence, worktree isolation, multi-provider consultation
(Council), and fleet orchestration. Exposes MCP tools for Antigravity,
VS Code, and Zed, and speaks ACP for editor-integrated agent sessions.

## Quick Start

```bash
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync
uv run rig-relay
```

On first launch, Rig Relay will walk you through provider setup — pick a
provider, get an API key, and you're ready. No API key? Rig Relay still
starts in dry-run mode with full projection and WebSocket available.

```bash
uv tool install git+https://github.com/juliantorr-es/rig-relay.git --force
```

## Current Path

Rig Relay is a standalone desktop application built with pywebview. The
primary surface is a chat-first console with widget panels for workspace
state, fleet status, provider health, and Council (multi-provider
adversarial review).

```
uv run rig-relay
```

### Desktop Cockpit

Operator, Review, System, and Technical layout modes. Widgets at three
disclosure levels: compact chips, standard cards, and full-page expanded
views. Chat sends to AgentLoop → LLM → tools → response. WebSocket
streams projections and chat state to the frontend.

```bash
uv run rig-relay --dry-run       # projection dump, no window
uv run rig-relay --server-only   # WebSocket + URL, headless
```

## Protocol Surfaces

Rig Relay exposes four protocol surfaces for different integration patterns:

| Surface | Role | Description |
|---|---|---|
| **ACP Agent** | Editor ↔ Agent | Rig presents as a governed coding agent to Zed, JetBrains, VS Code. Sessions, progress events, edit proposals, permission gating. |
| **MCP Client** | Rig ↔ External Tools | Rig consumes external MCP servers for additional tools and context. |
| **MCP Server** | Host ↔ Rig | Rig exposes governed tools, resources, and prompts to Antigravity, Claude Desktop, Cursor, and other MCP hosts. Tiered: read-only → analysis → validation → patch proposal → mutation. |
| **WebSocket** | Cockpit ↔ Backend | Local projection stream for the desktop cockpit. Token-gated, localhost-only, content-light. |

See [docs/protocol-surfaces.md](docs/protocol-surfaces.md) for details.

## Legacy Path

Rig Relay is a derivative of mistralai/mistral-vibe. The `vibe` command
and legacy Textual TUI are retained for compatibility during migration
but are not the product identity.

```bash
rig-relay legacy          # legacy CLI
rig-relay legacy --agent plan
```

Legacy config paths (`.vibe/`, `~/.vibe/`) are read as compatibility
fallbacks. Set `RIG_RELAY_DISABLE_LEGACY_CONFIG=1` to require the new
paths.

## Agent Profiles

Rig Relay ships with built-in agent profiles. Select with `--agent`:

| Profile | Type | Tools | Use |
|---|---|---|---|
| `default` | Agent | Standard | Normal development with approval gates |
| `orchestrator` | Agent | Git, task dispatch, consult | Fleet orchestration, roadmap planning |
| `plan` | Agent | Read-only | Exploration and planning |
| `explorer` | Subagent | grep, read_file | Codebase exploration |
| `builder` | Subagent | write_file, search_replace, task | Patch application in scratch worktrees |
| `cleaner` | Subagent | validate, validation_suite | Post-build validation and cleanup |
| `bug-exterminator` | Subagent | cleaner tools + task | Hard merge conflict resolution |

## Features

- **Chat-first console** — Operator, Review, System, Technical layout modes with adaptive widget grids
- **Council** — Multi-provider adversarial review with structured opinions and receipt-backed findings
- **Fleet orchestration** — Roadmap planning, sprint scoping, mission dispatch to subagents on isolated worktrees
- **Receipt-backed evidence** — Every tool call, checkpoint, and consultation produces a receipt
- **Worktree isolation** — Agents operate in git worktrees under `.rig/relay/worktrees`
- **Slash commands** — `/init`, `/worktree`, `/fleet`, `/council`, `/orchestrator`, `/provider`, and more
- **Provider onboarding** — Interactive setup for DeepSeek, OpenAI, Anthropic, Google, Mistral, OpenRouter
- **MCP server** — 16 governed tools across 5 tiers, exposed for Antigravity/VS Code/Zed
- **ACP agent** — Editor-integrated session control with progress streaming and permission gating

## Configuration

Rig Relay looks for configuration at:
1. `./.rig/relay/config.toml` (project-specific)
2. `~/.rig/relay/config.toml` (user-global)

API keys are stored in `~/.rig/relay/.env`. On first launch with no key
configured, the onboarding wizard walks through provider selection and
key setup.

## Development

```bash
uv run pytest                  # full suite
uv run pyright                 # type check
uv run ruff check --fix .      # lint
uv run ruff format .           # format
```

## License

Apache 2.0. Derivative of [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe).
See [LICENSE](LICENSE) and [UPSTREAM.md](UPSTREAM.md).

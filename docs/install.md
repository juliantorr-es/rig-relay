# Rig Relay Install Channels

## Primary Install: Python Packaging

Rig Relay is a Python CLI application distributed via PyPI. The recommended
install methods use standard Python packaging tools.

### uv tool install (recommended)

```bash
uv tool install rig-relay
```

### pipx install

```bash
pipx install rig-relay
```

### pip install (lower priority, risk of environment conflicts)

```bash
pip install rig-relay
```

## Source Install (Contributors)

```bash
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync --all-extras
```

## OS-Specific Channels

### Homebrew (future)

A Homebrew tap (`homebrew-rig-relay`) will be published when the project
reaches beta stability. The formula uses:

```ruby
class RigRelay < Formula
  include Language::Python::Virtualenv
  desc "Governed coding-agent harness with coordination, checkpoints, and dataset telemetry"
  url "https://files.pythonhosted.org/packages/.../rig_relay-0.1.0a1.tar.gz"
  depends_on "python@3.12"
  def install
    virtualenv_install_with_resources
  end
end
```

### npm wrapper (future convenience shim)

An npm package may be published as a thin wrapper that bootstraps `uv` or
`pipx` under the hood. It is NOT a Node.js rewrite.

```bash
npm install -g rig-relay
rig-relay
```

## Console Scripts

The Python package exposes these commands via `pyproject.toml` `[project.scripts]`:

| Command | Entry Point |
|---|---|
| `rig-relay` | `vibe.cli.entrypoint:main` |
| `rig-relay-acp` | `vibe.acp.entrypoint:main` |

The `vibe` and `vibe-acp` commands are **deprecated legacy aliases**. New
users should treat `rig-relay` as the primary product command and the 
pywebview cockpit as the primary operator surface.

## Version

Rig Relay v0.1.0-alpha.1 (Python package `0.1.0a1`).
Derived from Mistral Vibe CLI lineage; independent version line.
Upstream compatibility is not guaranteed.

See [versioning policy](release/versioning-policy.md) for version semantics.

## Legacy Migration

Rig Relay is migrating from Vibe-derived internals (`vibe.*`) to Relay-native packages (`rig_relay.*`).
Existing `vibe.*` imports remain supported during alpha. See the [Legacy Deprecation Doctrine](governance/vibe-legacy-deprecation.md)
for the migration plan.

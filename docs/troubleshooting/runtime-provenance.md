# Runtime Provenance

How to verify what code Rig Relay is actually running and diagnose stale-install problems.

## The problem

Rig Relay can be installed in two ways:

| Method | Command | Live-links to checkout? |
|---|---|---|
| Project venv (development) | `uv run rig-relay` | ✅ Yes (editable install) |
| System tool (global) | `rig-relay` | ❌ No (frozen copy) |

Running `rig-relay` (bare) invokes a **`uv tool install`** copy, which is a frozen
snapshot of the code at install time. It does **not** pick up local edits or new
commits until you reinstall.

Running `uv run rig-relay` uses the project's `.venv` editable install, which
**does** reflect the current working tree.

## Dogfood install

For development/dogfood, install from the local checkout:

```bash
cd /path/to/rig-relay
uv tool install --reinstall .
```

This replaces the global tool copy with the current checkout's code.
Repeat anytime the checkout advances.

## Verify what code is running

Run the runtime doctor:

```bash
rig-relay doctor runtime
```

This reports:

- Python executable path
- `rig-relay` command path
- `vibe` package path
- `agent_loop.py` and `assembler.py` paths
- Git HEAD commit (if inside a checkout)
- Installed version
- Presence of critical symbols (`write_assembly_report`, `validate_evidence_session`, etc.)
- Coherence status with warnings if paths disagree

Use `--json` for machine-readable output:

```bash
rig-relay doctor runtime --json
```

## Diagnostic commands

```bash
# Which rig-relay is on PATH?
which rig-relay

# Is it a uv tool install?
ls -la $(which rig-relay)

# Where does the tool env point?
cat ~/.local/share/uv/tools/rig-relay/lib/python3.12/site-packages/rig_relay-*.dist-info/direct_url.json

# What git commit was the tool install built from?
# Check direct_url.json or uv-receipt.toml

# What code does uv run use?
uv run python -c "import vibe; print(vibe.__file__)"

# Are the module paths coherent?
uv run python -c "from vibe.core.context.assembler import write_assembly_report; print('OK')"
```

## Common causes of stale runtime

1. **Bare `rig-relay` vs `uv run rig-relay`** — The bare command may use an old
   uv tool install while `uv run` uses the project venv.

2. **Multiple Python environments** — System Python, homebrew Python, uv-managed
   Python, and pyenv Python can all have different installs.

3. **Non-editable install** — `uv tool install .` copies the code; `uv pip install -e .`
   creates an editable link. Only the latter reflects local changes immediately.

4. **Git checkout drift** — If you run from the checkout (via `uv run`), the code
   matches the working tree. If you run from a tool install, you get the commit
   that was current when the tool was installed.

## Startup logging

Every Rig Relay session logs a compact provenance line at startup:

```
session_id=... package_path=... python=... git_head=... version=...
```

Look for this in `~/.rig/relay/logs/vibe.log` (or `$RIG_RELAY_HOME/logs/vibe.log`)
to confirm which code a session actually ran.

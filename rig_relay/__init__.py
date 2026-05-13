"""rig_relay — Rig Relay product package.

Rig Relay is an agent-runtime product for governed local coding assistance.
This package is the Relay-native product spine. Legacy Vibe-derived modules
live under ``vibe.*`` and are being migrated here through a controlled
Strangler Fig process.

See ``docs/governance/vibe-legacy-deprecation.md`` for the migration doctrine.

Package structure::

    rig_relay/
        __init__.py         -- Package root
        runtime/            -- Agent loop, provider boundary, tool registry
        governance/         -- Dirty guard, auth, telemetry modes, update policy
        coordination/       -- Store, leases, current_state, queue, spawn
        evidence/           -- Artifacts, receipts, semantic snippets, telemetry bundles
        desktop/            -- Projection, pywebview shell, WebSocket stream, intent API
        cli/                -- Product CLI commands, doctor, install helpers
"""

"""vibe.legacy — Legacy Vibe modules under quarantine.

This namespace package is the Legacy Quarantine zone (Phase 3 of the Strangler
Fig migration). Modules moved here are legacy substrate — not the product
architecture. New product code must not import from ``vibe.core`` directly;
instead, import from ``vibe.legacy.core`` when necessary during the transition.

See ``docs/governance/vibe-legacy-deprecation.md`` for the full doctrine.

When all importers have been migrated to ``rig_relay.*`` equivalents, modules
in this tree will be deleted or vendored.
"""

from __future__ import annotations

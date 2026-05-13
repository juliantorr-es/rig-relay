#!/usr/bin/env python3
"""Rig Relay Update Status Generator — CLI wrapper.

The core implementation now lives in ``rig_relay.runtime.update_status``.
This script is a thin CLI wrapper for backward compatibility.
"""

from __future__ import annotations

from rig_relay.runtime.update_status import (  # noqa: F401
    UPDATE_COMMANDS,
    VALID_STATES,
    _compare_versions,
    _get_current_version,
    generate_update_status,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Rig Relay Coordination Lease Cleanup — CLI wrapper.

The core implementation now lives in ``rig_relay.coordination.cleanup_leases``.
This script is a thin CLI wrapper for backward compatibility.
"""

from __future__ import annotations

from rig_relay.coordination.cleanup_leases import (  # noqa: F401
    CLEANABLE_STATUSES,
    DEFAULT_COORDINATION_ROOT,
    REPO_ROOT,
    _archive_files,
    _compute_stats,
    _delete_files,
    _parse_iso_datetime,
    _print_report,
    _scan_leases,
    _scan_tasks,
    main,
    run_cleanup,
)

if __name__ == "__main__":
    raise SystemExit(main())

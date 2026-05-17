#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.coordination.file_markers import claim_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-id")
    args = parser.parse_args()
    marker = claim_file(args.path, args.agent_id, args.session_id, args.task_id)
    print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


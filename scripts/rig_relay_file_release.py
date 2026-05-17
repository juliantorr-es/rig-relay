#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.coordination.file_markers import release_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    marker = release_file(args.path, args.agent_id, args.session_id, args.state, args.summary)
    print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


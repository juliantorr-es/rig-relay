#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rig_relay.pi_harness.extension_quarantine import ExtensionHealthStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    store = ExtensionHealthStore(root=args.root)
    for state in store.get_status():
        print(
            f"{state.extension.extension_id} healthy={state.healthy} quarantined={state.quarantined} crashes={len(state.crashes)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


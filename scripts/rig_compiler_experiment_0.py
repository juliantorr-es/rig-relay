#!/usr/bin/env python3
"""Contract Compiler Experiment 0 CLI.

Usage:
  uv run python scripts/rig_compiler_experiment_0.py [--target-schema PATH] [--run-id ID] [--keep-worktree] [--fail-on-validation-fail]

Exit codes:
  0 = experiment completed, evidence emitted (even if candidate rejected)
  1 = infrastructure failure
  2 = validation failure (only when --fail-on-validation-fail is passed)
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))

from datetime import UTC

from rig_relay.compiler_experiments.experiment_0 import run_experiment_0


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Compiler Experiment 0")
    parser.add_argument(
        "--target-schema",
        default=str(
            REPO_ROOT
            / "docs"
            / "schemas"
            / "rig.relay.coordination.fake_green_event.v1.schema.json"
        ),
        help="Path to target JSON Schema to compile a model for",
    )
    parser.add_argument(
        "--run-id", default=None, help="Run identifier (auto-generated if not set)"
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / ".build" / "rig-relay" / "contract-compiler" / "runs"),
        help="Output root for evidence artifacts",
    )
    parser.add_argument(
        "--worktree-root",
        default=str(REPO_ROOT / ".rig" / "relay" / "worktrees" / "compiler"),
        help="Root directory for compiler worktrees",
    )
    parser.add_argument(
        "--keep-worktree",
        action="store_true",
        help="Keep scratch worktree after experiment",
    )
    parser.add_argument(
        "--fail-on-validation-fail",
        action="store_true",
        help="Exit with code 2 if validation fails",
    )
    parser.add_argument(
        "--max-runtime-seconds", type=int, default=300, help="Max runtime per candidate"
    )
    args = parser.parse_args()

    from datetime import datetime

    run_id = args.run_id or f"exp0-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    target_schema = Path(args.target_schema)
    output_root = Path(args.output_root)
    worktree_root = Path(args.worktree_root)

    if not target_schema.exists():
        print(f"ERROR: Target schema not found: {target_schema}", file=sys.stderr)
        sys.exit(1)

    success, evidence_dir, worktree_dir = run_experiment_0(
        target_schema_path=target_schema,
        run_id=run_id,
        output_root=output_root,
        worktree_root=worktree_root,
        repo_root=REPO_ROOT,
        keep_worktree=args.keep_worktree,
        fail_on_validation_fail=args.fail_on_validation_fail,
    )

    if not success:
        if args.fail_on_validation_fail:
            print(f"Experiment failed validation. Evidence at: {evidence_dir}")
            sys.exit(2)
        print(f"Experiment infrastructure failure. Evidence may be at: {evidence_dir}")
        sys.exit(1)

    print(f"Experiment completed. Evidence at: {evidence_dir}")
    if worktree_dir:
        print(f"Worktree retained at: {worktree_dir}")


if __name__ == "__main__":
    main()

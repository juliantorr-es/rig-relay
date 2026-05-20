#!/usr/bin/env python3
"""Schema-to-Code Compiler CLI.

Usage:
  uv run python scripts/rig_compiler_schema_to_code.py \
    --schema docs/schemas/rig.event.envelope.v1.schema.json \
    --output-dir .build/rig-relay/compiler/generated/ \
    --validate

Exit codes:
  0 = compilation completed (even if validation fails)
  1 = infrastructure failure
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))

from rig_relay.compiler.schema_to_code import compile_schema_to_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema-to-Code Compiler")
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to target JSON Schema to compile a model for",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / ".build" / "rig-relay" / "compiler" / "generated"),
        help="Output directory for generated code and evidence",
    )
    parser.add_argument(
        "--validate", action="store_true", default=True, help="Run validation gates"
    )
    parser.add_argument(
        "--no-validate", action="store_true", help="Skip validation gates"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print summary of results"
    )
    args = parser.parse_args()

    schema_path = Path(args.schema)
    if not schema_path.exists():
        print(f"ERROR: Schema not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    run_validation = not args.no_validate

    result = compile_schema_to_code(
        schema_path=schema_path, output_dir=output_dir, run_validation=run_validation
    )

    if args.summary or True:
        print(f"Schema: {result['schema_path']}")
        print(f"Overall status: {result['overall_status']}")
        print(f"Evidence dir: {result['evidence_dir']}")
        print(f"Generated file: {result['generated_file']}")
        matrix = result.get("gate_matrix", {})
        if matrix:
            gates = matrix.get("gates", [])
            passed = sum(1 for g in gates if g.get("status") == "pass")
            failed = sum(1 for g in gates if g.get("status") == "fail")
            skipped = sum(1 for g in gates if g.get("status") == "skipped")
            print(f"Gates: {passed} passed, {failed} failed, {skipped} skipped")
            for gate in gates:
                status = gate["status"]
                marker = "✓" if status == "pass" else ("✗" if status == "fail" else "?")
                print(
                    f"  {marker} {gate['gate_id']}: {status} ({gate['duration_ms']}ms)"
                )

    if result["overall_status"] == "infra_fail":
        sys.exit(1)


if __name__ == "__main__":
    main()

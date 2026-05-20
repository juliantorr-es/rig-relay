"""Capability evidence dataset CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.providers.local_inference.dataset_export import build_export_policy
from rig_relay.providers.local_inference.ev_aggregation import aggregate_rows
from rig_relay.providers.local_inference.evidence_builder import build_evidence_row
from rig_relay.providers.local_inference.recommendation_policy import recommend


def _make_global() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--output-dir", type=Path, default=Path(".build/rig-relay/derived"))
    p.add_argument("--json", action="store_true")
    return p


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Capability evidence dataset")
    sub = p.add_subparsers(dest="command")
    gp = _make_global()
    b = sub.add_parser("build-rows", parents=[gp])
    b.add_argument("--count", type=int, default=10)
    sub.add_parser("aggregate", parents=[gp])
    sub.add_parser("recommend", parents=[gp])
    sub.add_parser("export-policy", parents=[gp])
    return p.parse_args(argv)


def _write(data: dict, filename: str, args) -> None:
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / filename).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not args.command:
        print("Commands: build-rows aggregate recommend export-policy", file=sys.stderr)
        return 1

    if args.command == "build-rows":
        rows = [
            build_evidence_row(
                machine_class="apple_silicon_medium",
                task_profile="chat_light",
                contract_passed=True,
                benchmark_available=True,
                shadow_passed=True,
            )
            for _ in range(getattr(args, "count", 5))
        ]
        data = [json.loads(r.model_dump_json()) for r in rows]
        _write({"rows": data}, "local_inference_capability_evidence.v1.json", args)
    elif args.command == "aggregate":
        rows_data = [
            build_evidence_row(
                machine_class="apple_silicon_medium",
                task_profile="chat_light",
                contract_passed=True,
                benchmark_available=True,
            ).model_dump()
            for _ in range(5)
        ]
        report = aggregate_rows(rows=rows_data)
        _write(
            json.loads(report.model_dump_json()),
            "local_inference_capability_evidence_report.v1.json",
            args,
        )
    elif args.command == "recommend":
        row = build_evidence_row(
            machine_class="apple_silicon_medium",
            task_profile="chat_light",
            contract_passed=True,
            benchmark_available=True,
            shadow_passed=True,
        )
        rec = recommend(row=row)
        _write(
            json.loads(rec.model_dump_json()),
            "local_inference_capability_recommendation.v1.json",
            args,
        )
    elif args.command == "export-policy":
        pol = build_export_policy()
        _write(
            json.loads(pol.model_dump_json()),
            "local_inference_dataset_export_policy.v1.json",
            args,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

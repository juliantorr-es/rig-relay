"""Capacity benchmarking & scientific comparison CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.providers.local_inference.benchmark_executor import run_benchmark_sync
from rig_relay.providers.local_inference.benchmark_harness import plan_benchmark
from rig_relay.providers.local_inference.capacity_scanner import scan_capacity
from rig_relay.providers.local_inference.model_fit_planner import plan_models
from rig_relay.providers.local_inference.scientific_comparison import (
    compare_local_cloud,
)
from rig_relay.providers.local_inference.telemetry_summary import (
    build_telemetry_summary,
)


def _make_global() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--output-dir", type=Path, default=Path(".build/rig-relay/derived"))
    p.add_argument("--json", action="store_true")
    return p


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Capacity benchmarking and scientific comparison"
    )
    sub = p.add_subparsers(dest="command")
    gp = _make_global()
    sub.add_parser("scan-capacity", parents=[gp])
    sub.add_parser("plan-models", parents=[gp])
    sub.add_parser("benchmark-plan", parents=[gp])
    c = sub.add_parser("compare", parents=[gp])
    c.add_argument("--task-profile", default="chat_light")
    br = sub.add_parser("benchmark-run", parents=[gp])
    br.add_argument("--endpoint-url", default="http://127.0.0.1:8080/v1")
    br.add_argument("--profile", default="chat_light")
    br.add_argument("--samples", type=int, default=3)
    br.add_argument("--execute", action="store_true")
    br.add_argument("--output-jsonl", type=Path, default=None)
    sub.add_parser("emit-telemetry", parents=[gp])
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
        print(
            "Commands: scan-capacity plan-models benchmark-plan compare emit-telemetry",
            file=sys.stderr,
        )
        return 1

    c = args.command
    if c == "scan-capacity":
        scan = scan_capacity()
        _write(
            json.loads(scan.model_dump_json()),
            "local_inference_capacity_scan.v1.json",
            args,
        )
    elif c == "plan-models":
        scan = scan_capacity()
        plan = plan_models(capacity=scan)
        _write(
            json.loads(plan.model_dump_json()),
            "local_inference_model_fit_plan.v1.json",
            args,
        )
    elif c == "benchmark-plan":
        bp = plan_benchmark()
        _write(
            json.loads(bp.model_dump_json()),
            "local_inference_capacity_benchmark_plan.v1.json",
            args,
        )
    elif c == "compare":
        report = compare_local_cloud(task_profile=args.task_profile)
        _write(
            json.loads(report.model_dump_json()),
            "local_inference_scientific_comparison_report.v1.json",
            args,
        )
    elif c == "benchmark-run":
        profiles = [args.profile]
        output_path = args.output_jsonl
        if not args.execute:
            bp = plan_benchmark(mode="dry_run_plan")
            _write(
                json.loads(bp.model_dump_json()),
                "local_inference_capacity_benchmark_plan.v1.json",
                args,
            )
            return 0
        plan, samples = run_benchmark_sync(
            endpoint_url=args.endpoint_url,
            task_profiles=profiles,
            sample_count_per_profile=args.samples,
            output_jsonl_path=output_path,
        )
        data = {
            "plan": json.loads(plan.model_dump_json()),
            "samples": [json.loads(s.model_dump_json()) for s in samples],
        }
        _write(data, "local_inference_capacity_benchmark_result.v1.json", args)
    elif c == "emit-telemetry":
        ts = build_telemetry_summary()
        _write(
            json.loads(ts.model_dump_json()),
            "local_inference_telemetry_summary.v1.json",
            args,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

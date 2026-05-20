"""Local inference orchestrator CLI. Plan-only by default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.providers.local_inference.auto_routing import evaluate_auto_routing
from rig_relay.providers.local_inference.backend_registry import (
    get_backend,
    list_backends,
)
from rig_relay.providers.local_inference.model_acquisition import plan_model_download
from rig_relay.providers.local_inference.proposal_adapter import classify_and_propose
from rig_relay.providers.local_inference.retention_policy import build_retention_policy
from rig_relay.providers.local_inference.server_lifecycle import plan_server_start


def _make_global() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--output-dir", type=Path, default=Path(".build/rig-relay/derived"))
    p.add_argument("--json", action="store_true")
    return p


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Local inference orchestrator")
    sub = p.add_subparsers(dest="command")
    gp = _make_global()

    sub.add_parser("list-backends", parents=[gp])
    m = sub.add_parser("plan-model-download", parents=[gp])
    m.add_argument("--backend-id", default="ollama")
    m.add_argument("--model-id", required=True)
    m.add_argument("--approval", action="store_true")
    s = sub.add_parser("start-server-plan", parents=[gp])
    s.add_argument("--backend-id", default="ollama")
    s.add_argument("--model-id-hash", default="")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--approval", action="store_true")
    r = sub.add_parser("retention-policy", parents=[gp])
    r.add_argument("--mode", default="disabled")
    d = sub.add_parser("route-decision", parents=[gp])
    d.add_argument("--backend-id", default="")
    d.add_argument("--routing-enabled", action="store_true")
    a = sub.add_parser("proposal-adapt", parents=[gp])
    a.add_argument("--completion-text", required=True)
    return p.parse_args(argv)


def _write(data: dict, filename: str, args) -> None:
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / filename).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))


def main(argv=None):
    args = _parse_args(argv)
    if not args.command:
        print(
            "Commands: list-backends plan-model-download start-server-plan retention-policy route-decision proposal-adapt",
            file=sys.stderr,
        )
        return 1

    c = args.command
    if c == "list-backends":
        data = [b.model_dump(mode="json") for b in list_backends()]
        _write(
            {"backends": data}, "local_inference_runtime_backend_registry.v1.json", args
        )
        if not args.json:
            for b in list_backends():
                print(f"  {b.backend_id}: {b.display_name}")
    elif c == "plan-model-download":
        plan = plan_model_download(
            backend_id=args.backend_id, model_id=args.model_id, approval=args.approval
        )
        _write(
            json.loads(plan.model_dump_json()),
            "local_inference_model_acquisition_plan.v1.json",
            args,
        )
    elif c == "start-server-plan":
        b = get_backend(args.backend_id)
        if b is None:
            print(f"Unknown: {args.backend_id}", file=sys.stderr)
            return 1
        r = plan_server_start(
            backend=b,
            model_id_hash=args.model_id_hash,
            host=args.host,
            port=args.port,
            approval=args.approval,
        )
        _write(
            json.loads(r.model_dump_json()),
            "local_inference_server_lifecycle_receipt.v1.json",
            args,
        )
    elif c == "retention-policy":
        pol = build_retention_policy(mode=args.mode)
        _write(
            json.loads(pol.model_dump_json()),
            "local_inference_raw_retention_policy.v1.json",
            args,
        )
    elif c == "route-decision":
        d = evaluate_auto_routing(
            backend_id=args.backend_id, routing_enabled=args.routing_enabled
        )
        _write(
            json.loads(d.model_dump_json()),
            "local_inference_auto_routing_decision.v1.json",
            args,
        )
    elif c == "proposal-adapt":
        prop = classify_and_propose(completion_text=args.completion_text)
        _write(
            json.loads(prop.model_dump_json()),
            "local_inference_local_output_proposal.v1.json",
            args,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

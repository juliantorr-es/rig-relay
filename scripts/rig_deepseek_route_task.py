#!/usr/bin/env python3
"""Dry-run DeepSeek lane router for Rig Relay tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.deepseek_routing import (
    DeepSeekRoutingTask,
    build_deepseek_routing_decision,
    format_deepseek_routing_decision_table,
    load_deepseek_lane_policy,
    validate_deepseek_lane_policy,
    validate_deepseek_routing_decision,
    write_deepseek_routing_decision,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Task text to classify.")
    task_group.add_argument("--task-file", type=Path, help="Path to a task text file.")
    parser.add_argument("--context-tokens", type=int, required=True)
    parser.add_argument("--output-kind", default="prose")
    parser.add_argument("--touches-code", action="store_true")
    parser.add_argument("--touches-tests", action="store_true")
    parser.add_argument("--touches-schemas", action="store_true")
    parser.add_argument("--touches-provider-auth", action="store_true")
    parser.add_argument("--touches-release-claims", action="store_true")
    parser.add_argument("--touches-public-site", action="store_true")
    parser.add_argument("--live-network", action="store_true")
    parser.add_argument(
        "--mutation-risk", choices=["none", "low", "medium", "high"], default="none"
    )
    parser.add_argument(
        "--concurrency-risk", choices=["none", "low", "medium", "high"], default="none"
    )
    parser.add_argument("--requires-json-output", action="store_true")
    parser.add_argument("--requires-tool-calls", action="store_true")
    parser.add_argument("--requires-multi-file-reasoning", action="store_true")
    parser.add_argument("--requires-strict-tool-beta", action="store_true")
    parser.add_argument("--strict-tool-schema-compatible", action="store_true")
    parser.add_argument("--user-override-lane")
    parser.add_argument("--generated-at")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument(
        "--write-artifact",
        type=Path,
        help="Write the routing decision artifact to this path.",
    )
    parser.add_argument(
        "--policy-path", type=Path, default=None, help="Optional policy artifact path."
    )
    parser.add_argument(
        "--fail-on-schema-error",
        action="store_true",
        help="Return non-zero when schema validation fails.",
    )
    return parser.parse_args(argv)


def _read_task_text(args: argparse.Namespace) -> str:
    if args.task is not None:
        return args.task
    assert args.task_file is not None
    return read_safe(args.task_file).text.rstrip("\r\n")


def _build_task(args: argparse.Namespace) -> DeepSeekRoutingTask:
    return DeepSeekRoutingTask(
        task_text=_read_task_text(args),
        estimated_context_tokens=args.context_tokens,
        requested_output_kind=args.output_kind,
        touches_code=args.touches_code,
        touches_tests=args.touches_tests,
        touches_schemas=args.touches_schemas,
        touches_provider_auth=args.touches_provider_auth,
        touches_release_claims=args.touches_release_claims,
        touches_public_site=args.touches_public_site,
        live_network=args.live_network,
        mutation_risk=args.mutation_risk,
        concurrency_risk=args.concurrency_risk,
        requires_json_output=args.requires_json_output,
        requires_tool_calls=args.requires_tool_calls,
        requires_multi_file_reasoning=args.requires_multi_file_reasoning,
        requires_strict_tool_beta=args.requires_strict_tool_beta,
        strict_tool_schema_compatible=args.strict_tool_schema_compatible,
        user_override_lane=args.user_override_lane,
    )


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        policy = load_deepseek_lane_policy(args.policy_path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"policy error: {exc}", file=sys.stderr)
        return 1

    policy_errors = validate_deepseek_lane_policy(policy)
    if policy_errors:
        print("policy validation failed:", file=sys.stderr)
        for error in policy_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    task = _build_task(args)
    try:
        decision = build_deepseek_routing_decision(
            task, policy=policy, generated_at=args.generated_at
        )
    except (ValueError, OSError, KeyError) as exc:
        print(f"routing error: {exc}", file=sys.stderr)
        return 1

    decision_errors = validate_deepseek_routing_decision(decision)
    if decision_errors:
        print("routing decision validation failed:", file=sys.stderr)
        for error in decision_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    if args.write_artifact is not None:
        write_deepseek_routing_decision(decision, args.write_artifact)

    if args.json:
        _emit_json(decision)
    else:
        print(format_deepseek_routing_decision_table(decision))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Local inference selection policy CLI.

Evaluates local inference eligibility and produces governed receipts.
Never starts a runtime, downloads a model, or sends prompts/completions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.providers.local_inference.airlock import (
    LocalInferenceAirlock,
    get_airlock,
)
from rig_relay.providers.local_inference.benchmark_summarizer import (
    summarize_benchmark_jsonl,
    validate_benchmark_content_light,
)
from rig_relay.providers.local_inference.capability_matching import match_capabilities
from rig_relay.providers.local_inference.fallback import decide_fallback
from rig_relay.providers.local_inference.models import CapabilityProbeResult
from rig_relay.providers.local_inference.selection_policy import (
    evaluate_selection_policy,
)
from rig_relay.providers.local_inference.task_profiles import get_task_profile


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate local inference selection policy."
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=None,
        help="Path to local inference config directory",
    )
    parser.add_argument(
        "--benchmark-jsonl",
        type=Path,
        default=None,
        help="Path to benchmark JSONL samples",
    )
    parser.add_argument(
        "--task-profile",
        type=str,
        default="unknown",
        choices=[
            "chat_light",
            "code_review_light",
            "structured_json",
            "tool_planning",
            "long_context_summary",
            "embedding_or_retrieval",
            "vision_or_multimodal",
            "unknown",
        ],
        help="Task profile to evaluate against",
    )
    parser.add_argument(
        "--diagnostics-disabled",
        action="store_true",
        help="Simulate diagnostics-disabled mode",
    )
    parser.add_argument(
        "--explicit-approval",
        action="store_true",
        help="Simulate explicit policy approval",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".build/rig-relay/derived"),
        help="Output directory for derived artifacts",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output results as JSON to stdout"
    )
    return parser.parse_args(argv)


async def _run_probe(endpoint_url: str) -> CapabilityProbeResult:
    from rig_relay.providers.local_inference.probe import probe_local_endpoint

    return await probe_local_endpoint(endpoint_url, dry_run=True)


def _get_probe_result(endpoint_url: str) -> CapabilityProbeResult:
    import asyncio
    import concurrent.futures

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run_probe(endpoint_url))
                return future.result(timeout=10)
        return asyncio.run(_run_probe(endpoint_url))
    except Exception:
        return CapabilityProbeResult(
            probe_id="cli_default",
            runtime_url=endpoint_url,
            probed_at="",
            probe_duration_ms=0,
            reachable=False,
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    airlock = (
        get_airlock()
        if args.config_root is None
        else LocalInferenceAirlock(args.config_root)
    )
    is_configured = airlock.is_configured
    config = airlock.get_config() if is_configured else None

    benchmark_summary = None
    if args.benchmark_jsonl:
        endpoint_sha256 = config.endpoint_sha256 if config else ""
        benchmark_summary = summarize_benchmark_jsonl(
            args.benchmark_jsonl,
            runtime_url=config.endpoint_url if config else "",
            endpoint_sha256=endpoint_sha256,
        )

    task_profile = get_task_profile(args.task_profile)
    capability_match = None
    probe_result = None

    if is_configured and config is not None:
        probe_result = _get_probe_result(config.endpoint_url)
        capability_match = match_capabilities(probe_result.capabilities, task_profile)

    selection_result = evaluate_selection_policy(
        endpoint_configured=is_configured,
        endpoint_sha256=config.endpoint_sha256 if config else "",
        probe_result=probe_result,
        benchmark_summary=benchmark_summary,
        task_profile=task_profile,
        capability_match=capability_match,
        diagnostics_enabled=not args.diagnostics_disabled,
        explicit_approval=args.explicit_approval,
    )

    fallback_decision = decide_fallback(selection_policy_result=selection_result)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "local_inference_selection_policy.v1.json").write_text(
            json.dumps(selection_result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (
            args.output_dir / "local_inference_provider_fallback_decision.v1.json"
        ).write_text(
            json.dumps(
                fallback_decision.model_dump(mode="json"), indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        if benchmark_summary:
            (args.output_dir / "local_inference_benchmark_summary.v1.json").write_text(
                json.dumps(
                    benchmark_summary.model_dump(mode="json"), indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
        msg = f"Artifacts written to {args.output_dir}"
        if args.json:
            print(msg, file=sys.stderr)
        else:
            print(msg)

    if args.json:
        output: dict = {
            "selection_policy": selection_result,
            "fallback_decision": fallback_decision.model_dump(mode="json"),
        }
        if benchmark_summary:
            output["benchmark_summary"] = benchmark_summary.model_dump(mode="json")
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        status = selection_result["result_kind"]
        conf = selection_result["confidence"]
        print(f"Selection Policy: {status} (confidence: {conf})")
        codes = selection_result["explanation_codes"]
        print(f"  Explanation: {codes}")
        print(f"  Manual: {selection_result['manual_selection_allowed']}")
        print(f"  Policy: {selection_result['policy_selection_allowed']}")
        print(f"  Fallback: {fallback_decision.fallback_provider_class}")
        print(f"  Rationale: {fallback_decision.fallback_rationale}")

    if args.benchmark_jsonl:
        warnings = validate_benchmark_content_light(args.benchmark_jsonl)
        if warnings:
            print(f"\nBenchmark content warnings: {len(warnings)}")
            for w in warnings[:5]:
                print(f"  - {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

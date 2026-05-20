"""Shadow evaluation CLI for local inference.

Runs shadow scenarios using the manual execution gate. Emits receipts.
Never auto-starts servers, downloads models, or persists raw completions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from rig_relay.providers.local_inference.airlock import (
    LocalInferenceAirlock,
    get_airlock,
)
from rig_relay.providers.local_inference.models import ShadowScenario
from rig_relay.providers.local_inference.shadow_evaluation import run_shadow_evaluation


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shadow evaluation for local inference."
    )
    parser.add_argument("--config-root", type=Path, default=None)
    parser.add_argument("--scenario-file", type=Path, help="Path to scenario JSON")
    parser.add_argument("--scenario-id", type=str, help="Scenario ID from corpus")
    parser.add_argument(
        "--execute", action="store_true", help="Execute (requires fake endpoint)"
    )
    parser.add_argument("--print-output", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".build/rig-relay/derived")
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


SCENARIOS_CORPUS = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "json"
    / "governance"
    / "local_inference_shadow_scenarios_v1.v1.json"
)


def _load_scenario(args: argparse.Namespace) -> ShadowScenario | None:
    if args.scenario_file:
        data = json.loads(args.scenario_file.read_text(encoding="utf-8"))
        return ShadowScenario(**data)
    if args.scenario_id and SCENARIOS_CORPUS.exists():
        corpus = json.loads(SCENARIOS_CORPUS.read_text(encoding="utf-8"))
        for s in corpus.get("scenarios", []):
            if s.get("scenario_id") == args.scenario_id:
                prompt = s.get("prompt_text_synthetic_safe", "")
                pb = prompt.encode("utf-8")
                s["prompt_sha256"] = hashlib.sha256(pb).hexdigest()
                s["prompt_byte_count"] = len(pb)
                return ShadowScenario(**s)
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    airlock = (
        get_airlock()
        if args.config_root is None
        else LocalInferenceAirlock(args.config_root)
    )
    configured = airlock.is_configured
    config = airlock.get_config() if configured else None
    endpoint_hash = config.endpoint_sha256 if config else ""
    endpoint_url = config.endpoint_url if config else ""

    scenario = _load_scenario(args)
    if scenario is None:
        print("No scenario found.", file=sys.stderr)
        return 1

    receipt = run_shadow_evaluation(
        scenario=scenario,
        endpoint_configured=configured,
        endpoint_hash=endpoint_hash,
        endpoint_url=endpoint_url,
        dry_run=not args.execute,
    )

    receipt_data = json.loads(receipt.model_dump_json())
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out = args.output_dir / "local_inference_shadow_run_receipt.v1.json"
        out.write_text(
            json.dumps(receipt_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        msg = f"Receipt written to {out}"
        if args.json:
            print(msg, file=sys.stderr)
        else:
            print(msg)

    if args.json:
        print(json.dumps(receipt_data, indent=2, sort_keys=True))
    else:
        print(f"Status: {receipt_data['status']}")
        print(f"  Contract: {receipt_data['output_contract']}")
        print(f"  Contract result: {receipt_data['contract_result']}")
        print(f"  Raw prompt persisted: {receipt_data['raw_prompt_persisted']}")
        print(f"  Raw completion persisted: {receipt_data['raw_completion_persisted']}")
        print(f"  Auto execution: {receipt_data['automatic_agent_execution']}")
        print(f"  Agent mutated: {receipt_data['agent_state_mutated']}")
        print(f"  Tool execution: {receipt_data['tool_execution_allowed']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

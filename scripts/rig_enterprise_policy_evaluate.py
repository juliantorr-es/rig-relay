#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rig_relay.enterprise.attestation import (
    attestation_to_json,
    read_attestation,
    sign_attestation,
    verify_attestation,
    write_attestation,
)
from rig_relay.enterprise.policy_engine import (
    PolicyEngine,
    PolicyEvaluation,
    build_policy_context,
    evaluate_all_gates,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay" / "enterprise"


def _format_result(prefix: str, name: str, value: str) -> str:
    return f"  {prefix} {name}: {value}"


def print_summary(evaluation: PolicyEvaluation) -> None:
    print()
    print("=" * 60)
    print("  POLICY EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Policy ID:     {evaluation.policy_id}")
    print(f"  All passed:    {evaluation.all_passed}")
    print(f"  Passed:        {evaluation.passed_count}")
    print(f"  Failed:        {evaluation.failed_count}")
    print(f"  Blocked:       {evaluation.blocked_count}")
    print(f"  Next action:   {evaluation.next_action}")
    print("-" * 60)
    print(f"  {'Gate ID':<40s} {'Passed':<8s} {'Value'}")
    print("-" * 60)

    for gate in evaluation.gates:
        symbol = "\u2705" if gate.passed else "\u274c"
        line = (
            f"  {symbol} {gate.gate_id:<38s} {gate.passed!s:<8s} {gate.current_value}"
        )
        print(line)
        if gate.blocked_reason:
            print(f"      Reason: {gate.blocked_reason}")

    print("-" * 60)
    if evaluation.operator_acknowledgements_required:
        print(
            f"  Operator acknowledgements: {len(evaluation.operator_acknowledgements_required)}"
        )
        for ack in evaluation.operator_acknowledgements_required:
            print(f"    - {ack}")
        print("-" * 60)


def save_evaluation(evaluation: PolicyEvaluation, engine: PolicyEngine) -> Path:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    path = BUILD_ROOT / "policy_evaluation.v1.json"
    data = engine.to_json(evaluation)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nEvaluation saved to: {path}")
    return path


def cmd_evaluate_all(args: argparse.Namespace) -> int:
    ctx = build_policy_context()
    evaluation = evaluate_all_gates(ctx)
    engine = PolicyEngine()

    if args.summary:
        print_summary(evaluation)

    if args.output:
        save_evaluation(evaluation, engine)

    return 0 if evaluation.all_passed else 1


def cmd_sign(args: argparse.Namespace) -> int:
    if not args.operator_id:
        print("ERROR: --operator-id required for signing", file=sys.stderr)
        return 1

    ctx = build_policy_context()
    evaluation = evaluate_all_gates(ctx)
    attestation = sign_attestation(evaluation, args.operator_id)

    out_path = args.output or (BUILD_ROOT / "attestation.v1.json")
    write_attestation(attestation, out_path)

    data = attestation_to_json(attestation)
    print(json.dumps(data, indent=2, sort_keys=True))
    print(f"\nAttestation saved to: {out_path}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    if not args.attestation_path:
        print("ERROR: --attestation-path required for verification", file=sys.stderr)
        return 1

    att = read_attestation(Path(args.attestation_path))
    if att is None:
        print(
            f"ERROR: Cannot read attestation from {args.attestation_path}",
            file=sys.stderr,
        )
        return 1

    ctx = build_policy_context()
    evaluation_ref = evaluate_all_gates(ctx)
    valid = verify_attestation(att, evaluation_ref)

    print(f"\nAttestation verification: {'VALID' if valid else 'INVALID'}")
    print(f"  Attestation ID:    {att.attestation_id}")
    print(f"  Signed by:         {att.signed_by}")
    print(f"  Signed at:         {att.signed_at}")
    print(f"  Signature matches: {valid}")
    print(f"  Content light:     {att.content_light}")

    return 0 if valid else 1


def cmd_check_single(args: argparse.Namespace) -> int:
    gate_id = getattr(args, "gate", "")
    if not gate_id:
        print("ERROR: --gate required for single check", file=sys.stderr)
        return 1

    from rig_relay.enterprise.policy_engine import BUILTIN_GATES

    matched = [g for g in BUILTIN_GATES if g.gate_id == gate_id]
    if not matched:
        print(f"ERROR: Gate '{gate_id}' not found. Available gates:", file=sys.stderr)
        for g in BUILTIN_GATES:
            print(f"  - {g.gate_id}", file=sys.stderr)
        return 1

    ctx = build_policy_context()
    result = matched[0].evaluate(ctx)
    print(f"\nGate: {result.gate_id}")
    print(f"  Passed:   {result.passed}")
    print(f"  Evidence: {result.evidence}")
    print(f"  Current:  {result.current_value}")
    print(f"  Required: {result.required_value}")
    if result.blocked_reason:
        print(f"  Blocked:  {result.blocked_reason}")
    return 0 if result.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Rig Relay Enterprise Policy Engine")
    sub = parser.add_subparsers(dest="command")

    p_eval = sub.add_parser("evaluate-all", help="Evaluate all policy gates")
    p_eval.add_argument("--summary", action="store_true", help="Print summary")
    p_eval.add_argument(
        "--output", action="store_true", help="Save evaluation artifact"
    )

    p_sign = sub.add_parser("sign", help="Sign evaluation and produce attestation")
    p_sign.add_argument("--operator-id", type=str, help="Operator identifier")
    p_sign.add_argument("--output", type=str, help="Attestation output path")

    p_verify = sub.add_parser("verify", help="Verify a signed attestation")
    p_verify.add_argument(
        "--attestation-path", type=str, help="Path to attestation JSON"
    )

    p_check = sub.add_parser("check", help="Check a single gate")
    p_check.add_argument("--gate", type=str, help="Gate ID to check")

    # Support dashed subcommand style too
    args = parser.parse_args()

    match args.command:
        case "evaluate-all":
            sys.exit(cmd_evaluate_all(args))
        case "sign":
            sys.exit(cmd_sign(args))
        case "verify":
            sys.exit(cmd_verify(args))
        case "check":
            sys.exit(cmd_check_single(args))
        case _:
            parser.print_help()
            sys.exit(1)


# Also support --evaluate-all, --summary, --sign, --verify as top-level flags
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rig Relay Enterprise Policy Engine")
    parser.add_argument(
        "--evaluate-all", action="store_true", help="Evaluate all policy gates"
    )
    parser.add_argument("--summary", action="store_true", help="Print summary")
    parser.add_argument("--sign", action="store_true", help="Sign evaluation")
    parser.add_argument("--verify", action="store_true", help="Verify attestation")
    parser.add_argument(
        "--output", action="store_true", help="Save evaluation artifact"
    )
    parser.add_argument("--operator-id", type=str, help="Operator identifier")
    parser.add_argument("--attestation-path", type=str, help="Path to attestation JSON")
    parser.add_argument("--gate", type=str, help="Check single gate")
    return parser


def _handle_evaluate(args: argparse.Namespace) -> int:
    ctx = build_policy_context()
    evaluation = evaluate_all_gates(ctx)
    engine = PolicyEngine()
    if args.summary:
        print_summary(evaluation)
    if args.output:
        save_evaluation(evaluation, engine)
    return 0 if evaluation.all_passed else 1


def _handle_sign(args: argparse.Namespace) -> int:
    if not args.operator_id:
        print("ERROR: --operator-id required for signing", file=sys.stderr)
        return 1
    ctx = build_policy_context()
    evaluation = evaluate_all_gates(ctx)
    attestation = sign_attestation(evaluation, args.operator_id)
    out_path = (
        Path(args.attestation_path)
        if args.attestation_path
        else (BUILD_ROOT / "attestation.v1.json")
    )
    write_attestation(attestation, out_path)
    print(json.dumps(attestation_to_json(attestation), indent=2, sort_keys=True))
    print(f"\nAttestation saved to: {out_path}")
    return 0


def _handle_verify(args: argparse.Namespace) -> int:
    if not args.attestation_path:
        print("ERROR: --attestation-path required for verification", file=sys.stderr)
        return 1
    att = read_attestation(Path(args.attestation_path))
    if att is None:
        print(
            f"ERROR: Cannot read attestation from {args.attestation_path}",
            file=sys.stderr,
        )
        return 1
    ctx = build_policy_context()
    evaluation_ref = evaluate_all_gates(ctx)
    valid = verify_attestation(att, evaluation_ref)
    print(f"\nAttestation verification: {'VALID' if valid else 'INVALID'}")
    print(f"  Attestation ID:    {att.attestation_id}")
    return 0 if valid else 1


def _handle_check_gate(args: argparse.Namespace) -> int:
    from rig_relay.enterprise.policy_engine import BUILTIN_GATES

    matched = [g for g in BUILTIN_GATES if g.gate_id == args.gate]
    if not matched:
        print(f"ERROR: Gate '{args.gate}' not found", file=sys.stderr)
        return 1
    ctx = build_policy_context()
    result = matched[0].evaluate(ctx)
    print(f"Gate: {result.gate_id} -> passed={result.passed}")
    return 0 if result.passed else 1


def main_dashed() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.evaluate_all:
        sys.exit(_handle_evaluate(args))
    if args.sign:
        sys.exit(_handle_sign(args))
    if args.verify:
        sys.exit(_handle_verify(args))
    if args.gate:
        sys.exit(_handle_check_gate(args))

    parser.print_help()


if __name__ == "__main__":
    main_dashed()

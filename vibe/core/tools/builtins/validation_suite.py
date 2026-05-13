from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import time
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.store import CoordinationStore
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent, ToolStreamEvent

ValidationStepKind = Literal[
    "ruff_check",
    "ruff_format_check",
    "pyright",
    "pytest",
    "schema_validation",
    "storage_audit",
    "desktop_cockpit_dry_run",
    "ruff_format_fix",
]


class ValidationStepRequest(BaseModel):
    kind: str
    paths: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = None
    allow_mutation: bool = False
    broad_validation_allowed: bool = False


class ValidationStepResult(BaseModel):
    kind: str
    command: list[str] = Field(default_factory=list)
    returncode: int
    duration_ms: int
    status: Literal["passed", "failed", "partial", "refused"]
    stdout_sha256: str
    stderr_sha256: str
    stdout_preview: str
    stderr_preview: str
    warnings: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)


class ValidationSuiteArgs(BaseModel):
    suite_name: str = "validation_suite"
    steps: list[ValidationStepRequest] = Field(default_factory=list)
    default_paths: list[str] = Field(default_factory=list)
    broad_validation_allowed: bool = False
    timeout_seconds: int = 300
    max_paths: int = 8
    allow_mutation: bool = False
    session_id: str | None = None
    task_id: str | None = None


class ValidationSuiteResult(BaseModel):
    suite_name: str
    requested_steps: list[str] = Field(default_factory=list)
    executed_steps: list[str] = Field(default_factory=list)
    skipped_steps: list[str] = Field(default_factory=list)
    status: Literal["passed", "failed", "partial", "refused"]
    duration_ms: int
    steps: list[ValidationStepResult] = Field(default_factory=list)
    command_summary: list[str] = Field(default_factory=list)
    stdout_sha256: str
    stderr_sha256: str
    stdout_preview: str
    stderr_preview: str
    artifact_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_suite_sha256: str


@dataclass
class _StepExecution:
    command: list[str]
    cwd: Path
    timeout_seconds: int
    env: dict[str, str]


@dataclass
class _SuiteRunState:
    requested_steps: list[str]
    executed_steps: list[str]
    skipped_steps: list[str]
    step_results: list[ValidationStepResult]
    warnings: list[str]
    artifact_refs: list[str]


class ValidationSuiteConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    validation_root: Path = Field(
        default_factory=lambda: Path.cwd() / ".build" / "rig-relay" / "validation"
    )
    step_timeout_seconds: int = 300
    max_preview_bytes: int = 4096


class ValidationSuite(
    BaseTool[
        ValidationSuiteArgs, ValidationSuiteResult, ValidationSuiteConfig, BaseToolState
    ],
    ToolUIData[ValidationSuiteArgs, ValidationSuiteResult],
):
    description: ClassVar[str] = (
        "Run allowlisted validation commands and return structured evidence."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        args = event.args
        if isinstance(args, ValidationSuiteArgs):
            return ToolCallDisplay(summary=f"Validation suite: {args.suite_name}")
        return ToolCallDisplay(summary="Validation suite")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        result = event.result
        if isinstance(result, ValidationSuiteResult):
            return ToolResultDisplay(
                success=result.status == "passed", message=result.status
            )
        return ToolResultDisplay(success=True, message="Validation suite complete")

    @classmethod
    def get_status_text(cls) -> str:
        return "Running validation suite"

    async def run(
        self, args: ValidationSuiteArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ValidationSuiteResult, None]:
        result = await self._run_suite(args, ctx)
        yield result

    def resolve_permission(self, args: ValidationSuiteArgs) -> None:
        return None

    @staticmethod
    def _refused_step(kind: str, reason: str) -> ValidationStepResult:
        payload = {"kind": kind, "reason": reason}
        digest = _hash_payload(payload)
        return ValidationStepResult(
            kind=kind,
            command=[],
            returncode=1,
            duration_ms=0,
            status="refused",
            stdout_sha256=digest,
            stderr_sha256=digest,
            stdout_preview="",
            stderr_preview=reason,
            warnings=[reason],
        )

    async def _run_suite(
        self, args: ValidationSuiteArgs, ctx: InvokeContext | None
    ) -> ValidationSuiteResult:
        start = time.perf_counter()
        repo_root = Path.cwd().resolve()
        suite_dir = self.config.validation_root / _suite_id(args)
        suite_dir.mkdir(parents=True, exist_ok=True)
        state = _SuiteRunState(
            requested_steps=[step.kind for step in args.steps],
            executed_steps=[],
            skipped_steps=[],
            step_results=[],
            warnings=[],
            artifact_refs=[],
        )
        store = self._coordination_store(ctx)
        for index, step in enumerate(args.steps, start=1):
            result = await self._run_or_refuse_step(
                step=step,
                args=args,
                repo_root=repo_root,
                suite_dir=suite_dir / f"{index:02d}-{step.kind}",
            )
            state.step_results.append(result)
            if result.status == "refused":
                state.skipped_steps.append(step.kind)
            else:
                state.executed_steps.append(step.kind)
                state.artifact_refs.extend(result.artifact_refs)
            state.warnings.extend(result.warnings)

        stdout_sha256, stderr_sha256, stdout_preview, stderr_preview = (
            _summarize_results(state.step_results, self.config.max_preview_bytes)
        )
        status = self._aggregate_status(
            state.step_results, state.executed_steps, state.requested_steps
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        payload = {
            "suite_name": args.suite_name,
            "requested_steps": state.requested_steps,
            "executed_steps": state.executed_steps,
            "skipped_steps": state.skipped_steps,
            "status": status,
            "command_summary": [" ".join(step.command) for step in state.step_results],
            "stdout_sha256": stdout_sha256,
            "stderr_sha256": stderr_sha256,
            "artifact_refs": state.artifact_refs,
            "warnings": state.warnings,
            "step_hashes": [step.stdout_sha256 for step in state.step_results],
        }
        result = ValidationSuiteResult(
            suite_name=args.suite_name,
            requested_steps=state.requested_steps,
            executed_steps=state.executed_steps,
            skipped_steps=state.skipped_steps,
            status=status,
            duration_ms=duration_ms,
            steps=state.step_results,
            command_summary=payload["command_summary"],
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            artifact_refs=state.artifact_refs,
            warnings=state.warnings,
            validation_suite_sha256=_hash_payload(payload),
        )
        self._write_summary(suite_dir, result)
        self._publish_artifact_if_possible(store, args, result)
        return result

    async def _run_or_refuse_step(
        self,
        *,
        step: ValidationStepRequest,
        args: ValidationSuiteArgs,
        repo_root: Path,
        suite_dir: Path,
    ) -> ValidationStepResult:
        validation_reason = self._validate_step(step, args)
        if isinstance(validation_reason, str):
            return self._refused_step(step.kind, validation_reason)
        return await self._run_step(
            _StepExecution(
                command=validation_reason,
                cwd=repo_root,
                timeout_seconds=step.timeout_seconds
                or self.config.step_timeout_seconds,
                env=_base_env(),
            ),
            suite_dir=suite_dir,
        )

    def _validate_step(
        self, step: ValidationStepRequest, args: ValidationSuiteArgs
    ) -> list[str] | str:
        reason: str | None = None
        command: list[str] | None = None
        if step.kind not in _ALLOWLISTED_STEP_KINDS:
            reason = f"Unknown validation step: {step.kind}"
        elif step.kind == "ruff_format_fix" and not step.allow_mutation:
            reason = "ruff_format_fix requires allow_mutation=true"
        elif step.kind in {"ruff_check", "ruff_format_check", "pyright", "pytest"}:
            paths = step.paths or args.default_paths or _default_paths(step.kind)
            if len(paths) > args.max_paths and not (
                args.broad_validation_allowed or step.broad_validation_allowed
            ):
                reason = (
                    "Too many paths requested without broad_validation_allowed=true"
                )
            elif any(
                Path(path).as_posix().startswith("docs/schemas/") for path in paths
            ) and step.kind.startswith("ruff"):
                reason = "Ruff validation is refused for docs/schemas/*.json"
            else:
                command = _step_command(step.kind, paths)
        else:
            command = _step_command(step.kind, step.paths or args.default_paths)
        if reason is not None:
            return reason
        if command is None:
            return f"Unknown validation step: {step.kind}"
        return command

    async def _run_step(
        self, execution: _StepExecution, suite_dir: Path
    ) -> ValidationStepResult:
        suite_dir.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *execution.command,
            cwd=execution.cwd,
            env=execution.env,
            shell=False,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=execution.timeout_seconds
            )
        except TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise ToolError(
                f"Validation step timed out after {execution.timeout_seconds}s"
            ) from e
        duration_ms = int((time.perf_counter() - start) * 1000)
        stdout_preview = stdout_bytes[: self.config.max_preview_bytes].decode(
            "utf-8", errors="replace"
        )
        stderr_preview = stderr_bytes[: self.config.max_preview_bytes].decode(
            "utf-8", errors="replace"
        )
        stdout_sha256 = "sha256:" + hashlib.sha256(stdout_bytes).hexdigest()
        stderr_sha256 = "sha256:" + hashlib.sha256(stderr_bytes).hexdigest()
        (suite_dir / "stdout.sha256").write_text(stdout_sha256, encoding="utf-8")
        (suite_dir / "stderr.sha256").write_text(stderr_sha256, encoding="utf-8")
        (suite_dir / "stdout.preview.txt").write_text(stdout_preview, encoding="utf-8")
        (suite_dir / "stderr.preview.txt").write_text(stderr_preview, encoding="utf-8")
        (suite_dir / "command.json").write_text(
            dump_canonical_json({"command": execution.command}), encoding="utf-8"
        )
        status = "passed" if proc.returncode == 0 else "failed"
        if proc.returncode != 0 and stdout_bytes and stderr_bytes:
            status = "partial"
        return ValidationStepResult(
            kind=_kind_from_command(execution.command),
            command=execution.command,
            returncode=proc.returncode or 0,
            duration_ms=duration_ms,
            status=status,
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            artifact_refs=[str(suite_dir)],
            warnings=[],
        )

    def _write_summary(self, suite_dir: Path, result: ValidationSuiteResult) -> None:
        payload = result.model_dump(mode="json", exclude_none=True)
        (suite_dir / "validation_suite.json").write_text(
            dump_canonical_json(payload), encoding="utf-8"
        )

    def _coordination_store(
        self, ctx: InvokeContext | None
    ) -> CoordinationStore | None:
        if ctx is None or ctx.session_dir is None:
            return None
        return CoordinationStore(
            ctx.session_dir.parent / ".build" / "rig-relay" / "coordination"
        )

    def _publish_artifact_if_possible(
        self,
        store: CoordinationStore | None,
        args: ValidationSuiteArgs,
        result: ValidationSuiteResult,
    ) -> None:
        if store is None or args.session_id is None:
            return
        store.publish_artifact(
            session_id=args.session_id,
            task_id=args.task_id,
            artifact_kind="validation_suite_summary",
            artifact_uri=str(self.config.validation_root),
            artifact_sha256=result.validation_suite_sha256,
            schema_id="rig.relay.validation_suite.v1",
        )

    @staticmethod
    def _aggregate_status(
        step_results: list[ValidationStepResult],
        executed_steps: list[str],
        requested_steps: list[str],
    ) -> Literal["passed", "failed", "partial", "refused"]:
        if not requested_steps:
            return "passed"
        if all(step.status == "refused" for step in step_results):
            return "refused"
        if any(step.status == "failed" for step in step_results):
            return "failed"
        if len(executed_steps) != len(requested_steps):
            return "partial"
        return "passed"


def _base_env() -> dict[str, str]:
    env = {**os.environ, "CI": "true", "NONINTERACTIVE": "1", "NO_TTY": "1"}
    env.setdefault("TERM", "dumb")
    return env


def _default_paths(kind: str) -> list[str]:
    match kind:
        case "ruff_check" | "ruff_format_check" | "ruff_format_fix" | "pyright":
            return ["vibe/core/tools/builtins/validation_suite.py"]
        case "pytest":
            return ["tests/coordination/test_tool.py"]
        case _:
            return []


def _step_command(kind: str, paths: list[str]) -> list[str]:
    command: list[str]
    match kind:
        case "ruff_check":
            command = ["uv", "run", "ruff", "check", *paths]
        case "ruff_format_check":
            command = ["uv", "run", "ruff", "format", "--check", *paths]
        case "ruff_format_fix":
            command = ["uv", "run", "ruff", "format", *paths]
        case "pyright":
            command = ["uv", "run", "pyright", *paths]
        case "pytest":
            command = ["uv", "run", "pytest", "-n0", *paths]
        case "schema_validation":
            command = ["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"]
        case "storage_audit":
            command = [
                "uv",
                "run",
                "python",
                "scripts/rig_relay_storage_audit.py",
                "--root",
                ".build/rig-relay",
            ]
        case "desktop_cockpit_dry_run":
            command = [
                "uv",
                "run",
                "python",
                "scripts/rig_relay_desktop_cockpit.py",
                "--dry-run",
            ]
        case _:
            raise ToolError(f"Unknown validation step: {kind}")
    return command


_ALLOWLISTED_STEP_KINDS = {
    "ruff_check",
    "ruff_format_check",
    "pyright",
    "pytest",
    "schema_validation",
    "storage_audit",
    "desktop_cockpit_dry_run",
    "ruff_format_fix",
}


def _kind_from_command(command: list[str]) -> ValidationStepKind:
    kind: ValidationStepKind = "ruff_check"
    if command[2:4] == ["ruff", "check"]:
        kind = "ruff_check"
    elif command[2:5] == ["ruff", "format", "--check"]:
        kind = "ruff_format_check"
    elif command[2:4] == ["pyright"]:
        kind = "pyright"
    elif command[2:4] == ["pytest"]:
        kind = "pytest"
    elif command[2:4] == ["python", "scripts/rig_relay_validate_schemas.py"]:
        kind = "schema_validation"
    elif command[2:4] == ["python", "scripts/rig_relay_storage_audit.py"]:
        kind = "storage_audit"
    elif command[2:4] == ["python", "scripts/rig_relay_desktop_cockpit.py"]:
        kind = "desktop_cockpit_dry_run"
    elif command[2:4] == ["ruff", "format"]:
        kind = "ruff_format_fix"
    return kind


def _summarize_results(
    step_results: list[ValidationStepResult], max_preview_bytes: int
) -> tuple[str, str, str, str]:
    stdout_blob = "".join(step.stdout_preview for step in step_results).encode("utf-8")
    stderr_blob = "".join(step.stderr_preview for step in step_results).encode("utf-8")
    stdout_sha256 = "sha256:" + hashlib.sha256(stdout_blob).hexdigest()
    stderr_sha256 = "sha256:" + hashlib.sha256(stderr_blob).hexdigest()
    return (
        stdout_sha256,
        stderr_sha256,
        stdout_blob[:max_preview_bytes].decode("utf-8", errors="replace"),
        stderr_blob[:max_preview_bytes].decode("utf-8", errors="replace"),
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()
    )


def _suite_id(args: ValidationSuiteArgs) -> str:
    payload = args.model_dump(mode="json", exclude_none=True)
    return _hash_payload(payload)[7:23]

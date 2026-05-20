from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skipped"


class CompilerGate(StrEnum):
    SCHEMA_VALIDATION = "schema_validation"
    IMPORTABILITY = "importability"
    PYRIGHT = "pyright_type_check"
    RUFF_LINT = "ruff_lint"
    RUFF_FORMAT = "ruff_format"
    JSON_ROUNDTRIP = "json_roundtrip"
    ADVERSARIAL = "adversarial_input"
    DETERMINISTIC = "deterministic_regen"
    REDACTION = "content_redaction"
    DIRTY_CHECK = "dirty_check"

    @property
    def gate_id(self) -> str:
        return f"gate-{self.value}"

    @property
    def failure_class(self) -> str:
        _map: dict[str, str] = {
            "schema_validation": "constraint_violation",
            "importability": "type_error",
            "pyright_type_check": "type_error",
            "ruff_lint": "format_error",
            "ruff_format": "format_error",
            "json_roundtrip": "constraint_violation",
            "adversarial_input": "constraint_violation",
            "deterministic_regen": "constraint_violation",
            "content_redaction": "redaction_leak",
            "dirty_check": "worktree_dirty_state",
        }
        return _map.get(self.value, "constraint_violation")


class GateResult(BaseModel):
    gate_id: str
    gate_kind: str
    status: GateStatus
    evidence_hash: str
    duration_ms: int = 0


class GateMatrix(BaseModel):
    gates: list[GateResult] = Field(default_factory=list)

    def add(self, result: GateResult) -> None:
        self.gates.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for g in self.gates if g.status == GateStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for g in self.gates if g.status == GateStatus.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for g in self.gates if g.status == GateStatus.SKIP)

    @property
    def total(self) -> int:
        return len(self.gates)

    @property
    def overall_status(self) -> GateStatus:
        if self.failed > 0:
            return GateStatus.FAIL
        return GateStatus.PASS


STANDARD_GATE_MATRIX = GateMatrix()

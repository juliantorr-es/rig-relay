from __future__ import annotations

from enum import StrEnum, auto

from rig_relay.context.assembly_plan import (
    CandidateKind,
    CandidateRelation,
    CandidateSource,
    ContextAssemblyPlan,
    ContextBudgetLedger,
    ContextCandidate,
    ContextOmission,
    ContextSelection,
)


class CompilerKind(StrEnum):
    CONTEXT = auto()
    SCHEMA_TO_CODE = auto()


class ValidationGranularity(StrEnum):
    PACKAGE = auto()
    FILE = auto()
    LINE = auto()


__all__ = [
    "CandidateKind",
    "CandidateRelation",
    "CandidateSource",
    "CompilerKind",
    "ContextAssemblyPlan",
    "ContextBudgetLedger",
    "ContextCandidate",
    "ContextOmission",
    "ContextSelection",
    "ValidationGranularity",
]

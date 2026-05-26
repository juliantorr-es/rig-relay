"""Recovery Constraint Capability Admission Service — D3.

Typed internal application service that determines whether a configured
local runtime is suitable for a required recovery constraint class.

Read-side, content-light, Lane D-owned. Consumes canonical D2 evidence
and published capability dispositions. Never executes model generation
as part of ordinary evidence querying.

Separates JSON-object formatting, native JSON Schema enforcement, and
grammar/GBNF enforcement into distinct capability classes. Refuses to
certify a runtime for a stronger class than canonical evidence demonstrates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.recovery.constrained_execution import ConstrainedExecutionResult


class EnforcementClass(StrEnum):
    """Capability enforcement classes, strongest first."""

    UNSUPPORTED = "unsupported"
    JSON_OBJECT_FORMATTING_ONLY = "json_object_formatting_only"
    NATIVE_JSON_SCHEMA = "native_json_schema"
    NATIVE_GRAMMAR_GBNF = "native_grammar_gbnf"


_ENFORCEMENT_CLASS_RANK = {
    EnforcementClass.UNSUPPORTED: 0,
    EnforcementClass.JSON_OBJECT_FORMATTING_ONLY: 1,
    EnforcementClass.NATIVE_JSON_SCHEMA: 2,
    EnforcementClass.NATIVE_GRAMMAR_GBNF: 3,
}


class ConstraintCapabilityDisposition(BaseModel):
    """Snapshot of a runtime's demonstrated constraint enforcement capability.

    Content-light: runtime metadata, hashes, classifications only.
    Never contains raw prompts, completions, or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.constraint_capability_disposition.v1", frozen=True
    )
    disposition_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    runtime_kind: str
    runtime_endpoint_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    model_name_hash: str = ""
    enforced_mechanism: str = ""
    highest_enforcement_class_demonstrated: EnforcementClass = (
        EnforcementClass.UNSUPPORTED
    )
    json_object_formatting_demonstrated: bool = False
    json_schema_enforcement_demonstrated: bool = False
    json_schema_enforcement_receipt_bound: bool = False
    grammar_enforcement_demonstrated: bool = False
    evidence_from_captured_local_model: bool = False
    proof_event_ids: list[str] = Field(default_factory=list)
    proof_run_count: int = 0
    curated_fixture_run_count: int = 0
    proposal_only_mutation_preserved: bool = False
    constraint_receipt_digest: str = ""
    manifest_digest: str = ""
    enforced_schema_digests: list[str] = Field(default_factory=list)


class CapabilityAdmissionDecision(BaseModel):
    """Answer to 'can this runtime satisfy this constraint requirement?'

    Content-light: decisions, references, classifications only.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.capability_admission_decision.v1", frozen=True
    )
    decision_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    requested_enforcement_class: EnforcementClass
    runtime_capable: bool = False
    reason: str = ""
    evidence_disposition_digest: str = ""
    evidence_events_referenced: list[str] = Field(default_factory=list)
    evidence_from_captured_local_model: bool = False
    stronger_mechanism_unavailable: bool = True
    recommendation: str = ""


class CapabilityQuery(BaseModel):
    """Application-facing query for runtime capability admission."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    required_enforcement_class: EnforcementClass
    require_captured_local_model_evidence: bool = True
    require_receipt_bound: bool = True
    allow_curated_fixtures: bool = False


class RecoveryConstraintCapabilityAdmissionService:
    """Typed internal service for recovery constraint capability admission.

    Consumes canonical D2 evidence through ConstrainedExecutionResult records
    and published ConstraintEnforcementDisposition objects.

    Read-side only: never executes model generation. Never modifies
    recovery evidence, runtime configuration, provider state, or any
    handoff/execution authority.
    """

    def __init__(self) -> None:
        self._dispositions: dict[str, ConstraintCapabilityDisposition] = {}

    def register_disposition(
        self, disposition: ConstraintCapabilityDisposition
    ) -> None:
        """Register a runtime capability disposition from canonical evidence."""
        self._dispositions[disposition.disposition_id] = disposition

    def admit_capability(
        self, query: CapabilityQuery, *, disposition_id: str | None = None
    ) -> CapabilityAdmissionDecision:
        """Decide whether a registered runtime satisfies the required class.

        If disposition_id is None, uses the most recent registered disposition.
        """
        if not self._dispositions:
            return CapabilityAdmissionDecision(
                decision_id=f"dec_{query.query_id}",
                requested_enforcement_class=query.required_enforcement_class,
                runtime_capable=False,
                reason="No runtime capability dispositions registered",
                stronger_mechanism_unavailable=True,
                recommendation="Configure and exercise a local runtime before querying capability admission",
            )

        target_id = disposition_id or sorted(self._dispositions.keys())[-1]
        disp = self._dispositions.get(target_id)
        if disp is None:
            return CapabilityAdmissionDecision(
                decision_id=f"dec_{query.query_id}",
                requested_enforcement_class=query.required_enforcement_class,
                runtime_capable=False,
                reason=f"Disposition {target_id} not found",
                stronger_mechanism_unavailable=True,
                recommendation="Register the runtime capability disposition before querying",
            )

        return _admit_one(disp, query)

    def list_dispositions(self) -> list[ConstraintCapabilityDisposition]:
        """Return all registered dispositions (read-only snapshot)."""
        return sorted(
            self._dispositions.values(), key=lambda d: d.created_at, reverse=True
        )

    def query_capability(
        self,
        query_id: str,
        required_class: EnforcementClass,
        *,
        require_captured: bool = True,
    ) -> CapabilityAdmissionDecision:
        """Convenience query wrapper."""
        return self.admit_capability(
            CapabilityQuery(
                query_id=query_id,
                required_enforcement_class=required_class,
                require_captured_local_model_evidence=require_captured,
            )
        )


def _admit_one(
    disposition: ConstraintCapabilityDisposition, query: CapabilityQuery
) -> CapabilityAdmissionDecision:
    dec_id = f"dec_{query.query_id}"

    demonstrated_class = disposition.highest_enforcement_class_demonstrated
    demonstrated_rank = _ENFORCEMENT_CLASS_RANK[demonstrated_class]
    required_rank = _ENFORCEMENT_CLASS_RANK[query.required_enforcement_class]

    if (
        not disposition.evidence_from_captured_local_model
        and query.require_captured_local_model_evidence
    ):
        return CapabilityAdmissionDecision(
            decision_id=dec_id,
            requested_enforcement_class=query.required_enforcement_class,
            runtime_capable=False,
            reason=(
                f"Required enforcement class {query.required_enforcement_class.value} "
                f"requires captured local model evidence, but disposition "
                f"{disposition.disposition_id} lacks it"
            ),
            evidence_disposition_digest=_compute_disposition_digest(disposition),
            evidence_events_referenced=list(disposition.proof_event_ids),
            evidence_from_captured_local_model=False,
            stronger_mechanism_unavailable=True,
            recommendation="Exercise the runtime with captured local model calls before querying admission",
        )

    evidence_from = disposition.evidence_from_captured_local_model

    if (
        query.require_receipt_bound
        and query.required_enforcement_class
        in {EnforcementClass.NATIVE_JSON_SCHEMA, EnforcementClass.NATIVE_GRAMMAR_GBNF}
        and not disposition.json_schema_enforcement_receipt_bound
    ):
        return CapabilityAdmissionDecision(
            decision_id=dec_id,
            requested_enforcement_class=query.required_enforcement_class,
            runtime_capable=False,
            reason=(
                f"Native enforcement is demonstrated but the enforced schema "
                f"is not digest-bound to a canonical ConstraintCompilationReceipt. "
                f"Receipt binding is required for governed {query.required_enforcement_class.value} admission."
            ),
            evidence_disposition_digest=_compute_disposition_digest(disposition),
            evidence_events_referenced=list(disposition.proof_event_ids),
            evidence_from_captured_local_model=evidence_from,
            stronger_mechanism_unavailable=True,
            recommendation=(
                "Re-run constrained execution with a receipt that carries per-tool "
                "schema digests, and verify the enforced schema digest matches the receipt"
            ),
        )

    _native_json_schema_rank = 2
    if demonstrated_rank < required_rank:
        stronger_available = demonstrated_rank < _native_json_schema_rank
        return CapabilityAdmissionDecision(
            decision_id=dec_id,
            requested_enforcement_class=query.required_enforcement_class,
            runtime_capable=False,
            reason=(
                f"Demonstrated enforcement class {demonstrated_class.value} "
                f"is weaker than required {query.required_enforcement_class.value}"
            ),
            evidence_disposition_digest=_compute_disposition_digest(disposition),
            evidence_events_referenced=list(disposition.proof_event_ids),
            evidence_from_captured_local_model=evidence_from,
            stronger_mechanism_unavailable=not stronger_available,
            recommendation=(
                f"Upgrade runtime to support {query.required_enforcement_class.value} "
                "or reduce the required enforcement class"
            ),
        )

    return CapabilityAdmissionDecision(
        decision_id=dec_id,
        requested_enforcement_class=query.required_enforcement_class,
        runtime_capable=True,
        reason=(
            f"Demonstrated enforcement class {demonstrated_class.value} "
            f"satisfies required {query.required_enforcement_class.value}. "
            f"Evidence from {disposition.proof_run_count} proof runs."
        ),
        evidence_disposition_digest=_compute_disposition_digest(disposition),
        evidence_events_referenced=list(disposition.proof_event_ids),
        evidence_from_captured_local_model=evidence_from,
        stronger_mechanism_unavailable=True,
        recommendation="Runtime is suitable for the requested constraint enforcement class",
    )


def build_constraint_capability_disposition(
    *,
    disposition_id: str,
    runtime_kind: str,
    runtime_endpoint: str,
    model_name: str,
    results: list[ConstrainedExecutionResult],
    constraint_receipt_digest: str = "",
    manifest_digest: str = "",
) -> ConstraintCapabilityDisposition:
    """Build a capability disposition from execution results.

    Distinguishes captured local model evidence from curated fixtures.
    Determines the highest enforcement class actually demonstrated.
    """
    endpoint_hash = f"sha256:{hashlib.sha256(runtime_endpoint.encode()).hexdigest()}"
    model_hash = (
        f"sha256:{hashlib.sha256(model_name.encode()).hexdigest()}"
        if model_name
        else ""
    )

    captured_count = 0
    curated_count = 0
    json_object_demonstrated = False
    json_schema_demonstrated = False
    json_schema_receipt_bound = False
    grammar_demonstrated = False
    proposal_only_preserved = False
    proof_ids: list[str] = []
    enforced_mechanism = ""
    enforced_schema_digests: list[str] = []

    for i, r in enumerate(results):
        if r.execution_status != "executed":
            continue

        if r.emission_source_kind == "captured_local_model" or (
            not r.emission_source_kind
            and r.emission_sha256
            and r.output_token_count > 0
        ):
            captured_count += 1
            proof_ids.append(f"proof_{disposition_id}_{i:02d}")
        else:
            curated_count += 1

        if (
            r.enforced_schema_digest
            and r.constraint_receipt_digest
            and r.receipt_loaded_from_durable_evidence
        ):
            json_schema_receipt_bound = True
            enforced_schema_digests.append(r.enforced_schema_digest)

        disp = r.constraint_enforcement_disposition
        if disp:
            if disp.json_schema_enforcement_exercised:
                json_schema_demonstrated = True
                enforced_mechanism = disp.enforced_mechanism or enforced_mechanism
            if disp.json_object_enforcement_exercised:
                json_object_demonstrated = True
            if disp.grammar_enforcement_exercised:
                grammar_demonstrated = True

        if r.proposal_only:
            proposal_only_preserved = True

    if json_schema_demonstrated:
        highest = EnforcementClass.NATIVE_JSON_SCHEMA
    elif json_object_demonstrated:
        highest = EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
    else:
        highest = EnforcementClass.UNSUPPORTED

    return ConstraintCapabilityDisposition(
        disposition_id=disposition_id,
        runtime_kind=runtime_kind,
        runtime_endpoint_hash=endpoint_hash,
        model_name_hash=model_hash,
        enforced_mechanism=enforced_mechanism,
        highest_enforcement_class_demonstrated=highest,
        json_object_formatting_demonstrated=json_object_demonstrated,
        json_schema_enforcement_demonstrated=json_schema_demonstrated,
        json_schema_enforcement_receipt_bound=json_schema_receipt_bound,
        grammar_enforcement_demonstrated=grammar_demonstrated,
        evidence_from_captured_local_model=captured_count > 0,
        proof_event_ids=proof_ids,
        proof_run_count=captured_count,
        curated_fixture_run_count=curated_count,
        proposal_only_mutation_preserved=proposal_only_preserved,
        constraint_receipt_digest=constraint_receipt_digest,
        manifest_digest=manifest_digest,
        enforced_schema_digests=enforced_schema_digests,
    )


def compute_capability_projection(
    dispositions: list[ConstraintCapabilityDisposition],
    *,
    projection_id: str | None = None,
) -> dict[str, Any]:
    """Build deterministic capability projection from dispositions.

    Content-light: counts, hashes, classifications only.
    Designed for desktop/Gridline consumption.
    """
    pid = projection_id or f"capproj_{datetime.now(UTC).isoformat()}"
    total = len(dispositions)

    if total == 0:
        proj: dict[str, Any] = {
            "schema_version": "rig.relay.capability_projection.v1",
            "projection_id": pid,
            "created_at": datetime.now(UTC).isoformat(),
            "disposition_count": 0,
            "projection_digest": "",
        }
        return proj

    classes_demonstrated: dict[str, int] = {}
    captured_total = 0
    curated_total = 0
    proposal_preserved_count = 0
    runtimes: list[dict[str, Any]] = []

    for d in dispositions:
        cls = d.highest_enforcement_class_demonstrated.value
        classes_demonstrated[cls] = classes_demonstrated.get(cls, 0) + 1
        captured_total += d.proof_run_count
        curated_total += d.curated_fixture_run_count
        if d.proposal_only_mutation_preserved:
            proposal_preserved_count += 1
        runtimes.append({
            "disposition_id": d.disposition_id,
            "runtime_kind": d.runtime_kind,
            "model_name_hash": d.model_name_hash,
            "highest_class": d.highest_enforcement_class_demonstrated.value,
            "json_schema_demonstrated": d.json_schema_enforcement_demonstrated,
            "grammar_demonstrated": d.grammar_enforcement_demonstrated,
            "captured_proof_count": d.proof_run_count,
            "proposal_only_preserved": d.proposal_only_mutation_preserved,
        })

    projection: dict[str, Any] = {
        "schema_version": "rig.relay.capability_projection.v1",
        "projection_id": pid,
        "created_at": datetime.now(UTC).isoformat(),
        "disposition_count": total,
        "enforcement_classes_demonstrated": classes_demonstrated,
        "total_captured_local_proof_runs": captured_total,
        "total_curated_fixture_runs": curated_total,
        "proposal_only_mutation_preserved_count": proposal_preserved_count,
        "runtimes": runtimes,
    }
    digest_payload = {
        k: v
        for k, v in projection.items()
        if k not in {"projection_digest", "created_at"}
    }
    payload = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    projection["projection_digest"] = (
        f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    )
    return projection


def _compute_disposition_digest(disposition: ConstraintCapabilityDisposition) -> str:
    data = disposition.model_dump(mode="json")
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


__all__ = [
    "CapabilityAdmissionDecision",
    "CapabilityQuery",
    "ConstraintCapabilityDisposition",
    "EnforcementClass",
    "RecoveryConstraintCapabilityAdmissionService",
    "build_constraint_capability_disposition",
    "compute_capability_projection",
]

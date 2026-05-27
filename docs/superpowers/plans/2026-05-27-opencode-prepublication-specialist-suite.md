# OpenCode Prepublication Specialist Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-local OpenCode prepublication review suite that runs a parallel hostile audit before publication, emits schema-backed candidate and disposition records, and keeps publication authority separate from internal review.

**Architecture:** A builder prepares an immutable claim packet, a prepublication conductor dispatches required specialist adversaries in parallel, and the conductor combines findings mechanically without awarding release authority. Project-local OpenCode agent files and command files define the suite, repository config constrains invocation permissions, and canonical JSON schemas capture the packet, specialist findings, and combined disposition. A separate remote-main reviewer remains outside the builder-side subagent path and independently verifies or invalidates the published candidate.

**Tech Stack:** OpenCode project config (`opencode.json`, `.opencode/agents/`, `.opencode/commands/`), Python 3.12+, `pytest`, `jsonschema`, repo governance docs under `docs/governance/`, schema files under `docs/schemas/`.

---

### Task 1: Lock the canonical prepublication contract

**Files:**
- Modify: `docs/governance/reviewer-orchestrator.md`
- Modify: `docs/governance/orchestrator-subagent-model.md`
- Create: `docs/governance/prepublication-falsifier-contract.md`

- [ ] **Step 1: Write the contract text**

```markdown
# Prepublication Falsifier Contract

## Roles

- `builder`: prepares the typed candidate packet and cannot award publication.
- `prepublication-conductor`: orchestration only; dispatches auditors and mechanically combines verdicts.
- `claim-adversary`: single-agent fallback for narrow lanes only.
- `specialist adversaries`: read-only hostile auditors for one failure domain each.
- `publication-authorized actor`: may push only after admitted canonical evidence exists.
- `remote-main reviewer`: independent post-publication verifier.

## Verdict lattice

- any `falsified_blocking` result inside the declared boundary forces `prepublication_blocked`
- any material assertion required for the requested status that remains `unproven_material` forces `prepublication_inconclusive`
- only full satisfaction of all required attack domains without blocking findings permits `prepublication_admitted`

## Packet invariants

- the prepublication packet is immutable during review
- the packet contains `candidate_checkpoint_sha`, `candidate_base_remote_sha`, `intended_publication_ref`, `changed_file_slice`, and `working_tree_exclusions`
- the packet must not contain a remote publication SHA before push
- specialists receive the same immutable packet digest
- the conductor does not rewrite specialist findings
```

- [ ] **Step 2: Update the existing orchestrator doctrine to match the new role split**

```markdown
- replace any wording that makes a single reviewer both orchestrator and audit authority
- state that the conductor dispatches specialist adversaries and combines verdicts mechanically
- state that the builder cannot self-award publication admission, release, or freeze
- state that the independent remote-main reviewer remains a separate authority
```

- [ ] **Step 3: Run the narrow docs checks that cover doctrine drift**

Run:
```bash
uv run pytest tests/governance/test_cross_surface_v1_convergence_review.py tests/governance/test_event_fabric_command_boundary.py tests/review_projection/test_acceptance_gate.py -v
```
Expected: the updated governance text still satisfies the existing doctrine and no review-packet assumptions regress.

### Task 2: Add schema-backed prepublication packet, finding, and disposition records

**Files:**
- Create: `docs/schemas/rig.relay.prepublication_claim_packet.v1.schema.json`
- Create: `docs/schemas/rig.relay.prepublication_specialist_finding.v1.schema.json`
- Create: `docs/schemas/rig.relay.prepublication_disposition.v1.schema.json`
- Modify: `docs/schemas/rig.relay.prepublication_review_cycle.v1.schema.json`
- Modify: `docs/schemas/rig.relay.builder_publication_record.v1.schema.json`
- Modify: `docs/schemas/rig.relay.verification_record.v1.schema.json`
- Create: `rig_relay/orchestrator/prepublication.py`
- Modify: `rig_relay/orchestrator/__init__.py`
- Create: `tests/orchestrator/test_prepublication_suite.py`
- Modify: `tests/coordination/test_schema_validation.py`

- [ ] **Step 1: Write the failing schema tests**

```python
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def _schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_claim_packet_requires_candidate_binding_fields() -> None:
    packet = {
        "schema_version": "rig.relay.prepublication_claim_packet.v1",
        "generated_at": "2026-05-27T00:00:00Z",
        "mission_id": "mission-1",
        "lane_id": "lane-1",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=packet, schema=_schema("rig.relay.prepublication_claim_packet.v1"))


def test_specialist_finding_enforces_hostile_outcomes() -> None:
    finding = {
        "schema_version": "rig.relay.prepublication_specialist_finding.v1",
        "generated_at": "2026-05-27T00:00:00Z",
        "mission_id": "mission-1",
        "lane_id": "lane-1",
        "specialist_name": "authority-adversary",
        "packet_digest": "sha256:abc",
        "assertions_attacked": [],
        "findings": [],
        "outcome": "not_a_real_outcome",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=finding, schema=_schema("rig.relay.prepublication_specialist_finding.v1"))
```

- [ ] **Step 2: Implement the schemas and the orchestrator models**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://rig-relay.vibe.dev/schemas/rig.relay.prepublication_claim_packet.v1.schema.json",
  "title": "Prepublication Claim Packet v1",
  "description": "Immutable builder-authored candidate packet handed to hostile prepublication review.",
  "type": "object",
  "required": [
    "schema_version",
    "generated_at",
    "mission_id",
    "lane_id",
    "candidate_checkpoint_sha",
    "candidate_base_remote_sha",
    "intended_publication_ref",
    "requested_status",
    "declared_boundary",
    "consumer_purpose",
    "authority_owner",
    "changed_file_slice",
    "canonical_evidence_artifacts",
    "production_proof_commands",
    "deferred_seams",
    "working_tree_exclusions",
    "required_specialists",
    "immutable_packet_digest"
  ],
  "additionalProperties": false
}
```

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrepublicationFindingOutcome(StrEnum):
    FALSIFIED_BLOCKING = "falsified_blocking"
    SURVIVED_ATTACK = "survived_attack"
    UNPROVEN_MATERIAL = "unproven_material"
    DEFERRED_OUTSIDE_BOUNDARY = "deferred_outside_boundary"
    INFORMATIONAL = "informational"


class PrepublicationClaimPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.prepublication_claim_packet.v1"
    generated_at: str
    mission_id: str
    lane_id: str
    candidate_checkpoint_sha: str
    candidate_base_remote_sha: str
    intended_publication_ref: str
    requested_status: str
    declared_boundary: str
    consumer_purpose: str
    authority_owner: str
    changed_file_slice: list[str] = Field(default_factory=list)
    canonical_evidence_artifacts: list[str] = Field(default_factory=list)
    production_proof_commands: list[str] = Field(default_factory=list)
    deferred_seams: list[str] = Field(default_factory=list)
    working_tree_exclusions: list[str] = Field(default_factory=list)
    required_specialists: list[str] = Field(default_factory=list)
    immutable_packet_digest: str


class PrepublicationSpecialistFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.prepublication_specialist_finding.v1"
    generated_at: str
    mission_id: str
    lane_id: str
    specialist_name: str
    packet_digest: str
    assertions_attacked: list[str] = Field(default_factory=list)
    findings: list[dict[str, str]] = Field(default_factory=list)
    outcome: PrepublicationFindingOutcome


class PrepublicationDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.prepublication_disposition.v1"
    packet_digest: str
    status: str
    specialist_finding_digests: list[str] = Field(default_factory=list)


def combine_prepublication_specialist_findings(
    *, packet_digest: str, findings: list[dict[str, str]]
) -> PrepublicationDisposition:
    if any(f["outcome"] == PrepublicationFindingOutcome.FALSIFIED_BLOCKING.value for f in findings):
        return PrepublicationDisposition(
            packet_digest=packet_digest,
            status="prepublication_blocked",
            specialist_finding_digests=[],
        )
    if any(f["outcome"] == PrepublicationFindingOutcome.UNPROVEN_MATERIAL.value for f in findings):
        return PrepublicationDisposition(
            packet_digest=packet_digest,
            status="prepublication_inconclusive",
            specialist_finding_digests=[],
        )
return PrepublicationDisposition(
        packet_digest=packet_digest,
        status="prepublication_admitted",
        specialist_finding_digests=[],
    )
```

- [ ] **Step 2b: Add the disposition schema**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://rig-relay.vibe.dev/schemas/rig.relay.prepublication_disposition.v1.schema.json",
  "title": "Prepublication Disposition v1",
  "description": "Mechanical conductor output after hostile specialist findings are combined.",
  "type": "object",
  "required": [
    "schema_version",
    "packet_digest",
    "status",
    "specialist_finding_digests"
  ],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "rig.relay.prepublication_disposition.v1"
    },
    "packet_digest": { "type": "string" },
    "status": {
      "type": "string",
      "enum": [
        "prepublication_admitted",
        "prepublication_blocked",
        "prepublication_inconclusive"
      ]
    },
    "specialist_finding_digests": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 3: Add the mechanical conductor function**

```python
from rig_relay.orchestrator.prepublication import (
    PrepublicationDisposition,
    PrepublicationFindingOutcome,
    combine_prepublication_specialist_findings,
)


def test_one_blocking_specialist_forces_block() -> None:
    disposition = combine_prepublication_specialist_findings(
        packet_digest="sha256:packet",
        findings=[
            {"specialist_name": "authority-adversary", "outcome": PrepublicationFindingOutcome.SURVIVED_ATTACK.value},
            {"specialist_name": "evidence-adversary", "outcome": PrepublicationFindingOutcome.SURVIVED_ATTACK.value},
            {"specialist_name": "production-proof-adversary", "outcome": PrepublicationFindingOutcome.SURVIVED_ATTACK.value},
            {"specialist_name": "claim-scope-adversary", "outcome": PrepublicationFindingOutcome.SURVIVED_ATTACK.value},
            {"specialist_name": "lane-collision-adversary", "outcome": PrepublicationFindingOutcome.FALSIFIED_BLOCKING.value},
        ],
    )
    assert disposition.status == "prepublication_blocked"


def test_unproven_material_forces_inconclusive() -> None:
    disposition = combine_prepublication_specialist_findings(
        packet_digest="sha256:packet",
        findings=[
            {"specialist_name": "authority-adversary", "outcome": PrepublicationFindingOutcome.SURVIVED_ATTACK.value},
            {"specialist_name": "evidence-adversary", "outcome": PrepublicationFindingOutcome.UNPROVEN_MATERIAL.value},
        ],
    )
    assert disposition.status == "prepublication_inconclusive"
```

- [ ] **Step 4: Run schema validation and orchestrator tests**

Run:
```bash
uv run python scripts/rig_relay_validate_schemas.py
uv run pytest tests/coordination/test_schema_validation.py tests/orchestrator/test_prepublication_suite.py -v
```
Expected: the new schemas validate, the Pydantic models serialize cleanly, and the conductor obeys the verdict lattice.

### Task 3: Add project-local OpenCode agent profiles and command files

**Files:**
- Create: `.opencode/agents/prepublication-conductor.md`
- Create: `.opencode/agents/claim-adversary.md`
- Create: `.opencode/agents/claim-scope-adversary.md`
- Create: `.opencode/agents/authority-adversary.md`
- Create: `.opencode/agents/evidence-adversary.md`
- Create: `.opencode/agents/production-proof-adversary.md`
- Create: `.opencode/agents/recovery-adversary.md`
- Create: `.opencode/agents/security-adversary.md`
- Create: `.opencode/agents/lane-collision-adversary.md`
- Create: `.opencode/agents/remote-main-reviewer.md`
- Create: `.opencode/commands/prepublication-review.md`
- Create: `.opencode/commands/remote-main-review.md`
- Modify: `opencode.json`
- Create: `tests/integrations/test_opencode_agents.py`
- Modify: `tests/integrations/test_opencode_config.py`

- [ ] **Step 1: Write the failing filesystem assertions**

```python
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"
COMMANDS_DIR = REPO_ROOT / ".opencode" / "commands"


def _frontmatter(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    _, frontmatter, _ = raw.split("---", 2)
    return yaml.safe_load(frontmatter) or {}


def test_prepublication_agents_exist() -> None:
    for name in [
        "prepublication-conductor.md",
        "claim-adversary.md",
        "claim-scope-adversary.md",
        "authority-adversary.md",
        "evidence-adversary.md",
        "production-proof-adversary.md",
        "recovery-adversary.md",
        "security-adversary.md",
        "lane-collision-adversary.md",
        "remote-main-reviewer.md",
    ]:
        assert (AGENTS_DIR / name).exists()


def test_prepublication_command_targets_conductor() -> None:
    fm = _frontmatter(COMMANDS_DIR / "prepublication-review.md")
    assert fm["subagent"] == "prepublication-conductor"
    assert fm["subtask"] is True
```

- [ ] **Step 2: Create the agent markdown files with hidden subagent frontmatter and read-only hostile prompts**

```markdown
---
description: Dispatches hostile specialists for prepublication review and combines their verdicts mechanically.
mode: subagent
hidden: true
temperature: 0.1
steps: 40
permission:
  edit: deny
  task:
    "*": deny
  bash:
    "*": ask
---

You are the prepublication conductor. You do not decide whether the implementation looks good. You collect a typed candidate packet, dispatch only the required specialist adversaries, and combine their outcomes mechanically:

- any blocking finding => `prepublication_blocked`
- any unproven material assertion => `prepublication_inconclusive`
- otherwise => `prepublication_admitted`
```

```markdown
---
description: Falsifies builder claims for narrow lanes by attacking the exact requested status, boundary, and evidence.
mode: subagent
hidden: true
temperature: 0.1
steps: 40
permission:
  edit: deny
  task: deny
  bash:
    "*": ask
---

Treat the candidate claim as hostile input. Convert every noun and adjective in the requested status into a falsifiable assertion. Attack authority, evidence, recovery, production proof, scope, and lane collision. Return only assertion-level outcomes.
```

```markdown
---
description: Runs the independent remote-main review against a published candidate boundary.
mode: subagent
hidden: true
temperature: 0.1
steps: 40
permission:
  edit: deny
  task: deny
  bash:
    "*": ask
---

Inspect remote truth only. Do not reuse builder-side verdicts as release authority. Compare the published candidate against canonical remote evidence and emit an independent verification record.
```

- [ ] **Step 3: Update `opencode.json` permissions so builder-side execution cannot self-push and only governed review commands remain available**

```json
{
  "permission": {
    "bash": {
      "*": "ask",
      "git status*": "allow",
      "git diff*": "allow",
      "git show*": "allow",
      "git branch*": "allow",
      "git log*": "allow",
      "git push*": "deny",
      "git merge*": "deny",
      "git rebase*": "deny",
      "git reset*": "deny",
      "git restore*": "deny",
      "git clean*": "deny",
      "git stash*": "deny",
      "uv run pytest*": "allow",
      "uv run python scripts/rig_relay_validate_schemas.py": "allow"
    },
    "task": {
      "*": "deny",
      "prepublication-conductor": "allow",
      "claim-adversary": "allow"
    },
    "edit": "allow"
  }
}
```

Replace with repo-local controls that:

- deny builder `git push`
- allow controlled read and validation commands
- allow `Task` only for `prepublication-conductor` and `claim-adversary`
- deny special-agent self-recursion
- keep `remote-main-reviewer` invokable only as a separate session, not as a builder child

- [ ] **Step 4: Run OpenCode config tests and agent frontmatter tests**

Run:
```bash
uv run pytest tests/integrations/test_opencode_agents.py tests/integrations/test_opencode_config.py -v
```
Expected: the repository declares the new agent suite, the command files target the correct subagents, and the config no longer overgrants publication authority.

### Task 4: Extend the orchestrator profile registry for the suite

**Files:**
- Modify: `rig_relay/orchestrator/subagent_profiles.py`
- Modify: `rig_relay/orchestrator/__init__.py`
- Create: `tests/orchestrator/test_prepublication_profiles.py`

- [ ] **Step 1: Add failing assertions for the new profile set**

```python
from __future__ import annotations

from rig_relay.orchestrator.subagent_profiles import build_prepublication_profiles


def test_prepublication_profiles_are_registered() -> None:
    registry = build_prepublication_profiles()
    names = {profile.profile_id for profile in registry.list_all()}
    assert "profile-prepublication-conductor" in names
    assert "profile-claim-adversary" in names
    assert "profile-remote-main-reviewer" in names
    assert "profile-authority-adversary" in names
    assert "profile-evidence-adversary" in names
```

- [ ] **Step 2: Add the new profile records without changing the existing six demo profiles**

```python
SubagentProfile(
    profile_id="profile-prepublication-conductor",
    display_name="Prepublication Conductor",
    profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
    role="Dispatches and aggregates hostile prepublication auditors",
    description="Orchestrates the prepublication review suite without awarding release authority",
    allowed_capabilities=["read_file", "grep", "validate"],
    forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
    trust_tier=TrustTier.OBSERVE.value,
    can_mutate=False,
    can_run_validators=True,
    can_commit=False,
    assignable=True,
)
```

```python
SubagentProfile(
    profile_id="profile-remote-main-reviewer",
    display_name="Remote Main Reviewer",
    profile_kind=PROFILE_KIND_STANDARD_SUBAGENT,
    role="Independent remote-main verifier",
    description="Reads remote truth and validates or invalidates the published candidate",
    allowed_capabilities=["read_file", "grep", "validate"],
    forbidden_capabilities=["merge", "push_remote", "mutate_live_workspace"],
    trust_tier=TrustTier.OBSERVE.value,
    can_mutate=False,
    can_run_validators=True,
    can_commit=False,
    assignable=False,
)
```

- [ ] **Step 3: Add the specialist profiles with narrow hostile capabilities**

```python
SubagentProfile(
    profile_id="profile-authority-adversary",
    display_name="Authority Adversary",
    role="Attacks bypasses and direct persistence",
    description="Finds any path that bypasses typed application-service authority",
    allowed_capabilities=["read_file", "grep", "validate"],
    forbidden_capabilities=["push_remote", "merge", "mutate_live_workspace"],
    trust_tier=TrustTier.OBSERVE.value,
    can_mutate=False,
    assignable=True,
)
```

- [ ] **Step 4: Run the orchestrator profile tests**

Run:
```bash
uv run pytest tests/orchestrator/test_prepublication_profiles.py tests/orchestrator/test_subagent_profiles.py -v
```
Expected: the new suite profiles exist, the assignment rules stay narrow, and Ralph remains isolated.

### Task 5: Add the conductor synthesis and command-gate regression tests

**Files:**
- Create: `tests/data_plane/postgres/test_prepublication_review_gate.py`
- Modify: `tests/data_plane/postgres/test_x1_materialization.py`
- Modify: `tests/orchestrator/test_prepublication_suite.py`
- Modify: `tests/review_projection/test_acceptance_gate.py`

- [ ] **Step 1: Write the X1.4 blocker regression against the real review-cycle artifact**

```python
from __future__ import annotations

import json
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def test_x1_4_review_cycle_records_five_blockers() -> None:
    record_path = WORKSPACE_ROOT / "docs/json/evidence/prepublication_review_cycle_x1_4.v1.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["status"] == "prepublication_repair_required"
    assert record["final_admission"]["prepublication_admitted"] is False
    assert record["final_admission"]["blocking_findings_found"] == 5
    assert len(record["rounds"][0]["missed_blocking_defects"]) == 5
```

- [ ] **Step 2: Add the non-averaging test for the conductor**

```python
from rig_relay.orchestrator.prepublication import combine_prepublication_specialist_findings


def test_one_blocker_forces_block_even_when_other_specialists_survive() -> None:
    disposition = combine_prepublication_specialist_findings(
        packet_digest="sha256:packet",
        findings=[
            {"specialist_name": "claim-scope-adversary", "outcome": "survived_attack"},
            {"specialist_name": "authority-adversary", "outcome": "survived_attack"},
            {"specialist_name": "evidence-adversary", "outcome": "survived_attack"},
            {"specialist_name": "production-proof-adversary", "outcome": "survived_attack"},
            {"specialist_name": "lane-collision-adversary", "outcome": "falsified_blocking"},
        ],
    )
    assert disposition.status == "prepublication_blocked"
```

- [ ] **Step 3: Add the authority-separation test**

```python
def test_conductor_never_awards_remote_release_or_freeze() -> None:
    disposition = combine_prepublication_specialist_findings(
        packet_digest="sha256:packet",
        findings=[
            {"specialist_name": "claim-scope-adversary", "outcome": "survived_attack"},
            {"specialist_name": "authority-adversary", "outcome": "survived_attack"},
            {"specialist_name": "evidence-adversary", "outcome": "survived_attack"},
            {"specialist_name": "production-proof-adversary", "outcome": "survived_attack"},
        ],
    )
    assert disposition.status in {"prepublication_admitted", "prepublication_inconclusive"}
    assert "verified_narrow_release" not in disposition.model_dump(mode="json").values()
    assert "frozen_pending_integration" not in disposition.model_dump(mode="json").values()
```

- [ ] **Step 4: Run the focused regression slice**

Run:
```bash
uv run pytest tests/data_plane/postgres/test_prepublication_review_gate.py tests/orchestrator/test_prepublication_suite.py tests/review_projection/test_acceptance_gate.py -v
```
Expected: the known-bad X1.4-style candidate is blocked, the repaired candidate is never self-verified, and the conductor obeys the non-averaging rule.

### Task 6: Validate the full suite and publish the candidate record

**Files:**
- Modify: `docs/schemas/rig.relay.prepublication_review_cycle.v1.schema.json`
- Modify: `docs/schemas/rig.relay.builder_publication_record.v1.schema.json`
- Modify: `docs/schemas/rig.relay.verification_record.v1.schema.json`
- Modify: `docs/json/evidence/prepublication_review_cycle_x1_4.v1.json`
- Modify: `docs/governance/reviewer-orchestrator.md`
- Modify: `.opencode/agents/*.md`
- Modify: `.opencode/commands/*.md`
- Modify: `opencode.json`

- [ ] **Step 1: Run schema validation for all updated JSON Schema files**

Run:
```bash
uv run python scripts/rig_relay_validate_schemas.py
```
Expected: every schema remains valid JSON and JSON Schema.

- [ ] **Step 2: Run the OpenCode config, agent, and orchestrator tests together**

Run:
```bash
uv run pytest tests/integrations/test_opencode_agents.py tests/integrations/test_opencode_config.py tests/orchestrator/test_prepublication_profiles.py tests/orchestrator/test_prepublication_suite.py tests/data_plane/postgres/test_prepublication_review_gate.py -v
```
Expected: the suite is declared, the permissions are narrow, the conductor is mechanical, and the regressions cover the escaped X1 defects.

- [ ] **Step 3: Capture the implementation boundary in the builder publication record**

```json
{
  "schema_version": "rig.relay.builder_publication_record.v1",
  "status": "candidate_local",
  "decision_record": {
    "claim": "OpenCode prepublication specialist suite exists and blocks false publication claims",
    "required_proof": [
      "project-local subagent profiles exist",
      "conductor dispatches specialists",
      "specialist findings are schema-backed",
      "push remains gated by admitted evidence"
    ],
    "observed_proof": [
      "pytest coverage",
      "schema validation",
      "config assertions"
    ],
    "alternative_rejected": [
      {
        "option": "single generic reviewer only",
        "rejection_evidence": "does not separate orchestration from audit authority"
      }
    ],
    "verdict": "candidate_local"
  }
}
```

---

### Coverage Check

- Task 1 covers the governance split and falsifier contract.
- Task 2 covers the canonical packet, finding, disposition, and conductor model surfaces.
- Task 3 covers the committed OpenCode agent suite, command entrypoints, and config routing.
- Task 4 covers the internal profile registry so the new roles are represented in Rig Relay’s own model.
- Task 5 covers the hostile regression set, including the X1.4 evidence artifact and the non-averaging / authority-separation rules.
- Task 6 covers schema validation, repo-wide acceptance, and the publication record boundary.

### Self-Review

- No placeholders remain.
- The conductor is orchestration-only; claim-scope is the auditor.
- Prepublication review is separate from remote-main review.
- The packet uses candidate and intended publication refs before push, and published SHA only after push.
- The plan preserves existing demo profile tests while adding the new suite-specific coverage.

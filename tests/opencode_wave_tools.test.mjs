import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  buildPlanRecord,
  createPlanId,
  writePlanRecord,
} from "../.opencode/tools/opencode_plan_core.mjs"
import {
  buildExecutionArtifact,
  buildPublicationArtifact,
  buildSessionReport,
  buildStressArtifact,
  buildValidationArtifact,
  collectPlanArtifacts,
  readJsonl,
  resolveRepoRoot,
  wavesRoot,
} from "../.opencode/tools/opencode_wave_core.mjs"

test("wave artifacts and report are generated from canonical files", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "opencode-wave-"))

  try {
    const planId = createPlanId({ title: "Wave plan", revision: 1 })
    const planRecord = buildPlanRecord({
      repoRoot,
      planId,
      revision: 1,
      title: "Wave plan",
      objective: "Exercise wave artifact generation.",
      summary: "Plan for executor, validator, red team, and publisher artifacts.",
      assumptions: [],
      constraints: [],
      executionWaves: [],
      acceptanceCriteria: [],
      risks: [],
      openQuestions: [],
      revisionNotes: [],
      parentPlanId: null,
      parentPlanPath: null,
    })
    writePlanRecord(repoRoot, planRecord)

    const execution = buildExecutionArtifact({
      repoRoot,
      plan: planRecord,
      executorName: "executor-a",
      waveId: "execution",
      taskSummary: "Implemented tool plumbing.",
      filesChanged: [".opencode/tools/record_execution_wave.ts"],
      implementationNotes: ["Added canonical artifact output."],
      commandsRun: ["node --test tests/opencode_wave_tools.test.mjs"],
      proofArtifacts: [{ label: "test", path: "tests/opencode_wave_tools.test.mjs", digest: "sha256:abc" }],
      deferredSeams: [],
      openRisks: [],
      boundaryClaim: "executor records an implementation artifact",
    })
    const validation = buildValidationArtifact({
      repoRoot,
      plan: planRecord,
      validatorName: "validator-a",
      waveId: "validation",
      commandsRun: ["uv run pytest tests/opencode/test_plan_artifacts.py -q"],
      pass: true,
      testedBoundary: "OpenCode plan artifacts",
      failedSeams: [],
      missingEvidence: [],
      recommendations: ["Keep schema and artifact names aligned."],
    })
    const stress = buildStressArtifact({
      repoRoot,
      plan: planRecord,
      redTeamName: "red-team-a",
      waveId: "stress",
      attacks: ["missing digest", "mutable artifact"],
      attack_surface: ["plan", "comment ledger", "report"],
      survived: true,
      breakages: [],
      repaired_seams: ["mutable artifact path"],
      recommendations: ["Use immutable plan revisions."],
    })
    const publication = buildPublicationArtifact({
      repoRoot,
      plan: planRecord,
      publisherName: "publisher-a",
      waveId: "publication",
      target_ref: "origin/main",
      pushed_sha: "deadbeef",
      remote_verified: true,
      publication_notes: ["Published the current plan slice."],
      files_published: [execution.filePath, validation.filePath, stress.filePath],
      post_push_checks: ["remote SHA matched"],
    })

    const comments = [
      {
        comment_id: "comment-1",
        created_at: "2026-05-28T12:01:00Z",
        critic_name: "critic-a",
        severity: "major",
        category: "feasibility",
        wave_id: "critique",
        comment: "Plan needs a revision stage.",
        suggested_change: "Add revise_plan to the control flow.",
        references: ["docs/governance/reviewer-orchestrator.md"],
      },
    ]
    const report = buildSessionReport({
      repoRoot,
      plan: planRecord,
      executionArtifacts: [{ artifact_id: execution.artifact.artifact_id, path: execution.filePath, digest: "sha256:1" }],
      validationArtifacts: [{ artifact_id: validation.artifact.artifact_id, path: validation.filePath, digest: "sha256:2" }],
      stressArtifacts: [{ artifact_id: stress.artifact.artifact_id, path: stress.filePath, digest: "sha256:3" }],
      checkpointPreparations: [
        {
          artifact_id: "opencode-checkpoint-prep-20260528T120000Z-acde1234",
          path: "docs/json/opencode/checkpoints/preparations/example.json",
          digest: "sha256:5",
        },
      ],
      checkpointCommits: [
        {
          artifact_id: "opencode-checkpoint-20260528T120000Z-acde1234",
          path: "docs/json/opencode/checkpoints/commits/example.json",
          digest: "sha256:6",
        },
      ],
      publicationArtifacts: [{ artifact_id: publication.artifact.artifact_id, path: publication.filePath, digest: "sha256:4" }],
      planComments: comments,
      reportSummary: "All wave artifacts exist and the plan story is coherent.",
      next_steps: ["Review the report"],
      blocked_seams: [],
    })

    assert.equal(report.artifact.plan_id, planRecord.plan_id)
    assert.equal(report.artifact.plan_comment_count, 1)
    assert.equal(report.artifact.checkpoint_preparations.length, 1)
    assert.equal(report.artifact.checkpoint_commits.length, 1)
    assert.equal(report.artifact.plan_comment_summaries[0].critic_name, "critic-a")
    assert.match(report.filePath, /docs\/json\/opencode\/reports\/.*\.json$/)

    const collected = collectPlanArtifacts(repoRoot, planRecord.plan_id, "/execution/")
    assert.equal(collected.length, 1)
    assert.equal(readJsonl(`${repoRoot}/docs/json/opencode/plans/${planRecord.plan_id}.comments.jsonl`).length, 0)
    assert.ok(wavesRoot(resolveRepoRoot(repoRoot)).includes("docs/json/opencode/waves"))
  } finally {
    rmSync(repoRoot, { recursive: true, force: true })
  }
})

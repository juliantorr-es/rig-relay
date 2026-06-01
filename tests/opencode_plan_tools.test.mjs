import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  appendCommentRecord,
  buildCommentRecord,
  buildPlanRecord,
  commentLedgerPath,
  createPlanId,
  loadPlanRecord,
  normalizeWaves,
  plansRoot,
  resolveRepoRoot,
  toRepoRelative,
  reviewCriticism,
  writePlanRecord,
} from "./../.opencode/tools/opencode_plan_core.mjs"

test("plan helpers normalize waves and paths", () => {
  const repoRoot = resolveRepoRoot("/tmp/example-worktree")
  assert.equal(plansRoot(repoRoot), join(repoRoot, "docs", "json", "opencode", "plans"))
  assert.deepEqual(
    normalizeWaves([
      {
        wave_id: "critique",
        name: "Critique",
        purpose: "Review the plan",
        parallelism: "parallel",
        target_agents: ["a", "a", "b"],
        exit_criteria: ["done"],
        notes: "  note  ",
      },
    ]),
    [
      {
        wave_id: "critique",
        name: "Critique",
        purpose: "Review the plan",
        parallelism: "parallel",
        target_agents: ["a", "b"],
        exit_criteria: ["done"],
        notes: "note",
      },
    ]
  )
})

test("propose, comment, review, and revise flows preserve immutable plan versions", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "opencode-plan-"))

  try {
    const planId = createPlanId({ title: "Sample plan", revision: 1 })
    const planRecord = buildPlanRecord({
      repoRoot,
      planId,
      revision: 1,
      title: "Sample plan",
      objective: "Test OpenCode-native plan artifacts.",
      summary: "First revision.",
      assumptions: ["OpenCode tools are local"],
      constraints: ["No relay dependency"],
      executionWaves: [
        {
          wave_id: "learning",
          name: "Learning",
          purpose: "Map the state",
          parallelism: "parallel",
          target_agents: ["plan", "explore"],
          exit_criteria: ["state mapped"],
          notes: "",
        },
      ],
      acceptanceCriteria: ["Plan written"],
      risks: [],
      openQuestions: [],
      revisionNotes: [],
      parentPlanId: null,
      parentPlanPath: null,
    })

    const { filePath } = writePlanRecord(repoRoot, planRecord)
    const loaded = loadPlanRecord(repoRoot, planRecord.plan_id)
    assert.equal(loaded.filePath, filePath)
    assert.equal(loaded.planRecord.plan_id, planRecord.plan_id)
    assert.equal(
      loaded.planRecord.comment_ledger_path,
      toRepoRelative(repoRoot, commentLedgerPath(repoRoot, planRecord.plan_id))
    )

    const commentRecord = buildCommentRecord({
      repoRoot,
      planRecord,
      criticName: "constructive-critic",
      waveId: "critique",
      severity: "major",
      category: "feasibility",
      comment: "Need an explicit review step.",
      suggestedChange: "Insert review_criticism before revise_plan.",
      references: ["docs/governance/reviewer-orchestrator.md"],
    })
    const ledgerPath = appendCommentRecord(repoRoot, planRecord, commentRecord)
    assert.match(readFileSync(ledgerPath, "utf8"), /"critic_name":"constructive-critic"/)

    const review = reviewCriticism(repoRoot, planRecord.plan_id)
    assert.equal(review.plan.plan_id, planRecord.plan_id)
    assert.equal(review.comment_count, 1)
    assert.equal(review.blocking_comment_count, 0)
    assert.equal(review.comments[0].critic_name, "constructive-critic")

    const revisedId = createPlanId({ title: "Sample plan revised", revision: 2 })
    const revised = buildPlanRecord({
      repoRoot,
      planId: revisedId,
      revision: 2,
      title: "Sample plan revised",
      objective: "Test OpenCode-native plan artifacts.",
      summary: "Second revision.",
      assumptions: ["OpenCode tools are local"],
      constraints: ["No relay dependency"],
      executionWaves: planRecord.execution_waves,
      acceptanceCriteria: ["Plan written", "Criticism reviewed"],
      risks: [],
      openQuestions: [],
      revisionNotes: ["Addressed critic feedback"],
      parentPlanId: planRecord.plan_id,
      parentPlanPath: filePath,
    })
    writePlanRecord(repoRoot, revised)
    const revisedLoaded = loadPlanRecord(repoRoot, revised.plan_id)
    assert.equal(revisedLoaded.planRecord.parent_plan_id, planRecord.plan_id)
    assert.equal(revisedLoaded.planRecord.parent_plan_path, toRepoRelative(repoRoot, filePath))
    assert.equal(revisedLoaded.planRecord.revision, 2)
  } finally {
    rmSync(repoRoot, { recursive: true, force: true })
  }
})

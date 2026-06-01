import test from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  buildPlanRecord,
  writePlanRecord,
} from "../.opencode/tools/opencode_plan_core.mjs"
import {
  buildPublishedCheckpointReport,
  findPublicationArtifactByReceipt,
  pushCheckpoint,
} from "../.opencode/tools/opencode_checkpoint_publication_core.mjs"
import {
  commitCheckpoint,
  fileDigest,
  prepareCheckpoint,
} from "../.opencode/tools/opencode_checkpoint_core.mjs"

test("publish_checkpoint pushes once and generate_published_checkpoint_report summarizes the lineage", () => {
  const repo = mkdtempSync(join(tmpdir(), "opencode-publish-"))
  let remote = ""
  let reviewDir = ""

  try {
    execFileSync("git", ["init"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["branch", "-M", "main"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["config", "user.name", "Test"], { cwd: repo, stdio: "pipe" })

    remote = mkdtempSync(join(tmpdir(), "opencode-remote-"))
    execFileSync("git", ["init", "--bare"], { cwd: remote, stdio: "pipe" })
    execFileSync("git", ["remote", "add", "origin", remote], { cwd: repo, stdio: "pipe" })

    writeFileSync(join(repo, "alpha.txt"), "alpha v1\n")
    execFileSync("git", ["add", "alpha.txt"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["commit", "-m", "initial"], { cwd: repo, stdio: "pipe" })

    const planId = "opencode-plan-20260528T120000Z-demo-r1-abcdef12"
    const planRecord = buildPlanRecord({
      repoRoot: repo,
      planId,
      revision: 1,
      title: "Demo plan",
      objective: "Exercise checkpoint publication.",
      summary: "Keep the publisher native to OpenCode.",
      assumptions: ["Git is available."],
      constraints: ["Do not widen the boundary."],
      executionWaves: [],
      acceptanceCriteria: ["Publisher pushes exactly once."],
      risks: [],
      openQuestions: [],
      revisionNotes: [],
    })
    writePlanRecord(repo, planRecord)
    execFileSync("git", ["add", `docs/json/opencode/plans/${planId}.json`], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["commit", "-m", "add plan"], { cwd: repo, stdio: "pipe" })

    writeFileSync(join(repo, "alpha.txt"), "alpha v2\n")
    const currentSha = fileDigest(join(repo, "alpha.txt"))

    const prep = prepareCheckpoint({
      repoRoot: repo,
      taskId: "task-1",
      executorName: "executor-a",
      checkpointSummary: "Update alpha.",
      planId,
      waveId: "execution",
      changeItems: [
        {
          path: "alpha.txt",
          change_kind: "modify",
          why: "Update alpha text.",
          current_sha256: currentSha,
        },
      ],
    })

    const commit = commitCheckpoint({
      repoRoot: repo,
      preparationReceiptSha256: prep.preparation_receipt_sha256,
    })

    const candidatePacketDigest = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    reviewDir = mkdtempSync(join(tmpdir(), "opencode-review-"))
    const reviewPath = join(reviewDir, "review.json")
    writeFileSync(
      reviewPath,
      `${JSON.stringify(
        {
          schema_version: "opencode.prepublication_review.v1",
          artifact_id: "opencode-review-1",
          created_at: "2026-05-28T12:00:00Z",
          checkpoint_commit_receipt_sha256: commit.checkpoint_receipt_sha256,
          candidate_packet_digest: candidatePacketDigest,
          disposition: "prepublication_admitted",
          reviewer_name: "reviewer-a",
          review_notes: ["Admitted for publication."],
          content_light: true,
        },
        null,
        2,
      )}\n`,
    )

    const publication = pushCheckpoint(repo, {
      checkpoint_commit_receipt_sha256: commit.checkpoint_receipt_sha256,
      candidate_packet_digest: candidatePacketDigest,
      admitted_review_artifact_path: reviewPath,
      admitted_review_artifact_sha256: fileDigest(reviewPath),
      publisher_name: "publisher-a",
      remote_name: "origin",
      target_ref: "main",
      publication_notes: ["Published the admitted checkpoint."],
      files_published: ["alpha.txt"],
      post_push_checks: ["remote SHA matched HEAD"],
    })

    assert.equal(publication.artifact.remote_verified, true)
    assert.equal(publication.artifact.candidate_packet_digest, candidatePacketDigest)
    assert.equal(
      execFileSync("git", ["ls-remote", "origin", "main"], { cwd: repo, encoding: "utf8" }).trim().split(/\s+/)[0],
      publication.artifact.pushed_commit_sha,
    )

    const publicationEntry = findPublicationArtifactByReceipt(repo, publication.publication_receipt_sha256)
    assert.ok(publicationEntry)

    const report = buildPublishedCheckpointReport({
      repoRoot: repo,
      publicationArtifactEntry: publicationEntry,
      reportSummary: "Publication summary for the admitted checkpoint.",
      nextSteps: ["Continue with the next wave."],
      blockedSeams: [],
    })

    assert.equal(report.artifact.plan_id, planId)
    assert.equal(report.artifact.candidate_packet_digest, candidatePacketDigest)
    assert.equal(report.artifact.published_commit_sha, commit.artifact.commit_sha)
    assert.equal(report.artifact.checkpoint_sequence, 1)
    assert.equal(report.artifact.plan_comment_count, 0)
    assert.equal(report.artifact.checkpoint_commit_lineage.length, 1)
    assert.equal(report.artifact.checkpoint_preparation_lineage.length, 1)
    assert.equal(report.artifact.publication_artifacts.length, 1)
    assert.equal(report.artifact.report_summary, "Publication summary for the admitted checkpoint.")
  } finally {
    rmSync(repo, { recursive: true, force: true })
    if (typeof remote === "string" && remote.length) {
      try {
        rmSync(remote, { recursive: true, force: true })
      } catch {
        // ignore cleanup failures in test teardown
      }
    }
    if (reviewDir) {
      try {
        rmSync(reviewDir, { recursive: true, force: true })
      } catch {
        // ignore cleanup failures in test teardown
      }
    }
  }
})

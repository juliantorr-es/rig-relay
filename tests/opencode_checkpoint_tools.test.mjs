import test from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  commitCheckpoint,
  fileDigest,
  prepareCheckpoint,
} from "../.opencode/tools/opencode_checkpoint_core.mjs"

test("prepare_checkpoint stages the requested slice and checkpoint commits it", () => {
  const repo = mkdtempSync(join(tmpdir(), "opencode-checkpoint-"))

  try {
    execFileSync("git", ["init"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["branch", "-M", "main"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["config", "user.name", "Test"], { cwd: repo, stdio: "pipe" })

    writeFileSync(join(repo, "alpha.txt"), "alpha v1\n")
    execFileSync("git", ["add", "alpha.txt"], { cwd: repo, stdio: "pipe" })
    execFileSync("git", ["commit", "-m", "initial"], { cwd: repo, stdio: "pipe" })

    writeFileSync(join(repo, "alpha.txt"), "alpha v2\n")
    const currentSha = fileDigest(join(repo, "alpha.txt"))

    const prep = prepareCheckpoint({
      repoRoot: repo,
      taskId: "task-1",
      executorName: "executor-a",
      checkpointSummary: "Update alpha.",
      planId: "plan-1",
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

    assert.match(prep.preparation_receipt_sha256, /^sha256:/)
    assert.equal(prep.artifact.staged_paths[0], "alpha.txt")
    assert.match(
      execFileSync("git", ["diff", "--cached", "--name-only"], { cwd: repo, encoding: "utf8" }),
      /alpha\.txt/
    )
    assert.match(prep.filePath, /docs\/json\/opencode\/checkpoints\/preparations\/.*\.json$/)

    const commit = commitCheckpoint({
      repoRoot: repo,
      preparationReceiptSha256: prep.preparation_receipt_sha256,
    })

    assert.match(commit.checkpoint_receipt_sha256, /^sha256:/)
    assert.match(commit.filePath, /docs\/json\/opencode\/checkpoints\/commits\/.*\.json$/)
    assert.equal(commit.artifact.commit_sha, execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim())
    assert.equal(commit.artifact.files_committed[0], "alpha.txt")
    assert.equal(readFileSync(join(repo, "alpha.txt"), "utf8"), "alpha v2\n")
    assert.equal(
      execFileSync("git", ["log", "--format=%s", "-1"], { cwd: repo, encoding: "utf8" }).trim(),
      "checkpoint(task-1): Update alpha."
    )
  } finally {
    rmSync(repo, { recursive: true, force: true })
  }
})

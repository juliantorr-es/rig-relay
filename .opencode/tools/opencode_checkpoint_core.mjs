import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { createHash, randomUUID } from "node:crypto"
import { spawnSync } from "node:child_process"
import { join, relative, resolve } from "node:path"

export const CHECKPOINT_PREPARATION_SCHEMA_VERSION = "opencode.checkpoint_preparation.v1"
export const CHECKPOINT_SCHEMA_VERSION = "opencode.checkpoint_commit.v1"

export function resolveRepoRoot(worktree) {
  return resolve(worktree || process.cwd())
}

export function checkpointRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode", "checkpoints")
}

export function preparationRoot(repoRoot) {
  return join(checkpointRoot(repoRoot), "preparations")
}

export function commitRoot(repoRoot) {
  return join(checkpointRoot(repoRoot), "commits")
}

export function ensureCheckpointDirs(repoRoot) {
  mkdirSync(preparationRoot(repoRoot), { recursive: true })
  mkdirSync(commitRoot(repoRoot), { recursive: true })
}

export function repoRelative(repoRoot, filePath) {
  return relative(repoRoot, filePath).split("\\").join("/")
}

export function normalizeList(values) {
  return [...new Set((values || []).map((value) => String(value).trim()).filter(Boolean))]
}

export function stableDigest(payload) {
  return `sha256:${createHash("sha256").update(payload, "utf8").digest("hex")}`
}

export function fileDigest(filePath) {
  return stableDigest(readFileSync(filePath, "utf8"))
}

export function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf8"))
}

export function writeJson(filePath, payload) {
  mkdirSync(join(filePath, ".."), { recursive: true })
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8")
}

export function createRecordId(prefix) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")
  return `${prefix}-${stamp}-${randomUUID().slice(0, 8)}`
}

export function isInsideRepo(repoRoot, filePath) {
  const absolute = resolve(repoRoot, filePath)
  const rel = relative(repoRoot, absolute)
  return rel && !rel.startsWith("..") && !absolute.includes("\u0000")
}

export function gitResult(repoRoot, args) {
  const result = spawnSync("git", args, { cwd: repoRoot, encoding: "utf8" })
  if (result.error) {
    throw result.error
  }
  if (result.status !== 0) {
    const detail = [result.stdout, result.stderr].filter(Boolean).join("\n").trim()
    throw new Error(`git ${args.join(" ")} failed${detail ? `: ${detail}` : ""}`)
  }
  return {
    stdout: String(result.stdout ?? "").trim(),
    stderr: String(result.stderr ?? "").trim(),
  }
}

export function gitHead(repoRoot) {
  return gitResult(repoRoot, ["rev-parse", "HEAD"]).stdout
}

export function gitBranch(repoRoot) {
  return gitResult(repoRoot, ["branch", "--show-current"]).stdout
}

export function gitStatusPorcelain(repoRoot) {
  const output = gitResult(repoRoot, ["status", "--porcelain=v1", "-uall"]).stdout
  return output
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean)
}

export function gitStagedNames(repoRoot) {
  const output = gitResult(repoRoot, ["diff", "--cached", "--name-only"]).stdout
  return normalizeList(output.split(/\r?\n/))
}

export function gitAddPaths(repoRoot, paths) {
  if (!paths.length) {
    return
  }
  gitResult(repoRoot, ["add", "--", ...paths])
}

export function gitCommit(repoRoot, message) {
  const [subject, ...bodyParts] = String(message ?? "").split(/\r?\n/)
  const args = ["commit", "-m", subject || "checkpoint"]
  const body = bodyParts.join("\n").trim()
  if (body) {
    args.push("-m", body)
  }
  gitResult(repoRoot, args)
}

export function gitCommitHead(repoRoot) {
  return gitResult(repoRoot, ["rev-parse", "HEAD"]).stdout
}

export function parseStatusLine(line) {
  return {
    status: line.slice(0, 2),
    path: line.slice(3).split(" -> ").at(-1)?.trim() || "",
    raw: line,
  }
}

export function normalizeChangeItems(changeItems) {
  return (changeItems || []).map((item, index) => {
    const path = String(item.path ?? item.repository_path ?? `file-${index + 1}`).trim()
    return {
      path,
      change_kind: String(item.change_kind ?? item.kind ?? "modify").trim() || "modify",
      why: String(item.why ?? item.reason ?? "").trim(),
      current_sha256: String(item.current_sha256 ?? item.sha256 ?? "").trim(),
    }
  })
}

export function checkpointPreparationPath(repoRoot, artifactId) {
  return join(preparationRoot(repoRoot), `${artifactId}.json`)
}

export function checkpointCommitPath(repoRoot, artifactId) {
  return join(commitRoot(repoRoot), `${artifactId}.json`)
}

export function writePreparationArtifact(repoRoot, artifact) {
  ensureCheckpointDirs(repoRoot)
  const filePath = checkpointPreparationPath(repoRoot, artifact.artifact_id)
  writeJson(filePath, artifact)
  return filePath
}

export function writeCheckpointArtifact(repoRoot, artifact) {
  ensureCheckpointDirs(repoRoot)
  const filePath = checkpointCommitPath(repoRoot, artifact.artifact_id)
  writeJson(filePath, artifact)
  return filePath
}

export function collectCheckpointArtifacts(repoRoot, kind, planId, branch) {
  const root = kind === "commits" ? commitRoot(repoRoot) : preparationRoot(repoRoot)
  if (!existsSync(root)) {
    return []
  }
  const results = []
  const stack = [root]
  while (stack.length) {
    const current = stack.pop()
    if (!current) continue
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const entryPath = join(current, entry.name)
      if (entry.isDirectory()) {
        stack.push(entryPath)
      } else if (entry.isFile() && entry.name.endsWith(".json")) {
        const artifact = readJson(entryPath)
        if (planId && String(artifact.plan_id ?? "").trim() !== String(planId).trim()) {
          continue
        }
        if (branch && String(artifact.branch ?? "").trim() !== String(branch).trim()) {
          continue
        }
        results.push({
          path: repoRelative(repoRoot, entryPath),
          digest: fileDigest(entryPath),
          artifact,
        })
      }
    }
  }
  return results.sort((left, right) => left.path.localeCompare(right.path))
}

export function buildPreparationArtifact({
  repoRoot,
  taskId,
  executorName,
  checkpointSummary,
  planId,
  waveId,
  changeItems,
  headBefore,
  branch,
  statusBefore,
  statusAfter,
  stagedPaths,
  excludedDirtyFiles,
}) {
  const artifactId = createRecordId("opencode-checkpoint-prep")
  const filePath = checkpointPreparationPath(repoRoot, artifactId)
  const normalizedChanges = normalizeChangeItems(changeItems)
  const artifact = {
    schema_version: CHECKPOINT_PREPARATION_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    task_id: String(taskId ?? "").trim(),
    executor_name: String(executorName ?? "").trim(),
    checkpoint_summary: String(checkpointSummary ?? "").trim(),
    plan_id: planId ? String(planId).trim() : null,
    wave_id: waveId ? String(waveId).trim() : null,
    branch: String(branch ?? "").trim(),
    pre_commit_head: String(headBefore ?? "").trim(),
    change_items: normalizedChanges.map((item) => ({
      path: item.path,
      change_kind: item.change_kind,
      why: item.why,
      current_sha256: item.current_sha256 || null,
    })),
    staged_paths: normalizeList(stagedPaths),
    excluded_dirty_files: normalizeList(excludedDirtyFiles),
    git_status_before: normalizeList(statusBefore),
    git_status_after: normalizeList(statusAfter),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function buildCheckpointArtifact({
  repoRoot,
  preparationArtifact,
  preparationArtifactPath,
  preparationReceiptSha256,
  commitSha,
  headBefore,
  headAfter,
  branch,
  checkpointSequence,
  parentCheckpointReceiptSha256,
  filesCommitted,
}) {
  const artifactId = createRecordId("opencode-checkpoint")
  const filePath = checkpointCommitPath(repoRoot, artifactId)
  const artifact = {
    schema_version: CHECKPOINT_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    task_id: String(preparationArtifact.task_id ?? "").trim(),
    executor_name: String(preparationArtifact.executor_name ?? "").trim(),
    checkpoint_summary: String(preparationArtifact.checkpoint_summary ?? "").trim(),
    plan_id: preparationArtifact.plan_id ?? null,
    wave_id: preparationArtifact.wave_id ?? null,
    branch: String(branch ?? "").trim(),
    checkpoint_sequence: Number(checkpointSequence ?? 1),
    parent_checkpoint_receipt_sha256: parentCheckpointReceiptSha256 || null,
    pre_commit_head: String(headBefore ?? "").trim(),
    post_commit_head: String(headAfter ?? "").trim(),
    commit_sha: String(commitSha ?? "").trim(),
    preparation_receipt_sha256: String(preparationReceiptSha256 ?? "").trim(),
    preparation_artifact_path: preparationArtifactPath,
    files_committed: normalizeList(filesCommitted),
    change_items: normalizeChangeItems(preparationArtifact.change_items).map((item) => ({
      path: item.path,
      change_kind: item.change_kind,
      why: item.why,
      current_sha256: item.current_sha256 || null,
    })),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function computeFileSha256(filePath) {
  return stableDigest(readFileSync(filePath, "utf8"))
}

export function collectWritablePaths(changeItems) {
  return normalizeList(changeItems.map((item) => item.path))
}

export function findPreparationArtifactByReceipt(repoRoot, receiptSha256) {
  return collectCheckpointArtifacts(repoRoot, "preparations").find(
    (entry) => entry.digest === receiptSha256,
  )
}

export function prepareCheckpoint({
  repoRoot,
  taskId,
  executorName,
  checkpointSummary,
  planId,
  waveId,
  changeItems,
}) {
  ensureCheckpointDirs(repoRoot)
  const normalizedChanges = normalizeChangeItems(changeItems)
  if (!normalizedChanges.length) {
    throw new Error("prepare_checkpoint requires at least one change item")
  }

  const headBefore = gitHead(repoRoot)
  const branch = gitBranch(repoRoot)
  const statusBefore = gitStatusPorcelain(repoRoot)
  const stagedBefore = gitStagedNames(repoRoot)
  const requestedPaths = normalizedChanges.map((item) => item.path)
  const stagedOutsideRequest = stagedBefore.filter((path) => !requestedPaths.includes(path))
  if (stagedOutsideRequest.length) {
    throw new Error(
      `Refusing to prepare checkpoint with pre-existing staged files: ${stagedOutsideRequest.join(", ")}`,
    )
  }

  const excludedDirtyFiles = statusBefore
    .map((line) => parseStatusLine(line).path)
    .filter((path) => path && !requestedPaths.includes(path))

  for (const item of normalizedChanges) {
    if (!item.path) {
      throw new Error("Checkpoint change items require a repository-relative path")
    }
    const absolute = join(repoRoot, item.path)
    if (!existsSync(absolute)) {
      if (item.change_kind !== "delete") {
        throw new Error(`Checkpoint path does not exist: ${item.path}`)
      }
      continue
    }
    if (item.current_sha256) {
      const candidate = computeFileSha256(absolute)
      if (candidate !== item.current_sha256) {
        throw new Error(`SHA256 mismatch for ${item.path}`)
      }
    }
  }

  gitAddPaths(repoRoot, requestedPaths)
  const statusAfter = gitStatusPorcelain(repoRoot)
  const { filePath, artifact } = buildPreparationArtifact({
    repoRoot,
    taskId,
    executorName,
    checkpointSummary,
    planId,
    waveId,
    changeItems: normalizedChanges,
    headBefore,
    branch,
    statusBefore,
    statusAfter,
    stagedPaths: requestedPaths,
    excludedDirtyFiles,
  })

  return {
    filePath,
    artifact,
    preparation_receipt_sha256: computeFileSha256(filePath),
  }
}

export function commitCheckpoint({ repoRoot, preparationReceiptSha256 }) {
  ensureCheckpointDirs(repoRoot)
  const preparationEntry = findPreparationArtifactByReceipt(repoRoot, preparationReceiptSha256)
  if (!preparationEntry) {
    throw new Error(`No checkpoint preparation artifact matches receipt ${preparationReceiptSha256}`)
  }

  const preparationArtifact = preparationEntry.artifact
  const stagedPaths = gitStagedNames(repoRoot).sort((left, right) => left.localeCompare(right))
  const expectedPaths = normalizeList(preparationArtifact.staged_paths || []).sort((left, right) =>
    left.localeCompare(right),
  )
  if (stagedPaths.join("\n") !== expectedPaths.join("\n")) {
    throw new Error(
      `Staged paths no longer match the preparation receipt for ${preparationArtifact.artifact_id}`,
    )
  }

  const headBefore = gitHead(repoRoot)
  const branch = gitBranch(repoRoot)
  const priorCommits = collectCheckpointArtifacts(repoRoot, "commits", preparationArtifact.plan_id, branch)
  const priorCheckpoint = priorCommits.at(-1)
  const commitSubject = `checkpoint(${preparationArtifact.task_id || "task"}): ${preparationArtifact.checkpoint_summary}`
  const commitBody = [
    `Executor: ${preparationArtifact.executor_name || "unknown"}`,
    `Preparation receipt: ${preparationReceiptSha256}`,
    `Task: ${preparationArtifact.task_id || "unknown"}`,
    `Plan: ${preparationArtifact.plan_id || "none"}`,
    `Wave: ${preparationArtifact.wave_id || "none"}`,
    "Files:",
    ...normalizeList(
      (preparationArtifact.change_items || []).map(
        (item) => `${item.path} :: ${item.change_kind} :: ${item.why || "no reason recorded"}`,
      ),
    ),
  ].join("\n")

  gitCommit(repoRoot, `${commitSubject}\n\n${commitBody}`)
  const headAfter = gitCommitHead(repoRoot)
  const filesCommitted = gitResult(repoRoot, ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"]).stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  const commitArtifact = buildCheckpointArtifact({
    repoRoot,
    preparationArtifact,
    preparationArtifactPath: preparationEntry.path,
    preparationReceiptSha256,
    commitSha: headAfter,
    headBefore,
    headAfter,
    branch,
    checkpointSequence: priorCommits.length + 1,
    parentCheckpointReceiptSha256: priorCheckpoint ? priorCheckpoint.digest : null,
    filesCommitted,
  })

  return {
    filePath: commitArtifact.filePath,
    artifact: commitArtifact.artifact,
    checkpoint_receipt_sha256: computeFileSha256(commitArtifact.filePath),
  }
}

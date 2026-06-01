import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { spawnSync } from "node:child_process"
import { join } from "node:path"

import {
  collectCheckpointArtifacts,
  computeFileSha256,
  createRecordId,
  fileDigest,
  gitHead,
  gitStatusPorcelain,
  normalizeList,
  parseStatusLine,
  readJson,
  resolveRepoRoot,
  repoRelative,
  stableDigest,
  writeJson,
} from "./opencode_checkpoint_core.mjs"
import {
  collectPlanArtifacts,
  readPlan,
  planRoot,
  readJsonl as readPlanJsonl,
  normalizeObjectList,
  wavesRoot,
} from "./opencode_wave_core.mjs"
import {
  coordinationMessagesPath,
  readJsonl as readCoordinationJsonl,
} from "./opencode_coordination_core.mjs"

export const CHECKPOINT_PUBLICATION_SCHEMA_VERSION = "opencode.checkpoint_publication.v1"
export const PUBLISHED_CHECKPOINT_REPORT_SCHEMA_VERSION = "opencode.published_checkpoint_report.v1"

export function checkpointPublicationRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode", "checkpoint_publications")
}

export function publishedCheckpointReportRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode", "published_checkpoint_reports")
}

export function ensurePublicationDirs(repoRoot) {
  mkdirSync(checkpointPublicationRoot(repoRoot), { recursive: true })
  mkdirSync(publishedCheckpointReportRoot(repoRoot), { recursive: true })
}

export function publicationArtifactPath(repoRoot, artifactId) {
  return join(checkpointPublicationRoot(repoRoot), `${artifactId}.json`)
}

export function publishedReportPath(repoRoot, artifactId) {
  return join(publishedCheckpointReportRoot(repoRoot), `${artifactId}.json`)
}

export function collectPublicationArtifacts(repoRoot) {
  const root = checkpointPublicationRoot(repoRoot)
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

export function findPublicationArtifactByReceipt(repoRoot, receiptSha256) {
  return collectPublicationArtifacts(repoRoot).find((entry) => entry.digest === receiptSha256)
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

export function gitLsRemote(repoRoot, remoteName, refName) {
  return gitResult(repoRoot, ["ls-remote", remoteName, refName]).stdout
}

export function pushCheckpoint(repoRoot, args) {
  ensurePublicationDirs(repoRoot)
  const reviewArtifact = readJson(args.admitted_review_artifact_path)
  const reviewDigest = computeFileSha256(args.admitted_review_artifact_path)
  if (reviewDigest !== args.admitted_review_artifact_sha256) {
    throw new Error("Admitted review artifact digest mismatch")
  }
  if (String(reviewArtifact.disposition ?? "").trim() !== "prepublication_admitted") {
    throw new Error(`Review disposition is not admitted: ${reviewArtifact.disposition ?? "missing"}`)
  }
  if (String(reviewArtifact.checkpoint_commit_receipt_sha256 ?? "").trim() !== String(args.checkpoint_commit_receipt_sha256).trim()) {
    throw new Error("Review artifact does not bind to the requested checkpoint receipt")
  }
  if (String(reviewArtifact.candidate_packet_digest ?? "").trim() !== String(args.candidate_packet_digest ?? "").trim()) {
    throw new Error("Review artifact candidate packet digest does not match the admitted packet")
  }

  const checkpointEntry = collectCheckpointArtifacts(repoRoot, "commits").find(
    (entry) => entry.digest === args.checkpoint_commit_receipt_sha256,
  )
  if (!checkpointEntry) {
    throw new Error(`No checkpoint commit artifact matches receipt ${args.checkpoint_commit_receipt_sha256}`)
  }

  const checkpointArtifact = checkpointEntry.artifact
  const headBefore = gitHead(repoRoot)
  if (headBefore !== String(checkpointArtifact.commit_sha ?? "").trim()) {
    throw new Error("Current HEAD does not match the admitted checkpoint commit")
  }
  const dirtyFiles = gitStatusPorcelain(repoRoot)
    .map(parseStatusLine)
    .map((entry) => String(entry.path ?? "").trim())
    .filter(Boolean)
  const allowedDirtyFiles = new Set(
    [
      checkpointEntry.path,
      checkpointArtifact.preparation_artifact_path,
    ]
      .map((value) => String(value ?? "").trim())
      .filter(Boolean),
  )
  const unexpectedDirtyFiles = dirtyFiles.filter((path) => !allowedDirtyFiles.has(path))
  if (unexpectedDirtyFiles.length) {
    throw new Error(`Working tree is dirty; refusing to publish checkpoint: ${unexpectedDirtyFiles.join(", ")}`)
  }

  const refName = String(args.target_ref ?? "").trim()
  const remoteName = String(args.remote_name ?? "origin").trim() || "origin"
  const pushRef = refName.startsWith("refs/") ? refName : `refs/heads/${refName}`
  gitResult(repoRoot, ["push", remoteName, `HEAD:${pushRef}`])

  const remoteLine = gitLsRemote(repoRoot, remoteName, refName)
  const remoteSha = remoteLine.split(/\s+/)[0]?.trim() || ""
  const postPushHead = gitHead(repoRoot)
  if (remoteSha !== postPushHead) {
    throw new Error(`Remote SHA mismatch after push: expected ${postPushHead}, got ${remoteSha || "missing"}`)
  }

  const publicationArtifactId = createRecordId("opencode-checkpoint-publication")
  const filePath = publicationArtifactPath(repoRoot, publicationArtifactId)
  const artifact = {
    schema_version: CHECKPOINT_PUBLICATION_SCHEMA_VERSION,
    artifact_id: publicationArtifactId,
    created_at: new Date().toISOString(),
    publisher_name: String(args.publisher_name ?? "").trim(),
    remote_name: remoteName,
    target_ref: refName,
    plan_id: String(checkpointArtifact.plan_id ?? "").trim(),
    plan_revision: Number(checkpointArtifact.plan_revision ?? 1),
    checkpoint_commit_receipt_sha256: String(args.checkpoint_commit_receipt_sha256).trim(),
    checkpoint_commit_artifact_path: checkpointEntry.path,
    checkpoint_commit_sha: String(checkpointArtifact.commit_sha ?? "").trim(),
    checkpoint_sequence: Number(checkpointArtifact.checkpoint_sequence ?? 1),
    parent_checkpoint_receipt_sha256: checkpointArtifact.parent_checkpoint_receipt_sha256 ?? null,
    candidate_packet_digest: String(args.candidate_packet_digest ?? "").trim(),
    review_artifact_path: repoRelative(repoRoot, args.admitted_review_artifact_path),
    review_artifact_sha256: String(args.admitted_review_artifact_sha256).trim(),
    admitted_review_status: String(reviewArtifact.disposition ?? "").trim(),
    pre_push_head: headBefore,
    post_push_head: postPushHead,
    pushed_commit_sha: remoteSha,
    remote_verified: true,
    publication_notes: normalizeList(args.publication_notes),
    files_published: normalizeList(args.files_published.length ? args.files_published : checkpointArtifact.files_committed),
    post_push_checks: normalizeList(args.post_push_checks.length ? args.post_push_checks : [
      "git push completed",
      "remote SHA matched HEAD",
      "working tree clean before push",
    ]),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return {
    filePath,
    artifact,
    publication_receipt_sha256: computeFileSha256(filePath),
  }
}

function summarizeArtifactRef(entry) {
  return {
    artifact_id: String(entry.artifact.artifact_id ?? "").trim(),
    path: entry.path,
    digest: entry.digest,
  }
}

function selectCoordinationMessages(repoRoot, planId, publicationArtifact, checkpointArtifact) {
  const messages = readCoordinationJsonl(coordinationMessagesPath(repoRoot))
  const interestingTokens = new Set(
    [
      planId,
      publicationArtifact.artifact_id,
      publicationArtifact.checkpoint_commit_receipt_sha256,
      publicationArtifact.pushed_commit_sha,
      publicationArtifact.candidate_packet_digest,
      checkpointArtifact.artifact_id,
      checkpointArtifact.checkpoint_commit_receipt_sha256,
      checkpointArtifact.commit_sha,
      publicationArtifact.review_artifact_sha256,
      publicationArtifact.review_artifact_path,
      publicationArtifact.checkpoint_commit_artifact_path,
    ]
      .map((value) => String(value ?? "").trim())
      .filter(Boolean),
  )
  return messages.filter((message) =>
    (Array.isArray(message.artifact_refs) ? message.artifact_refs : []).some((ref) =>
      interestingTokens.has(String(ref.artifact_id ?? "").trim()) ||
      interestingTokens.has(String(ref.digest ?? "").trim()) ||
      interestingTokens.has(String(ref.path ?? "").trim()),
    ),
  )
}

export function buildPublishedCheckpointReport({
  repoRoot,
  publicationArtifactEntry,
  reportSummary,
  nextSteps,
  blockedSeams,
}) {
  const publicationArtifact = publicationArtifactEntry.artifact
  const checkpointEntry = collectCheckpointArtifacts(
    repoRoot,
    "commits",
    publicationArtifact.plan_id,
    undefined,
  ).find((entry) => entry.digest === publicationArtifact.checkpoint_commit_receipt_sha256)
  if (!checkpointEntry) {
    throw new Error(`Checkpoint commit artifact not found for receipt ${publicationArtifact.checkpoint_commit_receipt_sha256}`)
  }
  const checkpointArtifact = checkpointEntry.artifact
  const plan = readPlan(repoRoot, publicationArtifact.plan_id)
  const planArtifact = plan.plan
  const executionArtifacts = collectPlanArtifacts(repoRoot, publicationArtifact.plan_id, "/execution/")
  const validationArtifacts = collectPlanArtifacts(repoRoot, publicationArtifact.plan_id, "/validation/")
  const stressArtifacts = collectPlanArtifacts(repoRoot, publicationArtifact.plan_id, "/stress/")
  const publicationArtifacts = collectPublicationArtifacts(repoRoot)
    .filter((entry) => String(entry.artifact.plan_id ?? "").trim() === String(publicationArtifact.plan_id ?? "").trim())
    .filter((entry) => Number(entry.artifact.checkpoint_sequence ?? 0) <= Number(publicationArtifact.checkpoint_sequence ?? 0))
  const checkpointCommitArtifacts = collectCheckpointArtifacts(repoRoot, "commits", publicationArtifact.plan_id, checkpointArtifact.branch)
    .filter((entry) => Number(entry.artifact.checkpoint_sequence ?? 0) <= Number(publicationArtifact.checkpoint_sequence ?? 0))
    .sort((left, right) => Number(left.artifact.checkpoint_sequence ?? 0) - Number(right.artifact.checkpoint_sequence ?? 0))
  const checkpointPreparationArtifacts = collectCheckpointArtifacts(repoRoot, "preparations", publicationArtifact.plan_id, checkpointArtifact.branch)
    .sort((left, right) => String(left.artifact.created_at ?? "").localeCompare(String(right.artifact.created_at ?? "")))
  const planComments = readPlanJsonl(join(planRoot(repoRoot), `${publicationArtifact.plan_id}.comments.jsonl`))
  const coordinationMessages = selectCoordinationMessages(repoRoot, publicationArtifact.plan_id, publicationArtifact, checkpointArtifact)
  const reportArtifactId = createRecordId("opencode-published-checkpoint-report")
  const filePath = publishedReportPath(repoRoot, reportArtifactId)
  const artifact = {
    schema_version: PUBLISHED_CHECKPOINT_REPORT_SCHEMA_VERSION,
    artifact_id: reportArtifactId,
    created_at: new Date().toISOString(),
    publisher_name: publicationArtifact.publisher_name,
    remote_name: publicationArtifact.remote_name,
    target_ref: publicationArtifact.target_ref,
    plan_id: publicationArtifact.plan_id,
    plan_revision: publicationArtifact.plan_revision,
    plan_path: repoRelative(repoRoot, plan.filePath),
    plan_digest: stableDigest(`${JSON.stringify(planArtifact, null, 2)}\n`),
    publication_artifact_path: repoRelative(repoRoot, publicationArtifactEntry.path),
    publication_artifact_sha256: publicationArtifactEntry.digest,
    candidate_packet_digest: publicationArtifact.candidate_packet_digest,
    checkpoint_commit_artifact_path: publicationArtifact.checkpoint_commit_artifact_path,
    checkpoint_commit_sha: publicationArtifact.checkpoint_commit_sha,
    checkpoint_commit_receipt_sha256: publicationArtifact.checkpoint_commit_receipt_sha256,
    checkpoint_sequence: publicationArtifact.checkpoint_sequence,
    parent_checkpoint_receipt_sha256: publicationArtifact.parent_checkpoint_receipt_sha256,
    published_commit_sha: publicationArtifact.pushed_commit_sha,
    review_artifact_path: publicationArtifact.review_artifact_path,
    review_artifact_sha256: publicationArtifact.review_artifact_sha256,
    admitted_review_status: publicationArtifact.admitted_review_status,
    checkpoint_commit_lineage: checkpointCommitArtifacts.map(summarizeArtifactRef),
    checkpoint_preparation_lineage: checkpointPreparationArtifacts.map(summarizeArtifactRef),
    execution_artifacts: executionArtifacts.map(summarizeArtifactRef),
    validation_artifacts: validationArtifacts.map(summarizeArtifactRef),
    stress_artifacts: stressArtifacts.map(summarizeArtifactRef),
    publication_artifacts: publicationArtifacts.map(summarizeArtifactRef),
    plan_comment_count: planComments.length,
    plan_comment_summaries: normalizeObjectList(planComments, (comment) => ({
      comment_id: String(comment.comment_id ?? "").trim(),
      critic_name: String(comment.critic_name ?? "").trim(),
      severity: String(comment.severity ?? "").trim(),
      category: String(comment.category ?? "").trim(),
      wave_id: comment.wave_id ? String(comment.wave_id).trim() : null,
      comment: String(comment.comment ?? "").trim(),
      suggested_change: String(comment.suggested_change ?? "").trim(),
      references: normalizeList(comment.references),
    })),
    coordination_messages: coordinationMessages.map((message) => ({
      message_id: String(message.message_id ?? "").trim(),
      created_at: String(message.created_at ?? "").trim(),
      sender_session_id: String(message.sender_session_id ?? "").trim(),
      sender_role: String(message.sender_role ?? "").trim(),
      recipients: normalizeList(message.recipients),
      message_kind: String(message.message_kind ?? "").trim(),
      subject: String(message.subject ?? "").trim(),
      reply_to_message_id: message.reply_to_message_id ?? null,
      wave_id: message.wave_id ?? null,
      artifact_refs: normalizeList(
        (message.artifact_refs || []).map(
          (ref) => `${String(ref.artifact_kind ?? "").trim()}:${String(ref.artifact_id ?? "").trim()}`,
        ),
      ),
    })),
    report_summary: String(reportSummary ?? "").trim(),
    next_steps: normalizeList(nextSteps),
    blocked_seams: normalizeList(blockedSeams),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact, report_receipt_sha256: computeFileSha256(filePath) }
}

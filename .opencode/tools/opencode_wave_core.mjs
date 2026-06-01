import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { createHash, randomUUID } from "node:crypto"
import { join, relative, resolve } from "node:path"

export const EXECUTION_SCHEMA_VERSION = "opencode.execution_artifact.v1"
export const VALIDATION_SCHEMA_VERSION = "opencode.validation_artifact.v1"
export const STRESS_SCHEMA_VERSION = "opencode.stress_artifact.v1"
export const PUBLICATION_SCHEMA_VERSION = "opencode.publication_artifact.v1"
export const CHECKPOINT_PREPARATION_SCHEMA_VERSION = "opencode.checkpoint_preparation.v1"
export const CHECKPOINT_SCHEMA_VERSION = "opencode.checkpoint_commit.v1"
export const SESSION_REPORT_SCHEMA_VERSION = "opencode.session_report.v1"

export function resolveRepoRoot(worktree) {
  return resolve(worktree || process.cwd())
}

export function opencodeRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode")
}

export function wavesRoot(repoRoot) {
  return join(opencodeRoot(repoRoot), "waves")
}

export function reportsRoot(repoRoot) {
  return join(opencodeRoot(repoRoot), "reports")
}

export function planRoot(repoRoot) {
  return join(opencodeRoot(repoRoot), "plans")
}

export function ensureDir(dirPath) {
  mkdirSync(dirPath, { recursive: true })
}

export function repoRelative(repoRoot, filePath) {
  return relative(repoRoot, filePath).split("\\").join("/")
}

export function normalizeList(values) {
  return [...new Set((values || []).map((value) => String(value).trim()).filter(Boolean))]
}

export function normalizeObjectList(values, mapper) {
  return (values || []).map((value, index) => mapper(value, index)).filter(Boolean)
}

export function stableDigest(payload) {
  return `sha256:${createHash("sha256").update(payload, "utf8").digest("hex")}`
}

export function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf8"))
}

export function writeJson(filePath, payload) {
  ensureDir(join(filePath, ".."))
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8")
}

export function appendJsonl(filePath, payload) {
  ensureDir(join(filePath, ".."))
  appendFileSync(filePath, `${JSON.stringify(payload)}\n`, "utf8")
}

export function createRecordId(prefix) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")
  return `${prefix}-${stamp}-${randomUUID().slice(0, 8)}`
}

export function readPlan(repoRoot, planId) {
  const filePath = join(planRoot(repoRoot), `${planId}.json`)
  if (!existsSync(filePath)) {
    throw new Error(`Plan artifact not found: ${repoRelative(repoRoot, filePath)}`)
  }
  return { filePath, plan: readJson(filePath) }
}

export function waveArtifactPath(repoRoot, planId, waveId, fileName) {
  return join(wavesRoot(repoRoot), planId, waveId, fileName)
}

export function publicationPath(repoRoot, planId, fileName) {
  return join(wavesRoot(repoRoot), planId, "publication", fileName)
}

export function sessionReportPath(repoRoot, planId, fileName) {
  return join(reportsRoot(repoRoot), planId, fileName)
}

export function buildExecutionArtifact({
  repoRoot,
  plan,
  executorName,
  waveId,
  taskSummary,
  filesChanged,
  implementationNotes,
  commandsRun,
  proofArtifacts,
  deferredSeams,
  openRisks,
  boundaryClaim,
}) {
  const artifactId = createRecordId("opencode-execution")
  const filePath = waveArtifactPath(repoRoot, plan.plan_id, waveId, `${artifactId}.json`)
  const artifact = {
    schema_version: EXECUTION_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    plan_id: plan.plan_id,
    plan_revision: plan.revision,
    plan_digest: stableDigest(`${JSON.stringify(plan, null, 2)}\n`),
    wave_id: waveId,
    executor_name: executorName,
    task_summary: String(taskSummary ?? "").trim(),
    files_changed: normalizeList(filesChanged),
    implementation_notes: normalizeList(implementationNotes),
    commands_run: normalizeList(commandsRun),
    proof_artifacts: normalizeObjectList(proofArtifacts, (value) => ({
      label: String(value.label ?? "").trim(),
      path: String(value.path ?? "").trim(),
      digest: String(value.digest ?? "").trim(),
    })),
    deferred_seams: normalizeList(deferredSeams),
    open_risks: normalizeList(openRisks),
    boundary_claim: String(boundaryClaim ?? "").trim(),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function buildValidationArtifact({
  repoRoot,
  plan,
  validatorName,
  waveId,
  commandsRun,
  pass,
  testedBoundary,
  failedSeams,
  missingEvidence,
  recommendations,
}) {
  const artifactId = createRecordId("opencode-validation")
  const filePath = waveArtifactPath(repoRoot, plan.plan_id, waveId, `${artifactId}.json`)
  const artifact = {
    schema_version: VALIDATION_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    plan_id: plan.plan_id,
    plan_revision: plan.revision,
    plan_digest: stableDigest(`${JSON.stringify(plan, null, 2)}\n`),
    wave_id: waveId,
    validator_name: validatorName,
    commands_run: normalizeList(commandsRun),
    pass: Boolean(pass),
    tested_boundary: String(testedBoundary ?? "").trim(),
    failed_seams: normalizeList(failedSeams),
    missing_evidence: normalizeList(missingEvidence),
    recommendations: normalizeList(recommendations),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function buildStressArtifact({
  repoRoot,
  plan,
  redTeamName,
  waveId,
  attacks,
  attack_surface,
  survived,
  breakages,
  repaired_seams,
  recommendations,
}) {
  const artifactId = createRecordId("opencode-stress")
  const filePath = waveArtifactPath(repoRoot, plan.plan_id, waveId, `${artifactId}.json`)
  const artifact = {
    schema_version: STRESS_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    plan_id: plan.plan_id,
    plan_revision: plan.revision,
    plan_digest: stableDigest(`${JSON.stringify(plan, null, 2)}\n`),
    wave_id: waveId,
    red_team_name: redTeamName,
    attacks: normalizeList(attacks),
    attack_surface: normalizeList(attack_surface),
    survived: Boolean(survived),
    breakages: normalizeList(breakages),
    repaired_seams: normalizeList(repaired_seams),
    recommendations: normalizeList(recommendations),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function buildPublicationArtifact({
  repoRoot,
  plan,
  publisherName,
  waveId,
  target_ref,
  pushed_sha,
  remote_verified,
  publication_notes,
  files_published,
  post_push_checks,
}) {
  const artifactId = createRecordId("opencode-publication")
  const filePath = publicationPath(repoRoot, plan.plan_id, `${artifactId}.json`)
  const artifact = {
    schema_version: PUBLICATION_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    plan_id: plan.plan_id,
    plan_revision: plan.revision,
    plan_digest: stableDigest(`${JSON.stringify(plan, null, 2)}\n`),
    wave_id: waveId,
    publisher_name: publisherName,
    target_ref: String(target_ref ?? "").trim(),
    pushed_sha: String(pushed_sha ?? "").trim(),
    remote_verified: Boolean(remote_verified),
    publication_notes: normalizeList(publication_notes),
    files_published: normalizeList(files_published),
    post_push_checks: normalizeList(post_push_checks),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function buildSessionReport({
  repoRoot,
  plan,
  executionArtifacts,
  validationArtifacts,
  stressArtifacts,
  checkpointPreparations,
  checkpointCommits,
  publicationArtifacts,
  planComments,
  reportSummary,
  next_steps,
  blocked_seams,
}) {
  const artifactId = createRecordId("opencode-session-report")
  const filePath = sessionReportPath(repoRoot, plan.plan_id, `${artifactId}.json`)
  const artifact = {
    schema_version: SESSION_REPORT_SCHEMA_VERSION,
    artifact_id: artifactId,
    created_at: new Date().toISOString(),
    plan_id: plan.plan_id,
    plan_revision: plan.revision,
    plan_digest: stableDigest(`${JSON.stringify(plan, null, 2)}\n`),
    plan_path: repoRelative(repoRoot, join(planRoot(repoRoot), `${plan.plan_id}.json`)),
    comment_ledger_path: repoRelative(repoRoot, join(planRoot(repoRoot), `${plan.plan_id}.comments.jsonl`)),
    execution_artifacts: normalizeObjectList(executionArtifacts, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
    validation_artifacts: normalizeObjectList(validationArtifacts, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
    stress_artifacts: normalizeObjectList(stressArtifacts, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
    checkpoint_preparations: normalizeObjectList(checkpointPreparations, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
    checkpoint_commits: normalizeObjectList(checkpointCommits, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
    publication_artifacts: normalizeObjectList(publicationArtifacts, (artifact) => ({
      artifact_id: String(artifact.artifact_id ?? "").trim(),
      path: String(artifact.path ?? "").trim(),
      digest: String(artifact.digest ?? "").trim(),
    })),
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
    report_summary: String(reportSummary ?? "").trim(),
    next_steps: normalizeList(next_steps),
    blocked_seams: normalizeList(blocked_seams),
    content_light: true,
  }
  writeJson(filePath, artifact)
  return { filePath, artifact }
}

export function listArtifacts(rootDir) {
  if (!existsSync(rootDir)) {
    return []
  }
  const results = []
  const stack = [rootDir]
  while (stack.length) {
    const current = stack.pop()
    if (!current) continue
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const entryPath = join(current, entry.name)
      if (entry.isDirectory()) {
        stack.push(entryPath)
      } else if (entry.isFile()) {
        results.push(entryPath)
      }
    }
  }
  return results.sort((left, right) => left.localeCompare(right))
}

export function readJsonl(filePath) {
  if (!existsSync(filePath)) {
    return []
  }
  return readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

export function fileDigest(filePath) {
  return stableDigest(readFileSync(filePath, "utf8"))
}

export function collectPlanArtifacts(repoRoot, planId, prefix) {
  const root = join(wavesRoot(repoRoot), planId)
  if (!existsSync(root)) {
    return []
  }
  return listArtifacts(root)
    .filter((path) => path.endsWith(".json") && (!prefix || path.includes(prefix)))
    .map((path) => ({
      path: repoRelative(repoRoot, path),
      digest: fileDigest(path),
      artifact: readJson(path),
    }))
}

export function summarizeArtifacts(entries) {
  return entries.map((entry) => ({
    artifact_id: String(entry.artifact.artifact_id ?? "").trim(),
    path: entry.path,
    digest: entry.digest,
  }))
}

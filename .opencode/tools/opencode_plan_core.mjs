import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { createHash, randomUUID } from "node:crypto"
import { join, relative, resolve } from "node:path"

export const PLAN_SCHEMA_VERSION = "opencode.plan.v1"
export const COMMENT_SCHEMA_VERSION = "opencode.plan_comment.v1"

export function resolveRepoRoot(worktree) {
  return resolve(worktree || process.cwd())
}

export function plansRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode", "plans")
}

export function planPath(repoRoot, planId) {
  return join(plansRoot(repoRoot), `${planId}.json`)
}

export function commentLedgerPath(repoRoot, planId) {
  return join(plansRoot(repoRoot), `${planId}.comments.jsonl`)
}

export function toRepoRelative(repoRoot, filePath) {
  return relative(repoRoot, filePath).split("\\").join("/")
}

export function normalizeStrings(values) {
  return [...new Set((values || []).map((value) => String(value).trim()).filter(Boolean))]
}

export function normalizeWaves(waves) {
  return (waves || []).map((wave, index) => ({
    wave_id: String(wave.wave_id ?? wave.waveId ?? `wave-${index + 1}`).trim(),
    name: String(wave.name ?? "").trim(),
    purpose: String(wave.purpose ?? "").trim(),
    parallelism: wave.parallelism === "parallel" ? "parallel" : "serial",
    target_agents: normalizeStrings(wave.target_agents ?? wave.targetAgents ?? []),
    exit_criteria: normalizeStrings(wave.exit_criteria ?? wave.exitCriteria ?? []),
    notes: String(wave.notes ?? "").trim(),
  }))
}

export function createPlanId({ title, revision }) {
  const slug = String(title || "plan")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32)
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")
  const suffix = randomUUID().slice(0, 8)
  return `opencode-plan-${stamp}-${slug || "plan"}-r${revision}-${suffix}`
}

export function createCommentId() {
  return `opencode-comment-${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}-${randomUUID().slice(0, 8)}`
}

export function sha256Text(text) {
  return `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`
}

export function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf8"))
}

export function ensurePlanDirs(repoRoot) {
  mkdirSync(plansRoot(repoRoot), { recursive: true })
}

export function buildPlanRecord({
  repoRoot,
  planId,
  revision,
  title,
  objective,
  summary,
  assumptions,
  constraints,
  executionWaves,
  acceptanceCriteria,
  risks,
  openQuestions,
  revisionNotes,
  parentPlanId,
  parentPlanPath,
}) {
  const filePath = planPath(repoRoot, planId)
  const ledgerPath = commentLedgerPath(repoRoot, planId)

  return {
    schema_version: PLAN_SCHEMA_VERSION,
    plan_id: planId,
    revision,
    created_at: new Date().toISOString(),
    title: String(title ?? "").trim(),
    objective: String(objective ?? "").trim(),
    summary: String(summary ?? "").trim(),
    assumptions: normalizeStrings(assumptions),
    constraints: normalizeStrings(constraints),
    execution_waves: normalizeWaves(executionWaves),
    acceptance_criteria: normalizeStrings(acceptanceCriteria),
    risks: (risks || []).map((risk) => ({
      risk: String(risk.risk ?? "").trim(),
      impact: String(risk.impact ?? "").trim(),
      mitigation: String(risk.mitigation ?? "").trim(),
    })),
    open_questions: normalizeStrings(openQuestions),
    revision_notes: normalizeStrings(revisionNotes),
    parent_plan_id: parentPlanId ?? null,
    parent_plan_path: parentPlanPath ? toRepoRelative(repoRoot, parentPlanPath) : null,
    canonical_path: toRepoRelative(repoRoot, filePath),
    comment_ledger_path: toRepoRelative(repoRoot, ledgerPath),
    content_light: true,
  }
}

export function writePlanRecord(repoRoot, planRecord) {
  ensurePlanDirs(repoRoot)
  const filePath = planPath(repoRoot, planRecord.plan_id)
  writeFileSync(filePath, `${JSON.stringify(planRecord, null, 2)}\n`, "utf8")
  return {
    filePath,
    planRecord,
  }
}

export function loadPlanRecord(repoRoot, planId) {
  const filePath = planPath(repoRoot, planId)
  if (!existsSync(filePath)) {
    throw new Error(`Plan artifact not found: ${toRepoRelative(repoRoot, filePath)}`)
  }
  return {
    filePath,
    planRecord: readJson(filePath),
  }
}

export function buildCommentRecord({
  repoRoot,
  planRecord,
  criticName,
  waveId,
  severity,
  category,
  comment,
  suggestedChange,
  references,
}) {
  return {
    schema_version: COMMENT_SCHEMA_VERSION,
    comment_id: createCommentId(),
    created_at: new Date().toISOString(),
    plan_id: planRecord.plan_id,
    plan_revision: planRecord.revision,
    plan_digest: sha256Text(`${JSON.stringify(planRecord, null, 2)}\n`),
    critic_name: String(criticName ?? "critic").trim(),
    wave_id: waveId ? String(waveId).trim() : null,
    severity: ["blocking", "major", "minor", "nit"].includes(severity) ? severity : "minor",
    category: String(category ?? "other").trim() || "other",
    comment: String(comment ?? "").trim(),
    suggested_change: String(suggestedChange ?? "").trim(),
    references: normalizeStrings(references),
    content_light: true,
  }
}

export function appendCommentRecord(repoRoot, planRecord, commentRecord) {
  ensurePlanDirs(repoRoot)
  const ledger = commentLedgerPath(repoRoot, planRecord.plan_id)
  appendFileSync(ledger, `${JSON.stringify(commentRecord)}\n`, "utf8")
  return ledger
}

export function readCommentRecords(repoRoot, planId) {
  const ledger = commentLedgerPath(repoRoot, planId)
  if (!existsSync(ledger)) {
    return []
  }

  return readFileSync(ledger, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line))
}

export function reviewCriticism(repoRoot, planId) {
  const { filePath, planRecord } = loadPlanRecord(repoRoot, planId)
  const comments = readCommentRecords(repoRoot, planId).sort((left, right) => {
    if (left.created_at !== right.created_at) {
      return left.created_at.localeCompare(right.created_at)
    }
    return left.comment_id.localeCompare(right.comment_id)
  })

  const counts = comments.reduce(
    (acc, comment) => {
      acc.total += 1
      acc[comment.severity] += 1
      return acc
    },
    { total: 0, blocking: 0, major: 0, minor: 0, nit: 0 },
  )

  return {
    plan: planRecord,
    plan_path: toRepoRelative(repoRoot, filePath),
    plan_digest: sha256Text(`${JSON.stringify(planRecord, null, 2)}\n`),
    comment_ledger_path: planRecord.comment_ledger_path,
    comment_count: counts.total,
    blocking_comment_count: counts.blocking,
    severity_counts: counts,
    comments,
  }
}

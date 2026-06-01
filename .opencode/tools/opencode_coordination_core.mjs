import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync } from "node:fs"
import { createHash, randomUUID } from "node:crypto"
import { join, relative, resolve } from "node:path"

export const COORDINATION_MESSAGE_SCHEMA_VERSION = "opencode.coordination_message.v1"

export function resolveRepoRoot(worktree) {
  return resolve(worktree || process.cwd())
}

export function coordinationRoot(repoRoot) {
  return join(repoRoot, "docs", "json", "opencode", "coordination")
}

export function coordinationMessagesPath(repoRoot) {
  return join(coordinationRoot(repoRoot), "messages.jsonl")
}

export function ensureCoordinationDir(repoRoot) {
  mkdirSync(coordinationRoot(repoRoot), { recursive: true })
}

export function repoRelative(repoRoot, filePath) {
  return relative(repoRoot, filePath).split("\\").join("/")
}

export function stableDigest(payload) {
  return `sha256:${createHash("sha256").update(payload, "utf8").digest("hex")}`
}

export function createRecordId(prefix) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")
  return `${prefix}-${stamp}-${randomUUID().slice(0, 8)}`
}

export function normalizeList(values) {
  return [...new Set((values || []).map((value) => String(value).trim()).filter(Boolean))]
}

export function normalizeArtifactRefs(values) {
  return (values || []).map((value) => ({
    artifact_kind: String(value.artifact_kind ?? "").trim(),
    artifact_id: String(value.artifact_id ?? "").trim(),
    path: String(value.path ?? "").trim(),
    digest: String(value.digest ?? "").trim(),
  }))
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

export function writeJson(filePath, payload) {
  mkdirSync(join(filePath, ".."), { recursive: true })
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8")
}

export function appendJsonl(filePath, payload) {
  mkdirSync(join(filePath, ".."), { recursive: true })
  appendFileSync(filePath, `${JSON.stringify(payload)}\n`, "utf8")
}

export function normalizeRecipients({ recipientSessionId, recipientGroup, recipients }) {
  if (Array.isArray(recipients) && recipients.length) {
    return normalizeList(recipients)
  }
  const normalized = []
  if (recipientSessionId) {
    normalized.push(`session:${String(recipientSessionId).trim()}`)
  }
  if (recipientGroup) {
    normalized.push(`group:${String(recipientGroup).trim()}`)
  }
  if (!normalized.length) {
    normalized.push("group:all")
  }
  return normalizeList(normalized)
}

export function parseRecipient(recipient) {
  const value = String(recipient ?? "").trim()
  if (!value) {
    return null
  }
  const [kind, ...rest] = value.split(":")
  return {
    kind: kind === "session" || kind === "group" ? kind : "group",
    value: rest.join(":").trim(),
  }
}

export function recipientMatches(recipient, sessionId, includeGroups) {
  const parsed = parseRecipient(recipient)
  if (!parsed) {
    return false
  }
  if (parsed.kind === "session") {
    return parsed.value === sessionId
  }
  return includeGroups.includes(parsed.value)
}

export function buildCoordinationMessage({
  senderSessionId,
  senderRole,
  recipients,
  messageKind,
  subject,
  body,
  conversationId,
  replyToMessageId,
  waveId,
  artifactRefs,
}) {
  const messageId = createRecordId("opencode-coord")
  return {
    schema_version: COORDINATION_MESSAGE_SCHEMA_VERSION,
    message_id: messageId,
    created_at: new Date().toISOString(),
    conversation_id: conversationId ? String(conversationId).trim() : null,
    sender_session_id: String(senderSessionId ?? "").trim(),
    sender_role: String(senderRole ?? "").trim(),
    recipients: normalizeRecipients({
      recipients,
    }),
    message_kind: String(messageKind ?? "status").trim(),
    subject: String(subject ?? "").trim(),
    body: String(body ?? "").trim(),
    reply_to_message_id: replyToMessageId ? String(replyToMessageId).trim() : null,
    wave_id: waveId ? String(waveId).trim() : null,
    artifact_refs: normalizeArtifactRefs(artifactRefs),
    content_light: true,
  }
}

export function appendCoordinationMessage(repoRoot, message) {
  ensureCoordinationDir(repoRoot)
  const filePath = coordinationMessagesPath(repoRoot)
  appendJsonl(filePath, message)
  return filePath
}

export function readCoordinationMessages({
  repoRoot,
  sessionId,
  includeGroups = ["all", "orchestrator", "executors", "validators", "critics", "red-team"],
  conversationId = "",
  knownMessageIds = [],
  limit = 200,
}) {
  const messages = readJsonl(coordinationMessagesPath(repoRoot))
  const conversationFilter = String(conversationId ?? "").trim()
  const knownIds = new Set(normalizeList(knownMessageIds))
  const filtered = messages.filter((message) => {
    if (conversationFilter && String(message.conversation_id ?? "").trim() !== conversationFilter) {
      return false
    }
    if (knownIds.has(String(message.message_id ?? "").trim())) {
      return false
    }
    const recipients = Array.isArray(message.recipients) ? message.recipients : []
    return recipients.some((recipient) => recipientMatches(recipient, sessionId, includeGroups))
  })
  return filtered.slice(-Math.max(0, Number(limit) || 0))
}

import { tool } from "@opencode-ai/plugin"
import {
  appendCoordinationMessage,
  buildCoordinationMessage,
  resolveRepoRoot,
} from "./opencode_coordination_core.mjs"

const artifactRefSchema = tool.schema.object({
  artifact_kind: tool.schema.string(),
  artifact_id: tool.schema.string(),
  path: tool.schema.string().default(""),
  digest: tool.schema.string().default(""),
})

export default tool({
  description:
    "Append an OpenCode coordination message for another session, a role group, or all sessions. Messages are append-only and artifact-backed.",
  args: {
    sender_session_id: tool.schema.string(),
    sender_role: tool.schema.string(),
    message_kind: tool.schema.string(),
    subject: tool.schema.string(),
    body: tool.schema.string(),
    recipient_session_id: tool.schema.string().default(""),
    recipient_group: tool.schema.string().default(""),
    conversation_id: tool.schema.string().default(""),
    reply_to_message_id: tool.schema.string().default(""),
    wave_id: tool.schema.string().default(""),
    artifact_refs: tool.schema.array(artifactRefSchema).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const message = buildCoordinationMessage({
      senderSessionId: args.sender_session_id,
      senderRole: args.sender_role,
      recipients: [],
      messageKind: args.message_kind,
      subject: args.subject,
      body: args.body,
      conversationId: args.conversation_id || null,
      replyToMessageId: args.reply_to_message_id || null,
      waveId: args.wave_id || null,
      artifactRefs: args.artifact_refs,
    })
    message.recipients = []
    if (args.recipient_session_id) {
      message.recipients.push(`session:${args.recipient_session_id.trim()}`)
    }
    if (args.recipient_group) {
      message.recipients.push(`group:${args.recipient_group.trim()}`)
    }
    if (!message.recipients.length) {
      message.recipients.push("group:all")
    }

    const filePath = appendCoordinationMessage(repoRoot, message)
    return {
      title: `send_message: ${message.message_id}`,
      output: JSON.stringify(
        {
          message,
          messages_path: filePath,
        },
        null,
        2,
      ),
    }
  },
})

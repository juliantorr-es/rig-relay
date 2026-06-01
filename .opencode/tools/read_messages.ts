import { tool } from "@opencode-ai/plugin"
import {
  readCoordinationMessages,
  resolveRepoRoot,
} from "./opencode_coordination_core.mjs"

export default tool({
  description:
    "Read append-only OpenCode coordination messages for a session, with optional group filtering and local dedupe by known message ids.",
  args: {
    session_id: tool.schema.string(),
    conversation_id: tool.schema.string().default(""),
    known_message_ids: tool.schema.array(tool.schema.string()).default([]),
    include_groups: tool.schema.array(tool.schema.string()).default(["all", "orchestrator", "executors", "validators", "critics", "red-team"]),
    limit: tool.schema.number().default(200),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const messages = readCoordinationMessages({
      repoRoot,
      sessionId: args.session_id,
      conversationId: args.conversation_id || "",
      knownMessageIds: args.known_message_ids,
      includeGroups: args.include_groups,
      limit: args.limit,
    })

    return {
      title: `read_messages: ${messages.length}`,
      output: JSON.stringify(
        {
          messages,
          message_count: messages.length,
        },
        null,
        2,
      ),
    }
  },
})

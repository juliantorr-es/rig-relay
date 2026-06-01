import { tool } from "@opencode-ai/plugin"
import {
  resolveRepoRoot,
  writeFileWithContext,
} from "./opencode_context_core.mjs"

export default tool({
  description:
    "Write a file and automatically append a bounded context history event for concurrent agents.",
  args: {
    path: tool.schema.string().describe("Repository-relative or absolute path of the file to write."),
    content: tool.schema.string().describe("Full file contents to write."),
    reason: tool.schema.string().default("").describe("Short reason for the mutation; stored in the change ledger."),
    expected_before_sha256: tool.schema
      .string()
      .default("")
      .describe("Current file SHA256 when overwriting an existing file; leave empty for new files or protected-generated writes."),
    allow_overwrite_protected: tool.schema
      .boolean()
      .default(false)
      .describe("Bypass the expected hash guard for known-safe generated files."),
    preflight_only: tool.schema
      .boolean()
      .default(false)
      .describe("Return the impact warning and planned edit shape without mutating the file."),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const result = writeFileWithContext({
      repoRoot,
      path: args.path,
      content: args.content,
      reason: args.reason,
      expectedBeforeSha256: args.expected_before_sha256 || null,
      allowOverwriteProtected: args.allow_overwrite_protected,
      preflightOnly: args.preflight_only,
    })

    return {
      title: `${args.preflight_only ? "preflight" : "write"}: ${result.filePath}`,
      output: JSON.stringify(
        {
          preflight: result.preflight,
          file_path: result.filePath,
          artifact_path: result.context.artifactPath,
          ledger_path: result.ledgerPath,
          event: result.event,
          artifact: result.context.artifact,
          preview: result.context.preview,
          mutated: result.mutated,
        },
        null,
        2,
      ),
    }
  },
})

import { tool } from "@opencode-ai/plugin"
import {
  editFileWithContext,
  resolveRepoRoot,
} from "./opencode_context_core.mjs"

export default tool({
  description:
    "Apply a guided edit using whole-file content or targeted search/replace and append a bounded context history event.",
  args: {
    path: tool.schema.string().describe("Repository-relative or absolute path of the file to edit."),
    content: tool.schema.string().default("").describe("Full file contents for a whole-file edit."),
    search: tool.schema.string().default("").describe("Exact text to find for a targeted edit."),
    replace: tool.schema.string().default("").describe("Replacement text for the targeted edit."),
    all: tool.schema.boolean().default(true).describe("Replace every occurrence instead of only the first match."),
    instruction: tool.schema.string().default("").describe("Short human instruction describing the edit intent."),
    reason: tool.schema.string().default("").describe("Reason for the mutation; stored in the change ledger."),
    expected_before_sha256: tool.schema
      .string()
      .default("")
      .describe("Current file SHA256 when editing an existing file; leave empty for new files or protected-generated writes."),
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
    const result = editFileWithContext({
      repoRoot,
      path: args.path,
      content: args.content || null,
      search: args.search || null,
      replace: args.replace || null,
      all: args.all,
      instruction: args.instruction,
      reason: args.reason,
      expectedBeforeSha256: args.expected_before_sha256 || null,
      allowOverwriteProtected: args.allow_overwrite_protected,
      preflightOnly: args.preflight_only,
    })

    return {
      title: `${args.preflight_only ? "preflight" : "edit"}: ${result.filePath}`,
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

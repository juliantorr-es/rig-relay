import { tool } from "@opencode-ai/plugin"
import {
  searchReplaceFileWithContext,
  resolveRepoRoot,
} from "./opencode_context_core.mjs"

export default tool({
  description:
    "Apply a targeted search/replace edit and append a bounded context history event for concurrent agents.",
  args: {
    path: tool.schema.string().describe("Repository-relative or absolute path of the file to patch."),
    search: tool.schema.string().describe("Exact text to replace."),
    replace: tool.schema.string().describe("Replacement text."),
    all: tool.schema.boolean().default(true).describe("Replace every occurrence instead of only the first match."),
    reason: tool.schema.string().default("").describe("Short reason for the mutation; stored in the change ledger."),
    expected_before_sha256: tool.schema
      .string()
      .default("")
      .describe("Current file SHA256 when patching an existing file; leave empty for new files or protected-generated writes."),
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
    const result = searchReplaceFileWithContext({
      repoRoot,
      path: args.path,
      search: args.search,
      replace: args.replace,
      all: args.all,
      reason: args.reason,
      expectedBeforeSha256: args.expected_before_sha256 || null,
      allowOverwriteProtected: args.allow_overwrite_protected,
      preflightOnly: args.preflight_only,
    })

    return {
      title: `${args.preflight_only ? "preflight" : "search_replace"}: ${result.filePath}`,
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

import { tool } from "@opencode-ai/plugin"
import {
  readFileContext,
  resolveRepoRoot,
} from "./opencode_context_core.mjs"

export default tool({
  description:
    "Read a file and return a mechanical context digest with structure, dependencies, propagation, and recent change history.",
  args: {
    path: tool.schema.string().describe("Repository-relative or absolute path of the file to read."),
    include_content: tool.schema
      .boolean()
      .default(true)
      .describe("Include the file contents in the response."),
    include_history: tool.schema
      .boolean()
      .default(true)
      .describe("Include the recent five-event context ledger in the response."),
    depth: tool.schema
      .number()
      .default(1)
      .describe("Recursive context depth for linked dependencies and dependents."),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const result = readFileContext({
      repoRoot,
      path: args.path,
      includeContent: args.include_content,
      includeHistory: args.include_history,
      depth: args.depth,
    })

    return {
      title: `read: ${result.artifact.target_path}`,
      output: JSON.stringify(
        {
          file_path: result.filePath,
          artifact_path: result.artifactPath,
          ledger_path: result.ledgerPath,
          artifact: result.artifact,
          preview: result.preview,
          content: result.content,
        },
        null,
        2,
      ),
    }
  },
})

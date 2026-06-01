import { tool } from "@opencode-ai/plugin"
import { resolveRepoRoot, reviewCriticism } from "./opencode_plan_core.mjs"

export default tool({
  description:
    "Read a canonical OpenCode plan artifact together with all appended critic comments and return a synthesized review bundle.",
  args: {
    plan_id: tool.schema.string(),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const review = reviewCriticism(repoRoot, args.plan_id)

    return {
      title: `review_criticism: ${review.plan.plan_id}`,
      output: JSON.stringify(review, null, 2),
    }
  },
})


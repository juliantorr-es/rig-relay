import { tool } from "@opencode-ai/plugin"
import {
  buildStressArtifact,
  readPlan,
  resolveRepoRoot,
} from "./opencode_wave_core.mjs"

export default tool({
  description:
    "Record a red-team or stress-wave artifact for a specific OpenCode plan version. The adversary writes the attack surface, break attempts, surviving weaknesses, and repair recommendations into a canonical JSON artifact.",
  args: {
    plan_id: tool.schema.string(),
    wave_id: tool.schema.string(),
    red_team_name: tool.schema.string(),
    attacks: tool.schema.array(tool.schema.string()).default([]),
    attack_surface: tool.schema.array(tool.schema.string()).default([]),
    survived: tool.schema.boolean(),
    breakages: tool.schema.array(tool.schema.string()).default([]),
    repaired_seams: tool.schema.array(tool.schema.string()).default([]),
    recommendations: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { plan } = readPlan(repoRoot, args.plan_id)
    const { filePath, artifact } = buildStressArtifact({
      repoRoot,
      plan,
      redTeamName: args.red_team_name,
      waveId: args.wave_id,
      attacks: args.attacks,
      attack_surface: args.attack_surface,
      survived: args.survived,
      breakages: args.breakages,
      repaired_seams: args.repaired_seams,
      recommendations: args.recommendations,
    })

    return {
      title: `record_stress_wave: ${artifact.artifact_id}`,
      output: JSON.stringify(
        {
          artifact_path: filePath,
          artifact,
        },
        null,
        2,
      ),
    }
  },
})


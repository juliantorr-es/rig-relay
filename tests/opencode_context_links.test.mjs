import test from "node:test"
import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { readFileContext } from "./../.opencode/tools/opencode_context_core.mjs"

test("file context links can be walked recursively", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "opencode-context-links-"))

  try {
    mkdirSync(join(repoRoot, "src"), { recursive: true })
    writeFileSync(join(repoRoot, "src", "leaf.ts"), "export const leaf = 1\n")
    writeFileSync(join(repoRoot, "src", "mid.ts"), "import { leaf } from './leaf'\nexport const mid = leaf\n")
    writeFileSync(join(repoRoot, "src", "root.ts"), "import { mid } from './mid'\nexport const root = mid\n")

    const result = readFileContext({
      repoRoot,
      path: "src/root.ts",
      includeContent: false,
      includeHistory: false,
      depth: 2,
    })

    assert.equal(result.artifact.linked_contexts.length, 1)
    assert.equal(result.artifact.linked_contexts[0].target_path, "src/mid.ts")
    assert.equal(result.artifact.linked_contexts[0].linked_contexts[0].target_path, "src/leaf.ts")
  } finally {
    rmSync(repoRoot, { recursive: true, force: true })
  }
})

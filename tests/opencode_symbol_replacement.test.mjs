import test from "node:test"
import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { readFileContext } from "./../.opencode/tools/opencode_context_core.mjs"

test("symbol records are deterministic and stable enough for replacement planning", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "opencode-symbol-replace-"))

  try {
    mkdirSync(join(repoRoot, "src"), { recursive: true })
    writeFileSync(join(repoRoot, "src", "dep.ts"), "export const dep = 1\n")
    writeFileSync(
      join(repoRoot, "src", "example.ts"),
      "import { dep } from './dep'\nexport function alpha() { return dep }\n",
    )

    const context = readFileContext({
      repoRoot,
      path: "src/example.ts",
      includeContent: true,
      includeHistory: false,
      depth: 0,
    })

    assert.ok(context.artifact.symbol_records.length >= 1)
    assert.match(context.artifact.symbol_records[0].symbol_id, /^sha256:/)
    assert.equal(context.artifact.symbol_records[0].replacement_key.includes("#"), true)
    assert.equal(context.artifact.symbol_records[0].references_out.length >= 1, true)
  } finally {
    rmSync(repoRoot, { recursive: true, force: true })
  }
})

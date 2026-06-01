import { readFileSync } from "node:fs"
import { extname, isAbsolute, resolve } from "node:path"
import { spawnSync } from "node:child_process"

const LANGUAGE_BY_EXT = {
  ".py": "python",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".js": "javascript",
  ".jsx": "javascript",
  ".rs": "rust",
  ".go": "go",
  ".swift": "swift",
  ".java": "java",
}

const PATTERN_PLANS = {
  python: [
    {
      label: "functions",
      patterns: ["def $NAME($$$): $$$"],
    },
    {
      label: "classes",
      patterns: ["class $NAME: $$$"],
    },
    {
      label: "imports",
      patterns: ["from $$$ import $$$", "import $$$"],
    },
  ],
  typescript: [
    {
      label: "functions",
      patterns: [
        "function $NAME($$$) { $$$ }",
        "export function $NAME($$$) { $$$ }",
      ],
    },
    {
      label: "classes",
      patterns: ["class $NAME { $$$ }", "export class $NAME { $$$ }"],
    },
    {
      label: "constants",
      patterns: [
        "const $NAME = ($$$) => { $$$ }",
        "export const $NAME = ($$$) => { $$$ }",
      ],
    },
  ],
  javascript: [
    {
      label: "functions",
      patterns: [
        "function $NAME($$$) { $$$ }",
        "export function $NAME($$$) { $$$ }",
      ],
    },
    {
      label: "classes",
      patterns: ["class $NAME { $$$ }", "export class $NAME { $$$ }"],
    },
    {
      label: "constants",
      patterns: [
        "const $NAME = ($$$) => { $$$ }",
        "export const $NAME = ($$$) => { $$$ }",
      ],
    },
  ],
  rust: [
    {
      label: "functions",
      patterns: ["fn $NAME($$$) { $$$ }"],
    },
    {
      label: "types",
      patterns: ["struct $NAME { $$$ }", "enum $NAME { $$$ }"],
    },
    {
      label: "impls",
      patterns: ["impl $TYPE { $$$ }"],
    },
  ],
  go: [
    {
      label: "functions",
      patterns: ["func $NAME($$$) { $$$ }"],
    },
    {
      label: "types",
      patterns: ["type $NAME struct { $$$ }"],
    },
  ],
  swift: [
    {
      label: "functions",
      patterns: ["func $NAME($$$) { $$$ }"],
    },
    {
      label: "types",
      patterns: ["class $NAME { $$$ }", "struct $NAME { $$$ }", "enum $NAME { $$$ }"],
    },
  ],
  java: [
    {
      label: "types",
      patterns: ["class $NAME { $$$ }", "interface $NAME { $$$ }"],
    },
    {
      label: "methods",
      patterns: ["void $NAME($$$) { $$$ }"],
    },
  ],
}

const MAX_OUTLINE_ITEMS = 6
const MAX_EXCERPTS = 3
const MAX_FALLBACK_LINES = 120
const MAX_SNIPPET_CHARS = 1000

export function inferLanguage(filePath) {
  return LANGUAGE_BY_EXT[extname(filePath).toLowerCase()] ?? null
}

export function buildPatternPlan(language) {
  return PATTERN_PLANS[language] ?? []
}

export function resolveToolPath(worktree, inputPath) {
  return isAbsolute(inputPath) ? inputPath : resolve(worktree, inputPath)
}

export function readSmartFile({ worktree, path }) {
  const filePath = resolveToolPath(worktree, path)
  const content = readFileSync(filePath, "utf8")
  const language = inferLanguage(filePath)
  const outline = language ? collectOutline(filePath, language) : []
  const excerpts = outline.length ? outline.slice(0, MAX_EXCERPTS) : []
  const mode = outline.length ? "ast-outline" : "line-preview"
  const output = formatSmartReadOutput({
    filePath,
    language,
    mode,
    content,
    outline,
    excerpts,
  })

  return {
    filePath,
    language,
    mode,
    content,
    outline,
    excerpts,
    output,
  }
}

function collectOutline(filePath, language) {
  const matches = collectAstMatches(filePath, language)
  const outline = []
  const seen = new Set()

  for (const match of matches) {
    const startLine = match.range?.start?.line ?? 0
    const endLine = match.range?.end?.line ?? startLine
    const text = typeof match.text === "string" ? match.text.trim() : ""
    const name = extractMatchName(match)
    const key = `${startLine}:${endLine}`

    if (seen.has(key)) {
      continue
    }
    seen.add(key)

    outline.push({
      label: match.label,
      name,
      startLine,
      endLine,
      snippet: text,
    })

    if (outline.length >= MAX_OUTLINE_ITEMS) {
      break
    }
  }

  if (outline.length > 1) {
    outline.sort((left, right) => left.startLine - right.startLine)
  }

  return outline
}

function collectAstMatches(filePath, language) {
  const matches = []
  for (const plan of buildPatternPlan(language)) {
    for (const pattern of plan.patterns) {
      const result = runAstGrep(filePath, language, pattern)
      for (const entry of result) {
        matches.push({
          label: plan.label,
          ...entry,
        })
      }
    }
  }
  return matches
}

function runAstGrep(filePath, language, pattern) {
  const result = spawnSync("sg", ["-p", pattern, "--lang", language, "--json", filePath], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
  })

  if (result.error?.code === "ENOENT") {
    return []
  }

  if (result.error || (result.status !== 0 && result.status !== 1)) {
    return []
  }

  const text = (result.stdout ?? "").trim()
  if (!text) {
    return []
  }

  try {
    const parsed = JSON.parse(text)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function extractMatchName(match) {
  const single = match.metaVariables?.single
  if (!single || typeof single !== "object") {
    return ""
  }

  const first = Object.values(single)[0]
  if (!first || typeof first !== "object") {
    return ""
  }

  return typeof first.text === "string" ? first.text : ""
}

function formatSmartReadOutput({ filePath, language, mode, content, outline, excerpts }) {
  const lines = content.split(/\r?\n/)
  const header = [`file: ${filePath}`, `language: ${language ?? "unknown"}`, `mode: ${mode}`]
  const sections = [header.join("\n")]

  if (outline.length) {
    sections.push(
      [
        "outline:",
        ...outline.map((entry, index) => {
          const lineRange = `${entry.startLine + 1}-${entry.endLine + 1}`
          const namePart = entry.name ? ` ${entry.name}` : ""
          return `${index + 1}. ${entry.label}${namePart} [${lineRange}]`
        }),
      ].join("\n")
    )
  } else {
    sections.push("outline:\n- none")
  }

  const excerptBlocks =
    excerpts.length > 0
      ? excerpts
          .map((entry, index) => {
            const excerpt = buildExcerptBlock(lines, entry.startLine, entry.endLine)
            return [
              `${index + 1}. ${entry.label}${entry.name ? ` ${entry.name}` : ""} [${
                entry.startLine + 1
              }-${entry.endLine + 1}]`,
              excerpt,
            ].join("\n")
          })
          .join("\n\n")
      : buildFallbackPreview(lines)

  sections.push(["selected excerpts:", excerptBlocks].join("\n"))
  return sections.join("\n\n")
}

function buildExcerptBlock(lines, startLine, endLine) {
  const contextStart = Math.max(0, startLine - 1)
  const contextEnd = Math.min(lines.length - 1, endLine + 1)
  const block = []

  for (let line = contextStart; line <= contextEnd; line += 1) {
    block.push(`${String(line + 1).padStart(4, " ")} | ${lines[line] ?? ""}`)
  }

  const text = block.join("\n")
  return text.length > MAX_SNIPPET_CHARS ? `${text.slice(0, MAX_SNIPPET_CHARS)}…` : text
}

function buildFallbackPreview(lines) {
  const slice = lines.slice(0, MAX_FALLBACK_LINES)
  const block = slice.map((line, index) => `${String(index + 1).padStart(4, " ")} | ${line}`)
  const text = block.join("\n")
  if (lines.length > MAX_FALLBACK_LINES) {
    return `${text}\n… ${lines.length - MAX_FALLBACK_LINES} more line(s) omitted`
  }
  return text
}

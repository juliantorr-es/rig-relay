# Python Language Practices

Best-practice anchors referenced by out-of-scope findings in this repository.
These are the authoritative references for Python-specific code quality and style governance.

## Baseline Style

**[PEP 8](https://peps.python.org/pep-0008/)** is the baseline Python style doctrine.
It covers code layout, naming conventions, comments, and programming recommendations.
All Python code in this repository SHALL follow PEP 8 unless explicitly overridden by project conventions in `AGENTS.md` or `pyproject.toml`.

Key PEP 8 principles applied here:
- 4-space indentation, no tabs.
- Line length limit of 88 (Ruff default, compatible with Black).
- Blank lines around top-level definitions and class methods.
- Imports at top of file, grouped standard library → third-party → local.
- No extraneous whitespace.

## Lint and Format Authority

**[Ruff](https://docs.astral.sh/ruff/)** is the sole lint and format authority for this repository.
Configuration lives in `pyproject.toml` under `[tool.ruff]`.

### Key Ruff Rules

| Rule | Meaning | Action |
|------|---------|--------|
| **PLR0914** | Too many local variables (>15) | Extract helper methods or group related locals into a typed dataclass / small value object. Do NOT suppress with `# noqa`. |
| **PLR0915** | Too many statements (>50) | Split the function into named phase helpers. Each phase should have one clear responsibility. |
| **PLR0911** | Too many return statements (>6) | Consolidate early returns with a helper method, or use a result variable with a single return. |
| **PLR0912** | Too many branches (>15) | Break complex conditionals into guard clauses or strategy patterns. |
| **PLR0913** | Too many arguments (>10) | Group related arguments into a typed dataclass or Pydantic model. |

### PLR0914 / PLR0915 Strategy

When a function triggers PLR0914 (too many locals) or PLR0915 (too many statements):

1. **Identify phases.** What distinct phases does the function go through? (parse, validate, apply, emit)
2. **Extract helpers.** Each phase becomes a private method. Pass only the state each helper needs.
3. **Group state.** If many locals represent one conceptual bundle, create a small `@dataclass` or Pydantic model.
4. **Prefer targeted extraction over broad rewrites.** During active multi-agent work, extract one phase at a time rather than restructuring the entire function.

Example anti-pattern (PLR0914 trigger):
```python
def run(self, args, ctx):
    path = self._resolve_path(args.path)
    content = self._read_file(path)
    before_hash = self._hash(content)
    blocks = self._parse_blocks(args.content)
    valid_blocks = self._validate_blocks(blocks)
    applied = 0
    failed = 0
    # ... 10 more locals ...
```

Example resolution:
```python
def run(self, args, ctx):
    target = self._prepare_target(args)
    result = self._apply_blocks(target, self._parse_blocks(args.content))
    self._emit_evidence(target, result)
```

## Project-Specific Conventions

These override or extend PEP 8 and are defined in `AGENTS.md`:

- Prefer `match`/`case` over long `if`/`elif` chains.
- Use walrus `:=` only when it shortens code and improves clarity.
- Never-nester: early returns and guard clauses over nested blocks.
- Modern type hints: built-in generics (`list`, `dict`) and `|` unions.
- `StrEnum`/`IntEnum` with `auto()` and UPPERCASE members.
- No inline `# type: ignore` or `# noqa`. Fix at the source.
- Declarative, minimalist code.

## Diátaxis Documentation Model

Project documentation follows the **[Diátaxis](https://diataxis.fr/)** framework, which organizes docs into four distinct types:

| Type | Purpose | Example in this repo |
|------|---------|---------------------|
| **Tutorial** | Learning-oriented, step-by-step | `docs/dogfood/rig-relay-self-dogfood.md` |
| **How-To** | Task-oriented, solving a specific problem | Governance docs under `docs/governance/` |
| **Reference** | Information-oriented, technical description | `docs/audits/`, `docs/schemas/`, `docs/findings/language-practices/` |
| **Explanation** | Understanding-oriented, background and context | `docs/audits/deep-research-report*.md` |

New documentation should be placed in the appropriate Diátaxis category.
Do not mix tutorials with reference material or how-to guides with explanatory background.

## References

- [PEP 8 – Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [Ruff Rules Reference](https://docs.astral.sh/ruff/rules/)
- [Diátaxis Documentation Framework](https://diataxis.fr/)
- [Swift API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/) (for cross-language reference)

# Contributing to Rig Relay

## Contributor License Agreement

By submitting a contribution to this project, you agree to the Contributor
License Agreement in [`CONTRIBUTOR_LICENSE_AGREEMENT.md`](CONTRIBUTOR_LICENSE_AGREEMENT.md).

You keep copyright in your contribution.

You agree that your contribution is made available to the public under this
repository's current open-source license, currently AGPL-3.0-or-later.

You also grant the project maintainer the right to relicense or dual-license
your contribution in the future. This is required so the project can remain
commercially sustainable, support paid distributions, support enterprise
licensing, and avoid locking the maintainer out of future licensing options.

The project will preserve contributor attribution through Git history and
project attribution records where practical.

## Contribution Signoff

By submitting a pull request, you confirm:

> By submitting this contribution, I confirm that I have the right to submit it,
> that I agree to the Contributor License Agreement, and that my contribution may
> be used under the project's current open-source license and may also be
> relicensed or dual-licensed by the project maintainer.

## Development Setup

See README.md for setup instructions.

## Conventions

Read [AGENTS.md](AGENTS.md) for the full agent and human contributor conventions.

Key rules:
- Use `uv` for all commands, never bare `python` or `pip`
- Tests live in `tests/` mirroring source layout
- No relative imports
- Pydantic models with `extra="forbid"`
- Modern type hints only (built-in generics, `|` unions)

## Pull Requests

1. Create a new branch from `main`
2. Make focused, convergent changes
3. Run `uv run ruff check --fix .` and `uv run ruff format .`
4. Run `uv run pyright`
5. Run `uv run pytest`
6. Run `uv run rig-relay demo-doctor`
7. Do not amend, force-push, or merge
8. Plain `git push` only

## License

Rig Relay is licensed under AGPL-3.0-or-later for the public repository.
This license is intentional. Rig Relay is designed to operate as local and
networked agent infrastructure. Modified versions that provide network
interaction to users must comply with AGPL-3.0 section 13, including
offering Corresponding Source to those users.

Commercial, enterprise, embedded, app-store, hosted, or proprietary
licensing may be available separately from the project maintainer.

See [LICENSE](LICENSE) for the full license text.

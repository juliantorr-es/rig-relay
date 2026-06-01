import assert from "node:assert/strict";
import test from "node:test";

import { routeBashCommand } from "./../.opencode/tools/bash_router_core.mjs";

test("bash router sends cat to read_file", () => {
	const route = routeBashCommand("cat docs/README.md");
	assert.equal(route?.kind, "read_file");
	assert.equal(route?.path, "docs/README.md");
});

test("bash router sends head to read_file with limit", () => {
	const route = routeBashCommand("head -n 5 docs/README.md");
	assert.equal(route?.kind, "read_file");
	assert.equal(route?.path, "docs/README.md");
	assert.equal(route?.limit, 5);
});

test("bash router sends echo redirect to write_file", () => {
	const route = routeBashCommand("echo hello > output.txt");
	assert.equal(route?.kind, "write_file");
	assert.equal(route?.path, "output.txt");
	assert.equal(route?.content, "hello\n");
	assert.equal(route?.overwrite, true);
});

test("bash router sends sed substitution to search_replace", () => {
	const route = routeBashCommand("sed -i 's/old/new/g' file.txt");
	assert.equal(route?.kind, "search_replace");
	assert.equal(route?.path, "file.txt");
	assert.equal(route?.search, "old");
	assert.equal(route?.replace, "new");
	assert.equal(route?.all, true);
});

test("bash router sends ruff check to validate lint", () => {
	const route = routeBashCommand("uv run ruff check tests/test_example.py");
	assert.equal(route?.kind, "validate");
	assert.equal(route?.mode, "lint");
	assert.deepEqual(route?.paths, ["tests/test_example.py"]);
});

test("bash router keeps ruff flags on validate lint", () => {
	const route = routeBashCommand(
		"uv run ruff check --fix tests/test_example.py",
	);
	assert.equal(route?.kind, "validate");
	assert.deepEqual(route?.extra_args, ["--fix"]);
	assert.deepEqual(route?.paths, ["tests/test_example.py"]);
});

test("bash router sends pyright to validate typecheck", () => {
	const route = routeBashCommand("uv run pyright src/module.py");
	assert.equal(route?.kind, "validate");
	assert.equal(route?.mode, "typecheck");
	assert.deepEqual(route?.paths, ["src/module.py"]);
});

test("bash router sends pytest to test", () => {
	const route = routeBashCommand("uv run pytest tests/test_example.py -q");
	assert.equal(route?.kind, "test");
	assert.deepEqual(route?.paths, ["tests/test_example.py"]);
	assert.deepEqual(route?.extra_args, ["-q"]);
});

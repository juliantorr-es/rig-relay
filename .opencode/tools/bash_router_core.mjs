import { exec } from "node:child_process";
import { promisify } from "node:util";

const execAsync = promisify(exec);

function stripQuotes(token) {
	if (token.length >= 2) {
		const first = token[0];
		const last = token[token.length - 1];
		if ((first === "'" && last === "'") || (first === '"' && last === '"')) {
			return token.slice(1, -1);
		}
	}
	return token;
}

function tokenize(command) {
	const matches = command.match(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\S+/g);
	return matches ? matches.map(stripQuotes) : [];
}

function parseSubstitutionExpression(script) {
	if (!script || script[0] !== "s" || script.length < 4) {
		return null;
	}
	const separator = script[1];
	const remainder = script.slice(2);
	const parts = remainder.split(separator);
	if (parts.length < 3) {
		return null;
	}
	const search = parts[0];
	const replace = parts[1];
	const flags = parts.slice(2).join(separator);
	if (!search) {
		return null;
	}
	return {
		search,
		replace,
		all: flags.includes("g"),
	};
}

function parseRedirect(tokens) {
	const redirectIndex = tokens.indexOf(">");
	if (redirectIndex < 2 || redirectIndex + 1 >= tokens.length) {
		return null;
	}
	return {
		path: tokens[redirectIndex + 1],
		contentTokens: tokens.slice(1, redirectIndex),
	};
}

function parseReadCommand(tokens) {
	if (!tokens.length) {
		return null;
	}
	const root = tokens[0];
	if (root === "cat" && tokens.length >= 2) {
		return { kind: "read_file", path: tokens[1], limit: null, offset: 0 };
	}
	if (root === "head" || root === "tail") {
		let limit = null;
		let path = null;
		for (let index = 1; index < tokens.length; index += 1) {
			const token = tokens[index];
			if (token === "-n" && index + 1 < tokens.length) {
				const value = Number.parseInt(tokens[index + 1], 10);
				if (!Number.isNaN(value)) {
					limit = value;
					index += 1;
					continue;
				}
			}
			if (token.startsWith("-n") && token.length > 2) {
				const value = Number.parseInt(token.slice(2), 10);
				if (!Number.isNaN(value)) {
					limit = value;
					continue;
				}
			}
			if (!token.startsWith("-")) {
				path = token;
				break;
			}
		}
		if (!path) {
			return null;
		}
		return { kind: "read_file", path, limit, offset: root === "tail" ? -1 : 0 };
	}
	if (root === "sed" && tokens[1] === "-n" && tokens[2] && tokens[3]) {
		const range = tokens[2];
		const path = tokens[3];
		const match = range.match(/^(\d+),(\d+)p$/);
		if (!match) {
			return null;
		}
		return {
			kind: "read_file",
			path,
			offset: Number.parseInt(match[1], 10) - 1,
			limit: Number.parseInt(match[2], 10) - Number.parseInt(match[1], 10) + 1,
		};
	}
	if (["less", "more", "bat"].includes(root) && tokens[1]) {
		return { kind: "read_file", path: tokens[1], limit: null, offset: 0 };
	}
	return null;
}

function parseWriteCommand(tokens) {
	if (!tokens.length) {
		return null;
	}
	const root = tokens[0];
	if (!["echo", "printf"].includes(root)) {
		return null;
	}
	if (tokens.includes(">>")) {
		return null;
	}
	const redirect = parseRedirect(tokens);
	if (!redirect) {
		return null;
	}
	const bodyTokens = redirect.contentTokens;
	if (!bodyTokens.length) {
		return null;
	}

	let newline = root === "echo";
	const contentParts = [...bodyTokens];
	if (root === "echo" && contentParts[0] === "-n") {
		newline = false;
		contentParts.shift();
	}
	if (!contentParts.length) {
		return null;
	}

	const content = contentParts.join(" ") + (newline ? "\n" : "");
	return {
		kind: "write_file",
		path: redirect.path,
		content,
		overwrite: true,
	};
}

function parseSearchReplaceCommand(tokens) {
	if (!tokens.length) {
		return null;
	}
	const root = tokens[0];
	if (!["sed", "perl"].includes(root)) {
		return null;
	}

	let script = null;
	let path = null;
	for (let index = 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (root === "sed" && token === "-i") {
			continue;
		}
		if (root === "perl" && ["-0pi", "-pi", "-i"].includes(token)) {
			continue;
		}
		if (token === "-e" && index + 1 < tokens.length) {
			script = tokens[index + 1];
			index += 1;
			continue;
		}
		if (token.startsWith("-")) {
			continue;
		}
		if (script === null && token.startsWith("s")) {
			script = token;
			continue;
		}
		path = token;
	}

	if (!script || !path) {
		return null;
	}

	const substitution = parseSubstitutionExpression(script);
	if (!substitution) {
		return null;
	}

	return {
		kind: "search_replace",
		path,
		search: substitution.search,
		replace: substitution.replace,
		all: substitution.all,
	};
}

function stripUvRun(tokens) {
	if (tokens[0] === "uv" && tokens[1] === "run") {
		return tokens.slice(2);
	}
	return tokens;
}

function collectPaths(tokens) {
	return tokens.filter(
		(token) => !token.startsWith("-") && !token.includes("="),
	);
}

function parseValidationCommand(tokens) {
	const inner = stripUvRun(tokens);
	if (!inner.length) {
		return null;
	}

	const root = inner[0];
	if (root === "ruff" && inner[1] === "check") {
		return {
			kind: "validate",
			mode: "lint",
			paths: collectPaths(inner.slice(2)),
			extra_args: inner.slice(2).filter((token) => token.startsWith("-")),
		};
	}
	if (root === "pyright") {
		return {
			kind: "validate",
			mode: "typecheck",
			paths: collectPaths(inner.slice(1)),
			extra_args: inner.slice(1).filter((token) => token.startsWith("-")),
		};
	}
	if (
		root === "pytest" ||
		root === "pytest3" ||
		(root === "python" && inner[1] === "-m" && inner[2] === "pytest")
	) {
		const startIndex = root === "python" ? 3 : 1;
		return {
			kind: "test",
			paths: collectPaths(inner.slice(startIndex)),
			extra_args: inner
				.slice(startIndex)
				.filter((token) => token.startsWith("-")),
		};
	}

	return null;
}

export function routeBashCommand(command) {
	const tokens = tokenize(command);
	if (!tokens.length) {
		return null;
	}

	return (
		parseValidationCommand(tokens) ??
		parseReadCommand(tokens) ??
		parseWriteCommand(tokens) ??
		parseSearchReplaceCommand(tokens)
	);
}

export async function runShellCommand(
	command,
	cwd,
	timeoutSeconds,
	maxBufferBytes,
) {
	try {
		const result = await execAsync(command, {
			cwd,
			timeout: timeoutSeconds * 1000,
			maxBuffer: maxBufferBytes,
			windowsHide: true,
		});
		return {
			status: "success",
			exit_code: 0,
			stdout: result.stdout,
			stderr: result.stderr,
		};
	} catch (error) {
		return {
			status: error?.killed ? "timed_out" : "failure",
			exit_code:
				typeof error?.code === "number" ? error.code : error?.signal ? -1 : 1,
			stdout: String(error?.stdout ?? ""),
			stderr: String(error?.stderr ?? error?.message ?? ""),
		};
	}
}

"""Fix the corrupted search_replace blocks in test file."""

from pathlib import Path

path = Path("tests/runtime/test_runtime_tool_invocation_execution.py")
content = path.read_text(encoding="utf-8")

# Fix 1: test_no_match_returns_completed
old_no_match = (
    "    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """Search text not found returns tool_status=\'no_match\', status=COMPLETED."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('some existing content\n"
    "', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\n"
    "nonexistent_text_xyz\n"
    "=======\n"
    "replacement\n"
    ">>>>>>> REPLACE'\n"
    "                ),\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'no_match'\n"
)

new_no_match = (
    "    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """Search text not found returns tool_status=\'no_match\', status=COMPLETED."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('some existing content\\n', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\\nnonexistent_text_xyz\\n=======\\nreplacement\\n>>>>>>> REPLACE'\n"
    "                ),\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'no_match'\n"
)

assert old_no_match in content, "Fix 1: old_no_match not found!"
content = content.replace(old_no_match, new_no_match, 1)
print("Fix 1 applied: test_no_match_returns_completed")

# Fix 2: test_ambiguous_match_returns_completed
old_ambiguous = (
    "    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """Duplicate SEARCH text with allow_multiple=False returns ambiguous_match."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('repeat\n"
    "other\n"
    "repeat\n"
    "', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\n"
    "repeat\n"
    "=======\n"
    "changed\n"
    ">>>>>>> REPLACE'\n"
    "                ),\n"
    "                'allow_multiple': False,\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'ambiguous_match'\n"
)

new_ambiguous = (
    "    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """Duplicate SEARCH text with allow_multiple=False returns ambiguous_match."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('repeat\\nother\\nrepeat\\n', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\\nrepeat\\n=======\\nchanged\\n>>>>>>> REPLACE'\n"
    "                ),\n"
    "                'allow_multiple': False,\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'ambiguous_match'\n"
)

assert old_ambiguous in content, "Fix 2: old_ambiguous not found!"
content = content.replace(old_ambiguous, new_ambiguous, 1)
print("Fix 2 applied: test_ambiguous_match_returns_completed")

# Fix 3: test_count_mismatch_returns_completed
old_mismatch = (
    "    async def test_count_mismatch_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """expected_replacements not matching actual returns count_mismatch."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('target\n"
    "', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\n"
    "target\n"
    "=======\n"
    "replaced\n"
    ">>>>>>> REPLACE'\n"
    "                ),\n"
    "                'expected_replacements': 5,\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'count_mismatch'\n"
)

new_mismatch = (
    "    async def test_count_mismatch_returns_completed(self, tmp_path: Path) -> None:\n"
    '        """expected_replacements not matching actual returns count_mismatch."""\n'
    "        target = tmp_path / 'test.py'\n"
    "        target.write_text('target\\n', encoding='utf-8')\n"
    "        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))\n"
    "        resolution = RuntimeContextResolution(status='resolved', context=ctx)\n"
    "        intent = _intent(\n"
    "            RuntimeToolName.SEARCH_REPLACE,\n"
    "            payload={\n"
    "                'file_path': 'test.py',\n"
    "                'content': (\n"
    "                    '<<<<<<< SEARCH\\ntarget\\n=======\\nreplaced\\n>>>>>>> REPLACE'\n"
    "                ),\n"
    "                'expected_replacements': 5,\n"
    "            },\n"
    "        )\n"
    "        runner = RuntimeToolExecutionRunner()\n"
    "        result = await runner.execute_search_replace(intent, resolution)\n"
    "        assert result.status == RuntimeToolExecutionStatus.COMPLETED\n"
    "        assert result.tool_status == 'count_mismatch'\n"
)

assert old_mismatch in content, "Fix 3: old_mismatch not found!"
content = content.replace(old_mismatch, new_mismatch, 1)
print("Fix 3 applied: test_count_mismatch_returns_completed")

path.write_text(content, encoding="utf-8")
print("All fixes applied. File saved.")

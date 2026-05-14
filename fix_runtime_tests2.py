from pathlib import Path

path = Path("tests/runtime/test_runtime_tool_invocation_execution.py")
content = path.read_text(encoding="utf-8")

# Content to append after TestSearchReplaceSchema
# Includes: TestSearchReplaceStatus (new), then all original missing classes
append = """

# ── SearchReplace status tests


class TestSearchReplaceStatus:
    \"\"\"Tests for search_replace status mapping through the adapter.\"\"\"

    @pytest.mark.asyncio
    async def test_no_match_returns_completed(self, tmp_path: Path) -> None:
        \"\"\"Search text not found returns tool_status='no_match', status=COMPLETED.\"\"\"
        target = tmp_path / 'test.py'
        target.write_text('some existing content\\n', encoding='utf-8')
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': (
                    '<<<<<<< SEARCH\\nnonexistent_text_xyz\\n=======\\nreplacement\\n>>>>>>> REPLACE'
                ),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == 'no_match'

    @pytest.mark.asyncio
    async def test_ambiguous_match_returns_completed(self, tmp_path: Path) -> None:
        \"\"\"Duplicate SEARCH text with allow_multiple=False returns ambiguous_match.\"\"\"
        target = tmp_path / 'test.py'
        target.write_text('repeat\\nother\\nrepeat\\n', encoding='utf-8')
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': (
                    '<<<<<<< SEARCH\\nrepeat\\n=======\\nchanged\\n>>>>>>> REPLACE'
                ),
                'allow_multiple': False,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == 'ambiguous_match'

    @pytest.mark.asyncio
    async def test_count_mismatch_returns_completed(self, tmp_path: Path) -> None:
        \"\"\"expected_replacements not matching actual returns count_mismatch.\"\"\"
        target = tmp_path / 'test.py'
        target.write_text('target\\n', encoding='utf-8')
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': (
                    '<<<<<<< SEARCH\\ntarget\\n=======\\nreplaced\\n>>>>>>> REPLACE'
                ),
                'expected_replacements': 5,
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.tool_status == 'count_mismatch'

    @pytest.mark.asyncio
    async def test_unsupported_tool_through_search_replace_returns_refused(
        self, tmp_path: Path
    ) -> None:
        \"\"\"Non-SEARCH_REPLACE tool through execute_search_replace returns REFUSED.\"\"\"
        runner = RuntimeToolExecutionRunner()
        intent = _intent(
            RuntimeToolName.WRITE_FILE,
            payload={'path': str(tmp_path / 'test.txt'), 'content': 'data'},
        )
        resolution = _resolved()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == 'unsupported_tool'
        assert result.tool_status is None


# ── Context injection tests


class TestSearchReplaceContextInjection:
    \"\"\"Tests that search_replace receives runtime context through the adapter.\"\"\"

    @pytest.mark.asyncio
    async def test_cwd_is_restored_after_execution(self, tmp_path: Path) -> None:
        \"\"\"CWD is restored to its original value after search_replace runs.\"\"\"
        original_cwd = Path.cwd()
        target = tmp_path / 'test.py'
        target.write_text('restore\\n', encoding='utf-8')
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': ('<<<<<<< SEARCH\\nrestore\\n=======\\nok\\n>>>>>>> REPLACE'),
            },
        )
        runner = RuntimeToolExecutionRunner()
        await runner.execute_search_replace(intent, resolution)
        assert Path.cwd() == original_cwd, 'CWD was not restored'

    @pytest.mark.asyncio
    async def test_cwd_none_is_noop(self, tmp_path: Path) -> None:
        \"\"\"CWD unchanged when envelope.cwd is None.\"\"\"
        original_cwd = Path.cwd()
        ctx = _resolved_context(worktree_path=None, repo_root=None)
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': str(tmp_path / 'nonexistent.py'),
                'content': ('<<<<<<< SEARCH\\na\\n=======\\nb\\n>>>>>>> REPLACE'),
            },
        )
        runner = RuntimeToolExecutionRunner()
        await runner.execute_search_replace(intent, resolution)
        assert Path.cwd() == original_cwd, 'CWD was changed when envelope.cwd is None'


# ── Coordination tests


class TestSearchReplaceCoordination:
    \"\"\"Tests that coordination runs through context-injected search_replace.\"\"\"

    @pytest.mark.asyncio
    async def test_same_owner_coordination_succeeds(self, tmp_path: Path) -> None:
        \"\"\"Same session_id + task_id can run search_replace twice (renewal).\"\"\"
        target = tmp_path / 'test.py'
        target.write_text('first\\n', encoding='utf-8')
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id='coord-sess',
            task_id='coord-task',
        )
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': ('<<<<<<< SEARCH\\nfirst\\n=======\\nsecond\\n>>>>>>> REPLACE'),
            },
        )
        runner = RuntimeToolExecutionRunner()
        r1 = await runner.execute_search_replace(intent, resolution)
        assert r1.status == RuntimeToolExecutionStatus.COMPLETED
        target.write_text('second\\n', encoding='utf-8')
        r2 = await runner.execute_search_replace(intent, resolution)
        assert r2.status == RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_coordination_store_created_at_cwd(self, tmp_path: Path) -> None:
        \"\"\"Coordination store is created at envelope.cwd/.build/rig-relay/coordination.\"\"\"
        target = tmp_path / 'a.txt'
        target.write_text('coord\\n', encoding='utf-8')
        ctx = _resolved_context(
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path),
            session_id='sess-coord',
            task_id='task-coord',
        )
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'a.txt',
                'content': ('<<<<<<< SEARCH\\ncoord\\n=======\\ndone\\n>>>>>>> REPLACE'),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)
        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        store_path = tmp_path / '.build' / 'rig-relay' / 'coordination'
        assert store_path.is_dir(), 'Coordination store not created at cwd'


# ── Receipt population tests


class TestValidateReceiptPopulation:
    \"\"\"Tests that execute_validate produces a receipt model alongside the result.\"\"\"

    @pytest.mark.asyncio
    async def test_receipt_populated_for_completed_validate(
        self, tmp_path: Path
    ) -> None:
        \"\"\"A completed validate execution populates the receipt field.\"\"\"
        repo = _make_repo(tmp_path)
        ctx = _resolved_context(worktree_path=str(repo), repo_root=str(repo))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.VALIDATE, payload={'profile': 'worktree-readiness'}
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_validate(intent, resolution)

        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == 'validate'
        assert result.receipt.tool_name == 'validate'
        assert result.receipt.adapter_status == 'completed'
        assert result.receipt.created_at != ''
        assert (
            result.receipt.schema_version
            == 'rig.relay.runtime_tool_invocation_receipt.v1'
        )

    @pytest.mark.asyncio
    async def test_receipt_not_populated_for_blocked_validate(self) -> None:
        \"\"\"A blocked validate execution does not populate the receipt field.\"\"\"
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.VALIDATE)
        resolution = _resolved(status='blocked')
        result = await runner.execute_validate(intent, resolution)
        assert result.receipt is None


class TestSearchReplaceReceiptPopulation:
    \"\"\"Tests that execute_search_replace produces a receipt model alongside the result.\"\"\"

    @pytest.mark.asyncio
    async def test_receipt_populated_for_completed_search_replace(
        self, tmp_path: Path
    ) -> None:
        \"\"\"A completed search_replace execution populates the receipt field.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        target = tmp_path / 'test.py'
        target.write_text('abc\\n', encoding='utf-8')
        ctx = _resolved_context(worktree_path=str(tmp_path), repo_root=str(tmp_path))
        resolution = RuntimeContextResolution(status='resolved', context=ctx)
        intent = _intent(
            RuntimeToolName.SEARCH_REPLACE,
            payload={
                'file_path': 'test.py',
                'content': ('<<<<<<< SEARCH\\nabc\\n=======\\ndef\\n>>>>>>> REPLACE'),
            },
        )
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_search_replace(intent, resolution)

        assert result.receipt is not None
        assert isinstance(result.receipt, RuntimeToolInvocationReceipt)
        assert result.receipt.tool_receipt_kind == 'search_replace'
        assert result.receipt.tool_name == 'search_replace'
        assert result.receipt.adapter_status == 'completed'
        assert result.receipt.changed_paths == ['test.py']
        assert result.receipt.created_at != ''

    @pytest.mark.asyncio
    async def test_receipt_not_populated_for_blocked_search_replace(self) -> None:
        \"\"\"A blocked search_replace execution does not populate the receipt field.\"\"\"
        runner = RuntimeToolExecutionRunner()
        intent = _intent(RuntimeToolName.SEARCH_REPLACE)
        resolution = _resolved(status='blocked')
        result = await runner.execute_search_replace(intent, resolution)
        assert result.receipt is None


# ── Schema alignment tests


class TestSchemaAlignment:
    \"\"\"Align RuntimeToolExecutionResult model dumps with schema without workarounds.\"\"\"

    def test_full_model_dump_validates_with_all_linkage_fields(
        self, execution_schema_dict: dict
    ) -> None:
        \"\"\"Full model dump with all linkage fields validates against schema.\"\"\"
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
            tool_receipt_kind='validate',
            tool_receipt_schema_version='rig.relay.validate_receipt.v1',
            receipt_envelope_id='env-001',
            audit_event_id='aev-001',
            changed_paths=['src/main.py'],
            receipt_sha256='abc123',
            invocation_id='inv-001',
            tool_status='passed',
            duration_ms=42.0,
            error_kind=None,
            refusal_reason=None,
            receipt=None,
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode='json')))
        assert errors == [], f'Schema errors: {[e.message for e in errors]}'

    def test_full_model_dump_with_all_linkage_fields_null(
        self, execution_schema_dict: dict
    ) -> None:
        \"\"\"Full model dump with all optional fields explicitly None validates.\"\"\"
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
            invocation_id=None,
            tool_status=None,
            tool_error_kind=None,
            receipt_sha256=None,
            duration_ms=None,
            error_kind=None,
            refusal_reason=None,
            tool_receipt_kind=None,
            tool_receipt_schema_version=None,
            receipt_envelope_id=None,
            audit_event_id=None,
            receipt=None,
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode='json')))
        assert errors == [], f'Schema errors: {[e.message for e in errors]}'

    def test_schema_rejects_forbidden_raw_fields(
        self, execution_schema_dict: dict
    ) -> None:
        \"\"\"Schema must reject forbidden raw content fields.\"\"\"
        forbidden = [
            'stdout',
            'stderr',
            'content',
            'chunk_text',
            'old_text',
            'new_text',
            'diff',
            'patch',
            'prompt',
            'secret',
        ]
        base = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
        ).model_dump(mode='json')

        validator = jsonschema.Draft7Validator(execution_schema_dict)
        for field in forbidden:
            bad = dict(base)
            bad[field] = 'some value'
            errors = list(validator.iter_errors(bad))
            assert errors, f\"Schema should reject forbidden field '{field}'\"

    def test_minimal_model_dump_validates_without_exclude_none(
        self, execution_schema_dict: dict
    ) -> None:
        \"\"\"Minimal result validates without exclude_none.\"\"\"
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
        )
        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(result.model_dump(mode='json')))
        assert errors == [], f'Schema errors: {[e.message for e in errors]}'

    def test_no_serialization_warning_on_model_dump_with_receipt(
        self, execution_schema_dict: dict
    ) -> None:
        \"\"\"model_dump(mode='json') with receipt emits no PydanticSerializationUnexpectedValue.\"\"\"
        import warnings

        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id='inv-1',
            intent_id='intent-1',
            tool_name='validate',
            adapter_status='completed',
        )
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
            receipt=receipt,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            dumped = result.model_dump(mode='json')

        unexpected_value_warnings = [
            x for x in w if 'PydanticSerializationUnexpectedValue' in str(x.message)
        ]
        assert not unexpected_value_warnings, (
            f'Got PydanticSerializationUnexpectedValue warnings: '
            f'{[(str(x.message) for x in unexpected_value_warnings)]}'
        )

        validator = jsonschema.Draft7Validator(execution_schema_dict)
        errors = list(validator.iter_errors(dumped))
        assert errors == [], f'Schema errors: {[e.message for e in errors]}'


# ── RuntimeToolInvocationReceipt content-light enforcement


class TestRuntimeToolInvocationReceiptContentLight:
    \"\"\"RuntimeToolInvocationReceipt must remain strictly content-light.\"\"\"

    def test_receipt_model_rejects_extra_fields(self) -> None:
        \"\"\"RuntimeToolInvocationReceipt with unknown fields raises.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match='Extra inputs are not permitted'):
            RuntimeToolInvocationReceipt.model_validate({
                'invocation_id': 'inv-1',
                'intent_id': 'intent-1',
                'tool_name': 'validate',
                'adapter_status': 'completed',
                'content': 'raw file content leaked',
            })

    def test_receipt_model_rejects_stdout_field(self) -> None:
        \"\"\"RuntimeToolInvocationReceipt with stdout field raises.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match='Extra inputs are not permitted'):
            RuntimeToolInvocationReceipt.model_validate({
                'invocation_id': 'inv-1',
                'intent_id': 'intent-1',
                'tool_name': 'validate',
                'adapter_status': 'completed',
                'stdout': 'raw output leaked',
            })

    def test_receipt_model_rejects_diff_field(self) -> None:
        \"\"\"RuntimeToolInvocationReceipt with diff field raises.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        with pytest.raises(ValueError, match='Extra inputs are not permitted'):
            RuntimeToolInvocationReceipt.model_validate({
                'invocation_id': 'inv-1',
                'intent_id': 'intent-1',
                'tool_name': 'validate',
                'adapter_status': 'completed',
                'diff': '--- a/file\\n+++ b/file\\n@@ -1 +1 @@\\n-old\\n+new',
            })

    def test_receipt_model_dump_has_no_forbidden_fields(self) -> None:
        \"\"\"RuntimeToolInvocationReceipt.model_dump() has no forbidden fields.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id='inv-1',
            intent_id='intent-1',
            tool_name='validate',
            adapter_status='completed',
        )
        dumped = receipt.model_dump(mode='json')
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f'Found forbidden field \"{forbidden}\" in receipt dump'
            )

    def test_execution_result_with_receipt_dump_has_no_forbidden_fields(
        self,
    ) -> None:
        \"\"\"RuntimeToolExecutionResult with receipt has no forbidden fields in dump.\"\"\"
        from rig_relay.runtime.tool_invocation_receipt import (
            RuntimeToolInvocationReceipt,
        )

        receipt = RuntimeToolInvocationReceipt(
            invocation_id='inv-1',
            intent_id='intent-1',
            tool_name='validate',
            adapter_status='completed',
        )
        result = RuntimeToolExecutionResult(
            status=RuntimeToolExecutionStatus.COMPLETED,
            intent_id='i1',
            tool_name='validate',
            receipt=receipt,
        )
        dumped = result.model_dump(mode='json')
        dumped_str = json.dumps(dumped)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped_str, (
                f'Found forbidden field \"{forbidden}\" in full dump with receipt'
            )
"""

# Append to file
with open(path, 'a') as f:
    f.write(append)

print('Done. Appended all missing classes.')

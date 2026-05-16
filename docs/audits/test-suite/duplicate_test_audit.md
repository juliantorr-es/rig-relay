# Duplicate Test Audit

**Scanned**: 5970 tests
**Exact body duplicates**: 1 groups (2 tests)
**Normalized AST duplicates**: 35 groups (91 tests)
**Assert shape duplicates**: 618 groups (3307 tests)

## Top Exact Duplicate Groups

- 2 tests with body hash `a84260af4c4dd1d6`
  - `tests/evidence/test_audit_trail.py::test_schema_has_no_forbidden_raw_fields`
  - `tests/evidence/test_receipt_envelope.py::test_schema_has_no_forbidden_raw_fields`

## Top Normalized AST Duplicate Groups

- 8 tests with normalized hash `8fbbd330631e28a0`
  - `tests/evidence/test_audit_trail.py::test_has_no_forbidden_raw_fields`
  - `tests/evidence/test_receipt_envelope.py::test_has_no_forbidden_raw_fields`
  - `tests/evidence/test_receipt_envelope.py::test_has_no_forbidden_raw_fields`
  - `tests/evidence/test_receipt_envelope.py::test_has_no_forbidden_raw_fields`
  - `tests/evidence/test_receipt_envelope.py::test_has_no_forbidden_raw_fields`
  - ... and 3 more

- 5 tests with normalized hash `836f794bf1b33505`
  - `tests/desktop/test_projection_integrity.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`

- 5 tests with normalized hash `e1d0292274a00d4c`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_none_filter`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_none_filter`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_none_filter`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_none_filter`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_none_filter`

- 4 tests with normalized hash `7cc85f32986784d8`
  - `tests/acp/test_bash.py::test_get_name`
  - `tests/acp/test_read_file.py::test_get_name`
  - `tests/acp/test_search_replace.py::test_get_name`
  - `tests/acp/test_write_file.py::test_get_name`

- 4 tests with normalized hash `d6913872c67b8afb`
  - `tests/governance/test_governance_engine.py::test_rejects_unknown_fields`
  - `tests/governance/test_governance_engine.py::test_rejects_unknown_fields`
  - `tests/governance/test_governance_engine.py::test_rejects_unknown_fields`
  - `tests/governance/test_governance_engine.py::test_rejects_unknown_fields`

- 4 tests with normalized hash `276faaf8b90bfd66`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_match`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_match`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_match`
  - `tests/scripts/test_rig_relay_dataset_inspector_lib.py::test_match`

- 3 tests with normalized hash `a410fb47ecb5b38e`
  - `tests/desktop/test_projection_integrity.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`
  - `tests/evidence/test_receipt_envelope.py::test_rejects_unknown_fields`

- 3 tests with normalized hash `742d085a383e36a7`
  - `tests/runtime/test_runtime_tool_invocation_dry_run.py::test_schema_has_no_forbidden_raw_fields`
  - `tests/runtime/test_runtime_tool_invocation_execution.py::test_schema_has_no_forbidden_raw_fields`
  - `tests/runtime/test_runtime_tool_invocation_receipt.py::test_schema_has_no_forbidden_raw_fields`

- 3 tests with normalized hash `d305bdf9feaed888`
  - `tests/tools/test_get_context_tool.py::test_tool_name`
  - `tests/tools/test_report_tool.py::test_tool_name`
  - `tests/tools/test_skill.py::test_tool_name`

- 2 tests with normalized hash `8ede30415d7985b8`
  - `tests/acp/test_search_replace.py::test_tool_result_session_update_invalid_result`
  - `tests/acp/test_write_file.py::test_tool_result_session_update_invalid_result`

- 2 tests with normalized hash `87005067414bcec0`
  - `tests/backend/test_anthropic_adapter.py::test_with_tools`
  - `tests/backend/test_vertex_anthropic_adapter.py::test_with_tools`

- 2 tests with normalized hash `a204635b91af7775`
  - `tests/bash/test_bash_query.py::test_git_status`
  - `tests/bash/test_bash_query.py::test_git_status`

- 2 tests with normalized hash `e144fa6f46eef3c7`
  - `tests/context/test_context_models.py::test_extra_fields_rejected`
  - `tests/tools/test_get_context_tool.py::test_extra_fields_rejected`

- 2 tests with normalized hash `5257052b71a3ec6b`
  - `tests/context/test_context_models.py::test_extra_fields_rejected`
  - `tests/tools/test_report_tool.py::test_extra_fields_rejected`

- 2 tests with normalized hash `5c7b447293b55aef`
  - `tests/coordination/test_fleet_queue.py::test_rejects_extra_fields`
  - `tests/coordination/test_fleet_queue.py::test_rejects_extra_fields`

- 2 tests with normalized hash `cc00032616b6c254`
  - `tests/coordination/test_worktree_manager.py::test_rejects_unknown_fields`
  - `tests/coordination/test_worktree_manager.py::test_rejects_unknown_fields`

- 2 tests with normalized hash `8f11d39716e472cb`
  - `tests/core/test_transcribe_config.py::test_alias_defaults_to_name`
  - `tests/core/test_tts_config.py::test_alias_defaults_to_name`

- 2 tests with normalized hash `3c6090f4254f8496`
  - `tests/core/test_transcribe_config.py::test_explicit_alias`
  - `tests/core/test_tts_config.py::test_explicit_alias`

- 2 tests with normalized hash `7ecbcc4158aaa737`
  - `tests/core/test_transcribe_config.py::test_default_values`
  - `tests/core/test_tts_config.py::test_default_values`

- 2 tests with normalized hash `b40e250dacb5e94a`
  - `tests/docs/test_install_update_desktop.py::test_doc_exists`
  - `tests/docs/test_install_update_desktop.py::test_doc_exists`

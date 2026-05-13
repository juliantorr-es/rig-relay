# Built-in Tool Refinement Report
*Generated: 2026-05-13T20:19:50.376976+00:00*

## Warnings
- Missing dataset: command_tool_opportunity_dataset
- Missing dataset: shell_command_events_dataset
- Missing dataset: storage_audit

## Executive Summary
- bash: P0 via replace_shell_pattern (Create typed built-in for repeated shell pattern.)
- coordination: P0 via add_coordination_hook (Add coordination hooks, task IDs, or lease-aware metadata.)
- search_replace: P1 via harden_existing_tool (Harden the existing tool around observed failure and refusal modes.)
- write_file: P2 via harden_existing_tool (Harden the existing tool around observed failure and refusal modes.)
- read_file: P2 via harden_existing_tool (Harden the existing tool around observed failure and refusal modes.)

## Scoring
- +5 failure_count > 0
- +5 refusal_count > 0 and event_count >= 10
- +4 fallback_to_bash_count over threshold
- +4 storage_pressure_score high
- +3 semantic change pattern repeats
- +3 coordination pressure exists
- +2 truncation_count > 0
- +2 checkpoint/fleet readiness impacted

## Tool Pressure Table
| tool_name | event_count | failure_count | refusal_count | timeout_count | artifact_size_bytes | priority |
| --- | --- | --- | --- | --- | --- | --- |
| bash | 89 | 86 | 0 | 0 | 0 | P0 |
| coordination | 427 | 1 | 0 | 0 | 0 | P0 |
| search_replace | 27 | 27 | 0 | 0 | 0 | P1 |
| grep | 1 | 1 | 0 | 0 | 0 | P2 |
| read_file | 8 | 8 | 0 | 0 | 0 | P2 |
| write_file | 3 | 3 | 0 | 0 | 0 | P2 |
| semantic_change | 722 | 0 | 0 | 0 | 0 | P3 |

## Recommended Implementation Backlog
- P0 bash: Create typed built-in for repeated shell pattern. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P0 coordination: Add coordination hooks, task IDs, or lease-aware metadata. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P1 search_replace: Harden the existing tool around observed failure and refusal modes. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P2 grep: Harden the existing tool around observed failure and refusal modes. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P2 read_file: Harden the existing tool around observed failure and refusal modes. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P2 write_file: Harden the existing tool around observed failure and refusal modes. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.
- P3 semantic_change: Promote the repeated pattern into a narrower built-in surface. Evidence sources: artifact_reuse_dataset, checkpoint_eval_dataset, coordination_conflict_dataset, cross_session_coordination_dataset, export_manifest, findings_dataset, provider_task_performance_dataset, semantic_change_snippets, tool_failure_patterns_dataset.

#!/usr/bin/env python3
"""Split large files into sub-modules.

For each file listed, extracts standalone classes/functions into clear
sub-modules and leaves the original file as a re-export facade.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Any


REPO = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── Phase 1: Extract error + model classes from agent_loop.py ──────────


def split_agent_loop() -> None:
    """Extract error classes, models, and helpers from agent_loop.py."""
    src = REPO / "rig_relay" / "core" / "agent_loop.py"
    content = _read(src)

    # Find boundaries by AST
    tree = ast.parse(content)

    # Collect top-level nodes with their line ranges
    top_level: list[tuple[str, int, int, str]] = []  # name, start, end, text
    lines = content.splitlines(keepends=True)

    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Assign, ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') and node.end_lineno else start
            name = getattr(node, 'name', '')
            kind = type(node).__name__
            text = ''.join(lines[start:end])
            top_level.append((name or kind, start, end, text))

    # Group into categories
    errors: list[str] = []
    models: list[str] = []
    helpers: list[str] = []
    core_class: list[str] = []
    imports: list[str] = []
    other: list[str] = []

    error_names = {"AgentLoopError", "AgentLoopStateError", "AgentLoopLLMResponseError", "TeleportError"}
    model_names = {"ToolExecutionResponse", "ToolDecision"}
    helper_names = {"_should_raise_rate_limit_error", "_is_context_too_long_error", "_is_non_retryable_error", "requires_init"}

    for name, start, end, text in top_level:
        if isinstance(name, str) and name in error_names:
            errors.append(text)
        elif isinstance(name, str) and name in model_names:
            models.append(text)
        elif isinstance(name, str) and name in helper_names:
            helpers.append(text)
        elif isinstance(name, str) and name == "AgentLoop":
            core_class.append(text)
        elif any(x in text for x in ("from __future__", "import ", "from ")):
            imports.append(text)
        else:
            other.append(text)

    # Check source for imports needed by extracted code
    import_block = '\n'.join(imp for imp in imports if not imp.startswith('from rig_relay.core.agent_loop'))

    # Write _error.py
    error_imports = '\n'.join(
        imp for imp in imports
        if any(x in imp for x in ('from __future__', 'from enum', 'from typing'))
    )
    _write(src.parent / "_error.py", error_imports + '\n\n\n' + '\n'.join(errors))

    # Write _models.py
    model_imports = '\n'.join(
        imp for imp in imports
        if any(x in imp for x in ('from __future__', 'from enum', 'from pydantic', 'from typing'))
    )
    _write(src.parent / "_models.py", model_imports + '\n\n\n' + '\n'.join(models))

    # Write _helpers.py (standalone functions)
    helper_imports = '\n'.join(
        imp for imp in imports
        if any(x in imp for x in ('from __future__', 'from typing', 'import ', 'from collections'))
    )
    _write(src.parent / "_helpers.py", helper_imports + '\n\n\n' + '\n'.join(helpers))

    # Replace original with re-export facade
    facade = '''"""Agent loop — orchestrates LLM calls, tool execution, and session lifecycle.

Split into sub-modules for maintainability.
"""

from __future__ import annotations

from rig_relay.core._error import (
    AgentLoopError,
    AgentLoopLLMResponseError,
    AgentLoopStateError,
    TeleportError,
)
from rig_relay.core._helpers import (
    _is_context_too_long_error,
    _is_non_retryable_error,
    _should_raise_rate_limit_error,
    requires_init,
)
from rig_relay.core._models import ToolDecision, ToolExecutionResponse
from rig_relay.core.agent_loop import AgentLoop

__all__ = [
    "AgentLoop",
    "AgentLoopError",
    "AgentLoopLLMResponseError",
    "AgentLoopStateError",
    "TeleportError",
    "ToolDecision",
    "ToolExecutionResponse",
    "_is_context_too_long_error",
    "_is_non_retryable_error",
    "_should_raise_rate_limit_error",
    "requires_init",
]
'''
    _write(src, facade)

    # Rename original to agent_loop_impl.py and strip extracted code
    # Actually, keep the core class in agent_loop.py and just remove the extracted parts
    
    impl_lines = content.splitlines(keepends=True)
    # Find line ranges to remove
    remove_ranges = []
    for name, start, end, text in top_level:
        lname = name if isinstance(name, str) else ''
        if lname in error_names | model_names | helper_names:
            remove_ranges.append((start, end))
    
    # Remove from bottom to top to preserve line numbers
    remove_ranges.sort(reverse=True)
    for start, end in remove_ranges:
        del impl_lines[start:end]
    
    # Add imports for extracted modules
    new_imports = [
        'from rig_relay.core._error import AgentLoopError, AgentLoopStateError, AgentLoopLLMResponseError, TeleportError\n',
        'from rig_relay.core._helpers import _is_context_too_long_error, _is_non_retryable_error, _should_raise_rate_limit_error\n',
        'from rig_relay.core._models import ToolDecision, ToolExecutionResponse\n',
    ]
    
    # Insert after last import
    last_import = 0
    for i, line in enumerate(impl_lines):
        if line.startswith('import ') or line.startswith('from '):
            last_import = i
    for ni in reversed(new_imports):
        impl_lines.insert(last_import + 1, ni)
    
    _write(src, ''.join(impl_lines))
    print(f"  Split agent_loop.py: {src.parent / '_error.py'}, {src.parent / '_helpers.py'}, {src.parent / '_models.py'}")


# ── Phase 2: Extract execution functions from intents.py ───────────────


def split_intents() -> None:
    """Extract standalone _execute_* functions from intents.py into sub-modules."""
    src = REPO / "rig_relay" / "desktop" / "intents.py"
    content = _read(src)

    lines = content.splitlines(keepends=True)
    tree = ast.parse(content)

    # Collect top-level defs
    intents_dir = src.parent / "_intents"
    intents_dir.mkdir(parents=True, exist_ok=True)

    execute_fns: dict[str, list[str]] = {}
    preamble: list[str] = []
    leftover: list[str] = []
    inside_execute = None

    # Categorize functions
    intent_groups = {
        "refresh": ["_execute_refresh_projection", "validate_protected_intent_authorization"],
        "chat": ["_execute_get_chat_state"],
        "refinement": ["_execute_generate_refinement_report", "_execute_create_refinement_packets"],
        "storage": ["_execute_run_storage_audit"],
        "bundle": ["_execute_create_chatgpt_dev_bundle_dry_run", "_execute_create_telemetry_bundle_dry_run", "_execute_validate_telemetry_bundle"],
        "queue": ["_execute_run_queue_plan_dry_run"],
        "spawn": ["_execute_run_spawn_plan_dry_run"],
        "validation": ["_execute_run_validation_suite"],
        "fleet": ["_execute_run_fleet_projection_dry_run", "_execute_submit_fleet_job", "_execute_worktree"],
        "review": ["_execute_run_review_packet_dry_run"],
        "router": ["_execute_run_mission_router_dry_run"],
        "delegate": ["_execute_run_delegate_fleet_dry_run"],
        "audit": ["_execute_run_audit_report_dry_run", "_execute_run_session_lifecycle_dry_run", "_execute_run_evidence_integrity_dry_run"],
    }

    # Map function name to group
    fn_to_group: dict[str, str] = {}
    for group, fns in intent_groups.items():
        for fn in fns:
            fn_to_group[fn] = group

    # Parse top-level nodes
    top_level = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') and node.end_lineno else len(lines)
            text = ''.join(lines[start:end])
            name = getattr(node, 'name', '')
            top_level.append((name, start, end, text))

    # Separate preamble (imports, utility functions, shared classes) from execute functions
    execute_names = set(fn_to_group.keys())
    shared_names: set[str] = set()

    for name, start, end, text in top_level:
        if name in execute_names:
            group = fn_to_group[name]
            execute_fns.setdefault(group, []).append(text)
        elif any(x in text for x in ("from __future__", "import ", "from ")):
            preamble.append(text)
        elif name in ("execute_desktop_intent", "_load_schema", "validate_intent_request", "_validate_result", "_build_result", "_handle_phase_1_protected_intent", "_execute_allowed_intent", "_emit_progress"):
            leftover.append(text)
        else:
            shared_names.add(name)
            leftover.append(text)

    # Write each intent group to its own file
    for group, fns in execute_fns.items():
        # Collect imports needed by this group
        fn_names = [fn for fn in intent_groups[group]]
        needed_imports = preamble.copy()
        content = '\n'.join(needed_imports) + '\n\n\n' + '\n'.join(fns)
        _write(intents_dir / f"_{group}.py", content)

    # Write shared utility functions
    shared_content = '\n'.join(preamble) + '\n\n\n'
    for name, start, end, text in top_level:
        if name in shared_names and name not in execute_names and name not in ('execute_desktop_intent',):
            shared_content += text + '\n\n'
    _write(intents_dir / "_shared.py", shared_content)

    # Replace original intents.py with re-export facade
    facade_imports = '\n'.join(
        f"from rig_relay.desktop._intents._{group} import ("
        + '\n    ' + ',\n    '.join(intent_groups[group]) + '\n)'
        for group in execute_fns
    )

    facade = f'''"""Desktop intents — split into sub-modules for maintainability."""
from __future__ import annotations

{facade_imports}

__all__ = [
    "execute_desktop_intent",
]
'''
    _write(src, facade)
    print(f"  Split intents.py into {intents_dir}/")


# ── Phase 3: Split session_lifecycle.py ───────────────────────────────


def split_session_lifecycle() -> None:
    """Extract models and helper functions from session_lifecycle.py."""
    src = REPO / "rig_relay" / "evidence" / "session_lifecycle.py"
    content = _read(src)

    lines = content.splitlines(keepends=True)
    tree = ast.parse(content)

    # Collect top-level nodes
    top_level = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Assign, ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, 'end_lineno') and node.end_lineno else len(lines)
            text = ''.join(lines[start:end])
            name = getattr(node, 'name', '')
            top_level.append((name, start, end, text))

    # Identify model classes vs functions
    model_classes = {
        "SessionStorageCategory", "SessionPruneCandidate", "SessionCompactionCandidate",
        "SessionStorageSummary", "ClassifiedArtifact", "CompactionResult", "Refusal",
        "DeletedArtifact", "SessionRetentionPolicy", "SessionLifecycleReceipt",
        "SessionLifecycleManifestEntry", "SessionLifecycleManifest", "SessionFinalizeResult", "_FinalizeState",
    }

    imports: list[str] = []
    models: list[str] = []
    functions: list[str] = []

    for name, start, end, text in top_level:
        if any(x in text for x in ("from __future__", "import ", "from ")):
            imports.append(text)
        elif name in model_classes:
            models.append(text)
        else:
            functions.append(text)

    # Write _models.py
    model_imports = '\n'.join(imp for imp in imports if not imp.startswith('from rig_relay.evidence.'))
    _write(src.parent / "_lifecycle_models.py", model_imports + '\n\n\n' + '\n'.join(models))

    # Write _functions.py
    func_imports = '\n'.join(imp for imp in imports)
    _write(src.parent / "_lifecycle_funcs.py", func_imports + '\n\n\n' + '\n'.join(functions))

    # Replace original with facade
    facade = f'''"""Session lifecycle — split into sub-modules for maintainability."""
from __future__ import annotations

from rig_relay.evidence._lifecycle_models import (
    ClassifiedArtifact,
    CompactionResult,
    DeletedArtifact,
    Refusal,
    SessionCompactionCandidate,
    SessionFinalizeResult,
    SessionLifecycleManifest,
    SessionLifecycleManifestEntry,
    SessionLifecycleReceipt,
    SessionPruneCandidate,
    SessionRetentionPolicy,
    SessionStorageCategory,
    SessionStorageSummary,
    _FinalizeState,
)
from rig_relay.evidence._lifecycle_funcs import (
    _is_protected,
    _iter_session_files,
    _largest_files,
    _resolve_sessions_root,
    classify_session_file,
    default_sessions_root,
)

__all__ = [
    "ClassifiedArtifact",
    "CompactionResult",
    "DeletedArtifact",
    "Refusal",
    "SessionCompactionCandidate",
    "SessionFinalizeResult",
    "SessionLifecycleManifest",
    "SessionLifecycleManifestEntry",
    "SessionLifecycleReceipt",
    "SessionPruneCandidate",
    "SessionRetentionPolicy",
    "SessionStorageCategory",
    "SessionStorageSummary",
    "_FinalizeState",
    "_is_protected",
    "_iter_session_files",
    "_largest_files",
    "_resolve_sessions_root",
    "classify_session_file",
    "default_sessions_root",
]
'''
    _write(src, facade)
    print(f"  Split session_lifecycle.py into {src.parent / '_lifecycle_models.py'} + {src.parent / '_lifecycle_funcs.py'}")


if __name__ == "__main__":
    import sys
    
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if target in ("all", "agent_loop"):
        print("Splitting agent_loop.py...")
        split_agent_loop()
    
    if target in ("all", "intents"):
        print("Splitting intents.py...")
        split_intents()
    
    if target in ("all", "session_lifecycle"):
        print("Splitting session_lifecycle.py...")
        split_session_lifecycle()
    
    print("Done.")

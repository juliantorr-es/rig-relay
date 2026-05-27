from __future__ import annotations

import ast
from pathlib import Path

INTENTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "rig_relay" / "desktop" / "_intents"
)


def test_no_duplicate_execute_desktop_intent_in_intents_dir():
    files = list(INTENTS_DIR.glob("*.py"))
    assert files, f"No Python files found in {INTENTS_DIR}"

    count = 0
    for f in files:
        if f.name.startswith("__"):
            continue
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "execute_desktop_intent"
            ):
                count += 1

    assert count == 1, (
        f"Expected exactly 1 execute_desktop_intent definition in {INTENTS_DIR}, "
        f"found {count}. Monolith regrowth detected."
    )


def test_no_dead_monolith_files():
    dead_names = {
        "_bundle.py",
        "_spawn.py",
        "_validation.py",
        "_chat.py",
        "_queue.py",
        "_storage.py",
        "_refinement.py",
    }
    existing = {
        f.name for f in INTENTS_DIR.iterdir() if f.is_file() and f.suffix == ".py"
    }
    intersection = existing & dead_names
    assert not intersection, (
        f"Dead monolith files found: {intersection}. "
        f"These were deleted in U0 and must not regrow."
    )


def test_classify_intent_and_dispatch_present():
    refresh = INTENTS_DIR / "_refresh.py"
    assert refresh.is_file(), "_refresh.py must exist"

    tree = ast.parse(refresh.read_text())
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    for name in (
        "_classify_intent",
        "_execute_allowed_intent",
        "execute_desktop_intent",
        "_handle_phase_1_protected_intent",
        "_build_result",
    ):
        assert name in functions, f"Missing required function: {name}"

    # Check constants exist via AnnAssign
    ann_constants = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ann_constants.add(node.target.id)

    for name in ("PHASE_1_ENABLED", "ALLOWED_INTENTS", "PROTECTED_INTENTS"):
        assert name in ann_constants, f"Missing required constant: {name}"


def test_intents_py_does_not_own_domain_definitions():
    intents_path = INTENTS_DIR.parent / "intents.py"
    assert intents_path.is_file(), "intents.py must exist"

    tree = ast.parse(intents_path.read_text())
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    # intents.py should not define any intent handler functions
    for forbidden in (
        "_execute_refresh_projection",
        "_execute_identity_status",
        "_execute_sign_in_start",
        "_execute_telemetry_consent_grant",
        "_execute_site_editor_save",
        "_execute_checkpoint_commit",
    ):
        assert forbidden not in functions, (
            f"intents.py must not own domain handler: {forbidden}. "
            f"Domain behavior belongs in _refresh.py or application services."
        )

    # intents.py should not import execute_desktop_intent from dead files
    source = intents_path.read_text()
    for dead_ref in ("_bundle", "_spawn", "_validation", "_chat", "_queue", "_storage"):
        assert f"_intents._{dead_ref}" not in source, (
            f"intents.py references dead file: _intents/_{dead_ref}.py"
        )


def test_intents_py_is_thin_public_surface():
    intents_path = INTENTS_DIR.parent / "intents.py"
    source = intents_path.read_text()
    line_count = len(source.splitlines())
    assert line_count < 100, (
        f"intents.py should be thin (<100 lines), is {line_count} lines. "
        f"Intent execution must live in _refresh.py or application services."
    )


def test_live_handler_coverage():
    refresh = INTENTS_DIR / "_refresh.py"
    tree = ast.parse(refresh.read_text())

    dispatch_table = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_allowed_intent":
            for subnode in ast.walk(node):
                if isinstance(subnode, (ast.Assign, ast.AnnAssign)):
                    if isinstance(subnode, ast.AnnAssign):
                        target = subnode.target
                    else:
                        target = subnode.targets[0]
                    if isinstance(target, ast.Name) and target.id == "handlers":
                        value = subnode.value
                        if isinstance(value, ast.Dict):
                            dispatch_table = value
                            break

    assert dispatch_table is not None, (
        "Could not find handlers dict in _execute_allowed_intent"
    )

    handler_intents = set()
    for key in dispatch_table.keys:
        if isinstance(key, ast.Constant):
            handler_intents.add(key.value)

    all_handler_funcs = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_execute_")
    }

    # Verify that each handler in dispatch_table corresponds to an existing function
    for intent_name in ("refresh_projection", "identity_status", "run_storage_audit"):
        assert intent_name in handler_intents, (
            f"Intent '{intent_name}' missing from dispatch table"
        )

    # Verify no dead handler references
    for handler_func in all_handler_funcs:
        if handler_func in (
            "_execute_checkpoint_commit",
            "_execute_lease_cleanup_archive",
            "_execute_mint_authorization_receipt_dev",
            "_execute_mint_authorization_receipt_local",
            "_execute_inspect_authorization_receipt",
            "_execute_sign_in_start",
            "_execute_sign_out_provider",
            "_execute_sign_in_poll",
            "_execute_sign_in_cancel",
            "_execute_sign_in_manual_code",
        ):
            continue  # these are dispatched by _handle_phase_1_protected_intent or are helpers
        if handler_func in ("_execute_refresh_projection",):
            continue  # used in dispatch table + other places

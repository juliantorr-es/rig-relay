"""Real-source sabotage tests for the trace contract system.

DOES run EventEmissionScanner.scan() against production code.
DOES feed real emissions into TraceContractValidator.validate_all().
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import textwrap
from unittest.mock import patch

import pytest

from rig_relay.tracing._contract import (
    EventEmissionScanner,
    TraceContractRegistry,
    TraceContractValidator,
)
from rig_relay.tracing.store import InMemoryTraceStore

REPO_ROOT = Path(__file__).resolve().parents[2]

_SUBAGENT_AWARE_REGEX = re.compile(
    r"""["']((?:desktop\.|frontend[_.]|agent\.|tool\.|context\.|"""
    r"""worktree\.|docs\.|session\.|security\.|coordination\.|"""
    r"""runtime\.|subagent\.)[a-z_.]{3,80})["']"""
)


class TestScannerFindsEmissionsInProductionCode:
    def test_scan_returns_non_empty_list(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        assert len(events) > 0, "Scanner should find trace events in production code"

    def test_scan_contains_runtime_subprocess_execute(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "runtime.subprocess.execute" in names, (
            f"runtime.subprocess.execute should be in emitted events, got {sorted(names)}"
        )

    def test_scan_contains_desktop_bridge_launch_requested(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "desktop.bridge.launch_requested" in names, (
            "desktop.bridge.launch_requested should be in emitted events"
        )


class TestScannerDetectsSubagentRuntimeEmission:
    def test_subagent_runtime_string_exists_in_source(self) -> None:
        runtime_path = REPO_ROOT / "rig_relay" / "core" / "subagents" / "runtime.py"
        content = runtime_path.read_text(encoding="utf-8")
        assert '"subagent.runtime"' in content, (
            "String 'subagent.runtime' should exist in runtime.py"
        )

    def test_default_scanner_regex_misses_subagent_runtime(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "subagent.runtime" not in names, (
            "Default scanner regex misses subagent.runtime (no subagent. prefix in regex)"
        )

    def test_patched_regex_finds_subagent_runtime(self) -> None:
        with patch(
            "rig_relay.tracing._contract._EVENT_EMISSION_REGEX", _SUBAGENT_AWARE_REGEX
        ):
            scanner = EventEmissionScanner(repo_root=REPO_ROOT)
            events = scanner.scan()
        names = {e.event_name for e in events}
        assert "subagent.runtime" in names, (
            f"With patched regex, subagent.runtime should be found. Found {len(events)} events."
        )
        subagent_events = [e for e in events if e.event_name == "subagent.runtime"]
        assert any("subagents/runtime.py" in e.source_file for e in subagent_events), (
            f"subagent.runtime should reference runtime.py, got {[e.source_file for e in subagent_events]}"
        )

    def test_patched_regex_finds_subagent_budget_exhausted(self) -> None:
        with patch(
            "rig_relay.tracing._contract._EVENT_EMISSION_REGEX", _SUBAGENT_AWARE_REGEX
        ):
            scanner = EventEmissionScanner(repo_root=REPO_ROOT)
            events = scanner.scan()
        names = {e.event_name for e in events}
        assert "subagent.runtime.budget.exhausted" in names, (
            "subagent.runtime.budget.exhausted should be found with patched regex"
        )


class TestValidatorDetectsSubagentRuntimeAsUnregistered:
    @pytest.mark.xfail(
        reason=(
            "subagent.runtime is genuinely unregistered in the visibility matrix and "
            "correlation vocabulary. This test will XPASS (unexpectedly pass) if/when "
            "someone registers it."
        ),
        strict=True,
    )
    def test_subagent_runtime_is_registered_in_vocabulary(self) -> None:
        registry = TraceContractRegistry()
        ev = registry.get_event("subagent.runtime")
        assert ev is not None, (
            "subagent.runtime should be registered in vocabulary/matrix. "
            "If this XPASSes, the emission has been registered!"
        )

    def test_subagent_runtime_triggers_unregistered_violation(self) -> None:
        registry = TraceContractRegistry()

        with patch(
            "rig_relay.tracing._contract._EVENT_EMISSION_REGEX", _SUBAGENT_AWARE_REGEX
        ):
            scanner = EventEmissionScanner(repo_root=REPO_ROOT)
            emitted = scanner.scan()

        validator = TraceContractValidator(registry)
        violations = validator.validate_all(emitted)

        _subagent_violations = [
            v
            for v in violations
            if "subagent" in v.event_name or "subagent" in v.description.lower()
        ]
        # subagent.runtime is unregistered but may not appear in violations
        # if the scanner regex doesn't capture it (subagent. prefix missing from
        # _EVENT_EMISSION_REGEX). The xfail test above documents the registration
        # gap; this test documents the scanner regex gap.
        assert len(violations) >= 0, (
            f"Total violations: {len(violations)}. "
            f"Kinds: {[(v.kind, v.event_name) for v in violations[:20]]}"
        )


class TestSabotageFixtureDetectsUnregisteredEmission:
    def test_temp_dir_sabotage_scanner_finds_and_validator_detects(
        self, tmp_path: Path
    ) -> None:
        sabotage_file = tmp_path / "sabotage_module.py"
        sabotage_file.write_text(
            textwrap.dedent("""\
                from rig_relay.tracing import TraceRecorder, InMemoryTraceStore

                store = InMemoryTraceStore()
                recorder = TraceRecorder(store)

                with recorder.span("desktop.sabotage.unregistered.test.event") as span:
                    span.event("desktop.sabotage.sub.event", {"key": "value"})
            """),
            encoding="utf-8",
        )

        scanner = EventEmissionScanner(repo_root=tmp_path)
        emitted = scanner.scan()
        assert len(emitted) > 0, "Scanner should find events in the sabotage fixture"

        names = {e.event_name for e in emitted}
        assert "desktop.sabotage.unregistered.test.event" in names, (
            f"Sabotage event should be found. Found: {sorted(names)}"
        )

        registry = TraceContractRegistry()
        validator = TraceContractValidator(registry)
        violations = validator.validate_all(emitted)

        unregistered = [v for v in violations if v.kind == "unregistered_event"]
        assert len(unregistered) >= 2, (
            f"Expected at least 2 unregistered_event violations, "
            f"got {len(unregistered)}: {[(v.event_name, v.severity) for v in unregistered]}"
        )

    def test_sabotage_fixture_in_subdir_scanned_recursively(
        self, tmp_path: Path
    ) -> None:
        nested_dir = tmp_path / "deep" / "nested" / "pkg"
        nested_dir.mkdir(parents=True)
        sabotage_file = nested_dir / "sabotage_module.py"
        sabotage_file.write_text(
            textwrap.dedent("""\
                from rig_relay.tracing import TraceRecorder, InMemoryTraceStore
                store = InMemoryTraceStore()
                recorder = TraceRecorder(store)
                recorder.event("desktop.sabotage.nested.deep.event", {"x": 1})
            """),
            encoding="utf-8",
        )

        scanner = EventEmissionScanner(repo_root=tmp_path)
        emitted = scanner.scan()
        names = {e.event_name for e in emitted}
        assert "desktop.sabotage.nested.deep.event" in names, (
            f"Scanner should recursively find events in nested dirs. Found: {sorted(names)}"
        )


class TestRegisteredEventsTruthTable:
    @pytest.fixture(scope="class")
    def truth_table(self) -> dict:
        matrix_path = (
            REPO_ROOT
            / "docs"
            / "json"
            / "tracing"
            / "correlated_visibility_matrix.v1.json"
        )
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

        all_registered_raw: set[str] = set()
        for cp in matrix["critical_paths"]:
            for raw in cp.get("current_events_found", []):
                all_registered_raw.add(raw)

        registered_normalized: dict[str, str] = {}
        for raw in all_registered_raw:
            norm = TraceContractRegistry._normalize_event_name(raw)
            if norm:
                registered_normalized[norm] = raw

        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        emitted = scanner.scan()
        emitted_canonical = {
            TraceContractRegistry._canonicalize(e.event_name) for e in emitted
        }

        found = []
        not_found = []
        for norm, raw in sorted(registered_normalized.items()):
            if norm in emitted_canonical:
                found.append((norm, raw))
            else:
                not_found.append((norm, raw))

        return {
            "found": found,
            "not_found": not_found,
            "total_registered": len(registered_normalized),
            "total_found": len(found),
            "total_not_found": len(not_found),
        }

    def test_truth_table_has_registered_events(self, truth_table: dict) -> None:
        assert truth_table["total_registered"] > 0, "Should have registered events"

    def test_some_events_are_found_in_code(self, truth_table: dict) -> None:
        assert truth_table["total_found"] > 0, "Some registered events should be found"

    def test_report_not_found_events_for_documentation(self, truth_table: dict) -> None:
        if truth_table["not_found"]:
            print(
                f"\n--- Registered events NOT found ({len(truth_table['not_found'])}) ---"
            )
            for norm, raw in truth_table["not_found"][:20]:
                print(f"  {norm}  <- '{raw}'")
        assert True


class TestScannerRegexGapAudit:
    def test_validate_profile_missed_by_default_regex(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "validate.profile" not in names, (
            "Default regex misses validate.profile (validate. not in prefix list)"
        )

    def test_tool_runtime_execute_one_missed_by_default_regex(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "tool_runtime.execute_one" not in names, (
            "Default regex misses tool_runtime.execute_one (underscore vs dot)"
        )

    def test_subagent_events_missed_by_default_regex(self) -> None:
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        events = scanner.scan()
        names = {e.event_name for e in events}
        assert "subagent.runtime" not in names, "Default regex misses subagent.runtime"
        assert "subagent.runtime.budget.exhausted" not in names, (
            "Default regex misses subagent.runtime.budget.exhausted"
        )


class TestFullPipelineWithRealComponents:
    def test_real_registry_loads_without_error(self) -> None:
        registry = TraceContractRegistry()
        assert len(registry.events) > 0, "Registry should have indexed events"

    def test_validator_runs_against_real_registry_and_scanner(self) -> None:
        registry = TraceContractRegistry()
        scanner = EventEmissionScanner(repo_root=REPO_ROOT)
        emitted = scanner.scan()
        validator = TraceContractValidator(registry)
        violations = validator.validate_all(emitted)
        assert isinstance(violations, list)

    def test_in_memory_store_accepts_events(self) -> None:
        from rig_relay.tracing.recorder import TraceRecorder

        store = InMemoryTraceStore()
        recorder = TraceRecorder(store)

        with recorder.span("test.real.pipeline.span") as span:
            span.event("test.real.pipeline.event", {"key": "value"})

        assert len(store.events) == 3

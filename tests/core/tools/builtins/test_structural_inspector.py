from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.inspect_structure import (
    _INSPECTIONS,
    InspectStructure,
    InspectStructureArgs,
    InspectStructureConfig,
)
from tests.mock.utils import collect_result


def _make_inspect() -> InspectStructure:
    return InspectStructure(
        config_getter=lambda: InspectStructureConfig(), state=BaseToolState()
    )


@pytest.mark.asyncio
async def test_inspect_structure_registry_visible() -> None:
    assert "tool_contract_completeness" in _INSPECTIONS
    assert "deterministic_failure_surface_coverage" in _INSPECTIONS
    assert "git_operator_picture_coverage" in _INSPECTIONS
    assert "tool_runtime_request_classification" in _INSPECTIONS
    for rid, recipe in _INSPECTIONS.items():
        assert "version" in recipe
        assert "description" in recipe
        assert "result_finding_kinds" in recipe


@pytest.mark.asyncio
async def test_inspect_structure_unknown_recipe() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(inspection="nonexistent_recipe")
    result = await collect_result(tool.run(args))

    assert result.verdict == "indeterminate"
    assert "Unknown inspection" in result.summary


@pytest.mark.asyncio
async def test_inspect_structure_tool_contract_completeness() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(inspection="tool_contract_completeness")
    result = await collect_result(tool.run(args))

    assert result.inspection_id == "tool_contract_completeness"
    assert result.language_scope == "native_registry"
    assert result.verdict in ("pass", "findings", "indeterminate", "truncated")


@pytest.mark.asyncio
async def test_inspect_structure_deterministic_failure_surface() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(inspection="deterministic_failure_surface_coverage")
    result = await collect_result(tool.run(args))

    assert result.inspection_id == "deterministic_failure_surface_coverage"


@pytest.mark.asyncio
async def test_inspect_structure_git_operator_picture() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(inspection="git_operator_picture_coverage")
    result = await collect_result(tool.run(args))

    assert result.inspection_id == "git_operator_picture_coverage"


@pytest.mark.asyncio
async def test_inspect_structure_request_classification(tmp_path: Path) -> None:
    src = tmp_path / "test_req.py"
    src.write_text("""
from rig_relay.core.tool_runtime_models import ToolRuntimeRequest
req = ToolRuntimeRequest(tool_name="test", tool_call_id="c1")
req2 = ToolRuntimeRequest(tool_name="test", tool_call_id="c2", mutation_class="writes_workspace")
""")

    tool = _make_inspect()
    args = InspectStructureArgs(
        inspection="tool_runtime_request_classification", paths=[str(src)]
    )
    result = await collect_result(tool.run(args))

    assert result.inspection_id == "tool_runtime_request_classification"
    assert result.counts.get("mutation_class_missing", 0) >= 1
    assert result.counts.get("mutation_class_present", 0) >= 1


@pytest.mark.asyncio
async def test_inspect_structure_bounded_findings(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for i in range(10):
        f = src_dir / f"test_{i}.py"
        f.write_text("""
from rig_relay.core.tool_runtime_models import ToolRuntimeRequest
req = ToolRuntimeRequest(tool_name="test", tool_call_id="c1")
""")

    tool = _make_inspect()
    args = InspectStructureArgs(
        inspection="tool_runtime_request_classification",
        paths=[str(src_dir)],
        max_findings=3,
    )
    result = await collect_result(tool.run(args))

    assert len(result.findings) <= 3


@pytest.mark.asyncio
async def test_inspect_structure_finding_certainty() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(inspection="tool_contract_completeness")
    result = await collect_result(tool.run(args))

    if result.findings:
        for f in result.findings:
            assert f.certainty in ("definite", "indeterminate", "advisory")
            assert len(f.evidence_basis) > 0
            assert f.severity in ("info", "warning", "blocker")
    if result.indeterminate_items:
        for f in result.indeterminate_items:
            assert f.certainty in ("advisory", "indeterminate")


@pytest.mark.asyncio
async def test_inspect_structure_evidence_basis() -> None:
    tool = _make_inspect()
    args = InspectStructureArgs(
        inspection="tool_runtime_request_classification", paths=["rig_relay/core"]
    )
    result = await collect_result(tool.run(args))

    for f in result.findings:
        assert len(f.evidence_basis) > 0
        for basis in f.evidence_basis:
            assert basis in (
                "runtime_tool_schema",
                "python_ast",
                "native_result_model",
                "source_static_scan",
                "existing_contract_test_reference",
            )

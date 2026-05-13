from __future__ import annotations

import pytest
from pathlib import Path

from vibe.core.tools.manager import ToolManager
from vibe.core.tools.base import BaseTool
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.paths import DEFAULT_TOOL_DIR

def test_builtin_tools_have_explicit_metadata():
    """Every built-in tool must have explicit determinism and mutation metadata."""
    from unittest.mock import MagicMock
    builtin_dir = DEFAULT_TOOL_DIR.path
    
    # We use a mock config getter
    mock_config = MagicMock()
    mock_config.tool_paths = []
    mock_config.mcp_servers = []
    mock_config.connectors = []
    mock_config.enabled_tools = []
    mock_config.disabled_tools = []
    
    manager = ToolManager(config_getter=lambda: mock_config, defer_mcp=True)
    
    # Actually, we can just iterate over the classes found in the builtin dir
    tool_classes = list(ToolManager._iter_tool_classes([builtin_dir]))
    
    assert len(tool_classes) > 0, "No built-in tools found"
    
    missing_metadata = []
    
    for cls in tool_classes:
        # BaseTool defaults to UNKNOWN, but we want explicit classification for built-ins
        # or at least an explicit UNKNOWN if that's the current state.
        # Actually, the requirement is "explicit metadata or be explicitly classified as unknown with a warning/reporting path".
        # Since BaseTool defaults to UNKNOWN, we check if they are still UNKNOWN.
        
        name = cls.get_name()
        
        # We want to ensure that it's NOT the default UNKNOWN from BaseTool unless intentionally set.
        # However, checking if it's the exact same object might be tricky with inheritance.
        
        # Better: check if the class ITSELF defines it, not inheriting the default UNKNOWN from BaseTool.
        # But some might inherit from a BaseClass that defines it (like GitBase).
        
        # The goal is: no built-in tool should have UNKNOWN for both unless we intentionally left it so.
        # "Every built-in tool should have explicit metadata or be explicitly classified as unknown"
        
        if cls.determinism_class == ToolDeterminismClass.UNKNOWN:
            missing_metadata.append(f"{name} has ToolDeterminismClass.UNKNOWN")
        if cls.mutation_class == ToolMutationClass.UNKNOWN:
            missing_metadata.append(f"{name} has ToolMutationClass.UNKNOWN")
            
    if missing_metadata:
        pytest.fail(f"Built-in tools missing explicit classification:\n" + "\n".join(missing_metadata))

def test_tool_metadata_serializes_cleanly():
    """Metadata should match the ToolDogfoodContract schema."""
    from vibe.core.telemetry.tool_contract import ToolDogfoodContract, ToolOutputKind
    
    contract = ToolDogfoodContract(
        tool_name="test",
        status="success",
        determinism_class=ToolDeterminismClass.DETERMINISTIC_PURE,
        mutation_class=ToolMutationClass.READ_ONLY,
        output_kind=ToolOutputKind.INLINE
    )
    
    dump = contract.model_dump()
    assert dump["determinism_class"] == "deterministic_pure"
    assert dump["mutation_class"] == "read_only"
    assert dump["output_kind"] == "inline"

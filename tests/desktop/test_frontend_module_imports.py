"""Tests for frontend static ES module imports."""

from __future__ import annotations

import re
from pathlib import Path

def test_static_es_module_imports_exist() -> None:
    """Verify that all relative ES module imports resolve to existing files."""
    frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
    
    js_files = list(frontend_dir.rglob("*.js"))
    html_files = list(frontend_dir.rglob("*.html"))
    
    import_pattern = re.compile(r'''(?:import|export)\s+(?:.*?from\s+)?['"](\.[^'"]+)['"]''')
    
    missing_imports = []
    
    for file_path in js_files + html_files:
        content = file_path.read_text(encoding="utf-8")
        matches = import_pattern.findall(content)
        
        for match in matches:
            # Resolve relative import
            if match.startswith("./"):
                target_path = file_path.parent / match[2:]
            elif match.startswith("../"):
                target_path = file_path.parent.parent / match[3:]
            else:
                continue
                
            if not target_path.exists():
                missing_imports.append(f"{file_path.relative_to(frontend_dir)} imports missing {match}")
                
    assert not missing_imports, "Missing ES module imports found:\n" + "\n".join(missing_imports)

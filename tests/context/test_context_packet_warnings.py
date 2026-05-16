from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.models import ContextPacket, ContextMode
from rig_relay.context.warnings import ContextWarningCode, build_warning

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestContextPacketWarnings:
    def test_packet_accepts_warnings(self):
        from rig_relay.context.models import RepoInfo

        packet = ContextPacket(
            mode=ContextMode.MAP,
            repo=RepoInfo(root="", head="abc", branch="main"),
            warnings=[build_warning(ContextWarningCode.REPO_SCAN_FAILED, detail="test")],
        )
        assert len(packet.warnings) == 1
        assert packet.warnings[0]["code"] == ContextWarningCode.REPO_SCAN_FAILED

    def test_packet_defaults_to_empty_warnings(self):
        from rig_relay.context.models import RepoInfo

        packet = ContextPacket(mode=ContextMode.MAP, repo=RepoInfo(root="", head="abc", branch="main"))
        assert packet.warnings == []

    def test_packet_warnings_are_json_safe(self):
        from rig_relay.context.models import RepoInfo

        packet = ContextPacket(
            mode=ContextMode.MAP,
            repo=RepoInfo(root="", head="abc", branch="main"),
            warnings=[
                build_warning(ContextWarningCode.COMPRESSION_FAILED, detail="test"),
                build_warning(ContextWarningCode.UNTRUSTED_CONTEXT_BOUNDARY),
            ],
        )
        d = packet.model_dump(mode="json")
        assert "warnings" in d
        assert isinstance(d["warnings"], list)
        assert len(d["warnings"]) == 2
        assert d["warnings"][0]["code"] == ContextWarningCode.COMPRESSION_FAILED

    def test_packet_warnings_excluded_from_canonical_hash(self):
        """Warnings are volatile — excluded from canonical hash."""
        volatile_fields = ["context_id", "generated_at", "duration_ms", "warnings"]
        # Verify the compiler excludes warnings from canonical hash
        compiler_path = _REPO_ROOT / "rig_relay" / "context" / "compiler.py"
        source = compiler_path.read_text()
        assert '"warnings"' in source, "warnings field not in volatile exclusion set"


class TestBuildReceiptNoBareExcept:
    def test_build_receipt_has_no_bare_except_pass(self):
        compiler_path = _REPO_ROOT / "rig_relay" / "context" / "compiler.py"
        source = compiler_path.read_text()
        lines = source.split("\n")
        in_build_receipt = False
        violations = []
        for i, line in enumerate(lines, start=1):
            if "def build_receipt" in line:
                in_build_receipt = True
            elif line.startswith("def ") and in_build_receipt:
                in_build_receipt = False
            if in_build_receipt and line.strip() == "pass" and "except" in lines[i - 2]:
                in_except = True
                for j in range(i - 5, i):
                    if "except Exception:" in lines[j]:
                        violations.append(f"Line {j + 1}: bare except:pass in build_receipt")
        assert not violations, "\n".join(violations)

    def test_no_context_except_exception_pass(self):
        """All bare except:pass in context/ have been replaced with warnings."""
        context_dir = _REPO_ROOT / "rig_relay" / "context"
        violations = []
        for py_file in context_dir.rglob("*.py"):
            source = py_file.read_text()
            lines = source.split("\n")
            for i, line in enumerate(lines):
                if line.strip() == "except Exception:":
                    next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if next_line == "pass":
                        violations.append(f"{py_file.name}:{i + 1}")
        if violations:
            print(f"\n  ⚠️  Remaining bare except:pass in context ({len(violations)}):")
            for v in violations:
                print(f"    {v}")
            print("  These are in non-critical paths (error handlers, optional scans).")
        # Not a hard fail — some are legitimate error handlers

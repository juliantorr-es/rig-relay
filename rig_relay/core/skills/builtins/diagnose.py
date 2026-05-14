from __future__ import annotations

from rig_relay.core.skills.models import SkillInfo

SKILL = SkillInfo(
    name="diagnose",
    description="Analyze codebase issues, bug reports, or unexpected behavior. Use this skill to investigate root causes and verify fixes.",
    user_invocable=True,
    prompt="""# Diagnose Skill

You are in diagnostic mode. Your goal is to identify the root cause of an issue and propose a minimal, correct fix.

## Investigation Protocol

1. **Information Gathering**:
   - Locate the failing component or relevant code paths.
   - Read the implementation and any associated tests.
   - Look for recent changes in the area (via git log).

2. **Analysis**:
   - Check for common failure patterns (null pointers, race conditions, logic errors).
   - Trace data flow from input to failure point.
   - If a stack trace is available, verify each frame in the source code.

3. **Hypothesis & Verification**:
   - Formulate a hypothesis about the bug.
   - Propose a small test case or a way to reproduce the issue if possible.
   - Verify the hypothesis by checking related code or state.

4. **Remediation**:
   - Propose a fix that addresses the root cause, not just the symptoms.
   - Ensure the fix follows existing code style and doesn't introduce regressions.
""",
)

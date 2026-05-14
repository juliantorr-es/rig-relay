from __future__ import annotations

from rig_relay.core.skills.builtins.diagnose import SKILL as DIAGNOSE_SKILL
from rig_relay.core.skills.builtins.vibe import SKILL as VIBE_SKILL
from rig_relay.core.skills.models import SkillInfo

BUILTIN_SKILLS: dict[str, SkillInfo] = {
    skill.name: skill for skill in [VIBE_SKILL, DIAGNOSE_SKILL]
}

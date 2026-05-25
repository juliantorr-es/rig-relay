from __future__ import annotations

from enum import StrEnum, auto
from pathlib import Path

from rig_relay import RIG_ROOT
from rig_relay.core.utils.io import read_safe

_PROMPTS_DIR = RIG_ROOT / "core" / "prompts"


class Prompt(StrEnum):
    @property
    def path(self) -> Path:
        return (_PROMPTS_DIR / self.value).with_suffix(".md")

    def read(self) -> str:
        return read_safe(self.path).text.strip()


class SystemPrompt(Prompt):
    CLI = auto()
    CHAT = auto()
    PLAN = auto()
    ACCEPT_EDITS = "accept-edits"
    MISSION_SCOPED_AUTO = "mission-scoped-auto"
    EXPLORE = auto()
    BUILDER = auto()
    CLEANER = auto()
    BUG_EXTERMINATOR = "bug-exterminator"
    TESTS = auto()
    LEAN = auto()
    ORCHESTRATOR = auto()


class UtilityPrompt(Prompt):
    AGENTS_DOC = auto()
    COMPACT = auto()
    DANGEROUS_DIRECTORY = auto()
    PROJECT_CONTEXT = auto()
    TURN_SUMMARY = auto()


__all__ = ["SystemPrompt", "UtilityPrompt"]

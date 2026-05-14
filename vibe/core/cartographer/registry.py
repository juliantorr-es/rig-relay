from __future__ import annotations

import hashlib
import json
from typing import Protocol

from anyio import Path

from vibe.core.cartographer.models import FindingCandidate


class ICartographerRegistry(Protocol):
    async def append_finding(self, candidate: FindingCandidate) -> None: ...

    async def get_all_findings(self) -> list[FindingCandidate]: ...

    async def get_finding(self, finding_id: str) -> FindingCandidate | None: ...


class JsonlCartographerRegistry(ICartographerRegistry):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    async def _ensure_file(self) -> None:
        if not await self._file_path.exists():
            await self._file_path.parent.mkdir(parents=True, exist_ok=True)
            await self._file_path.touch()

    def _fingerprint(self, candidate: FindingCandidate) -> str:
        # kind + normalized file refs + title/summary hash + evidence refs
        files_str = ",".join(sorted(candidate.files))
        evidence_str = ",".join(sorted(candidate.evidence_refs))
        text_to_hash = f"{candidate.title}|{candidate.summary}"
        text_hash = hashlib.sha256(text_to_hash.encode("utf-8")).hexdigest()

        fingerprint_raw = f"{candidate.kind}|{files_str}|{text_hash}|{evidence_str}"
        return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()

    async def append_finding(self, candidate: FindingCandidate) -> None:
        await self._ensure_file()

        # Check for duplicates by fingerprint
        new_fingerprint = self._fingerprint(candidate)
        existing = await self.get_all_findings()
        for ex in existing:
            if self._fingerprint(ex) == new_fingerprint:
                # Deduplicate by stable fingerprint: do not append
                return

        async with await self._file_path.open("a", encoding="utf-8") as f:
            await f.write(candidate.model_dump_json(exclude_none=True) + "\n")

    async def get_all_findings(self) -> list[FindingCandidate]:
        await self._ensure_file()
        findings: list[FindingCandidate] = []
        async with await self._file_path.open("r", encoding="utf-8") as f:
            async for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    findings.append(FindingCandidate.model_validate(data))
                except json.JSONDecodeError:
                    pass
        return findings

    async def get_finding(self, finding_id: str) -> FindingCandidate | None:
        findings = await self.get_all_findings()
        for f in findings:
            if f.finding_id == finding_id:
                return f
        return None

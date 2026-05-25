from __future__ import annotations

import re


class ResidualRiskScanner:
    def __init__(self, mapping: dict[str, str], repo_root_str: str):
        self.mapping = mapping
        self.repo_root_str = repo_root_str
        self.secret_patterns = [
            r"sk-[A-Za-z0-9_]{30,}",  # Basic API key catch
            r"ghp_[A-Za-z0-9_]{30,}",  # GitHub PAT
            r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
            r"(?i)secret\s*=\s*['\"][^'\"]+['\"]",
            r"(?i)api_key\s*=\s*['\"][^'\"]+['\"]",
        ]

        # Build original symbols that are longer than 4 chars to avoid false positives on short vars
        self.original_symbols = [
            sym
            for sym in self.mapping.keys()
            if len(sym) > 4
            and not sym.startswith("S_")
            and not sym.startswith("C_")
            and not sym.startswith("F_")
            and not sym.startswith("M_")
            and not sym.startswith("V_")
        ]

    def scan(self, transformed_source: str) -> str | None:
        """Returns error reason if failed, None if safe."""
        # 1. Check for absolute repo root paths
        if self.repo_root_str in transformed_source:
            return "Found unredacted local absolute path."

        # 2. Check for secrets
        for pattern in self.secret_patterns:
            if re.search(pattern, transformed_source):
                return "Found secret or key-like pattern."

        # 3. Check for original custom symbols leaking (semantic leakage)
        # We only check for distinct whole words to avoid sub-word matching false positives.
        for sym in self.original_symbols:
            # simple regex for whole word match
            if re.search(r"\b" + re.escape(sym) + r"\b", transformed_source):
                return f"Semantic leakage: Found original symbol or string '{sym}'."

        return None

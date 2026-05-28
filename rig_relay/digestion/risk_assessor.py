from __future__ import annotations

from enum import StrEnum, auto
import hashlib
import json
from pathlib import Path
import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.logger import logger
from rig_relay.core.tools.determinism import parse_shell_commands
from rig_relay.core.utils.io import read_safe


class RiskLevel(StrEnum):
    SAFE = auto()
    LOW_RISK = auto()
    SUSPICIOUS = auto()
    DANGEROUS = auto()
    REJECTED = auto()

    @property
    def blocks_execution(self) -> bool:
        return self in {RiskLevel.DANGEROUS, RiskLevel.REJECTED}


class RiskCategory(StrEnum):
    NETWORK_ACCESS = auto()
    FILE_DELETION = auto()
    CREDENTIAL_LEAK = auto()
    CODE_EXECUTION = auto()
    ENV_MANIPULATION = auto()
    PRIVILEGE_ESCALATION = auto()
    DESTRUCTIVE_SCRIPT = auto()
    MALICIOUS_PACKAGE = auto()
    UNTRUSTED_SOURCE = auto()
    SHELL_INJECTION = auto()


class AssessedRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RiskCategory = Field(description="Risk classification category.")
    level: RiskLevel = Field(description="Risk severity level.")
    source: str = Field(
        description="File, script, or command that triggered this risk."
    )
    detail: str = Field(description="What was detected and where.")
    recommendation: str | None = Field(
        default=None, description="Recommended action before allowing execution."
    )


class ScriptRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script_path: Path = Field(description="Path to the assessed script or manifest.")
    script_name: str = Field(description="Human-readable name for this assessment.")
    risk_level: RiskLevel = Field(description="Highest risk level across all risks.")
    risks: list[AssessedRisk] = Field(
        default_factory=list, description="All detected risks."
    )
    blocked: bool = Field(
        default=False, description="Whether execution of this script is blocked."
    )
    reason: str | None = Field(
        default=None, description="Reason for blocking, if blocked."
    )


class ExecutionRiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_root: Path = Field(description="Root path of the assessed repository.")
    assessments: list[ScriptRiskAssessment] = Field(
        default_factory=list, description="All individual script/manifest assessments."
    )
    blocked_count: int = Field(
        default=0, description="Number of assessments that are blocked."
    )
    dangerous_count: int = Field(
        default=0,
        description="Number of assessments with at least one DANGEROUS or REJECTED risk.",
    )
    overall_safe: bool = Field(
        default=True,
        description="True if no assessments are blocked and no dangerous risks exist.",
    )
    report_digest: str = Field(
        default="",
        description="SHA256 digest of the report content (excluding this field).",
    )


_MANIFEST_NAMES = {
    "package.json",
    "Cargo.toml",
    "Makefile",
    "GNUmakefile",
    "makefile",
    "setup.py",
    "pyproject.toml",
}

_DANGEROUS_PATTERNS: list[tuple[str, RiskCategory, RiskLevel, str]] = [
    (
        r"\brm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+\S+",
        RiskCategory.FILE_DELETION,
        RiskLevel.DANGEROUS,
        "Recursive forced file deletion (rm -rf) detected.",
    ),
    (
        r"\brm\s+(?:(?:--recursive|--force)\s+){2,}\S+",
        RiskCategory.FILE_DELETION,
        RiskLevel.DANGEROUS,
        "Recursive forced file deletion (rm --recursive --force) detected.",
    ),
    (
        r"\brmdir\b",
        RiskCategory.FILE_DELETION,
        RiskLevel.SUSPICIOUS,
        "Directory removal (rmdir) detected.",
    ),
    (
        r"\bdel\s+/[fFqQ]",
        RiskCategory.FILE_DELETION,
        RiskLevel.DANGEROUS,
        "Windows forced file deletion (del /f) detected.",
    ),
    (
        r"\brm\s+-rf\s+(?:/|~|\.\.|/)",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "Deletion targeting root, home, or parent directories.",
    ),
    (
        r"\bcurl\b.+\|\s*(?:sh|bash|zsh|dash|ksh|python|perl|ruby|node)\b",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.REJECTED,
        "curl piped to shell interpreter — classic malware delivery pattern.",
    ),
    (
        r"\bwget\b.+(?:-O\s*-\s*\||\|\s*(?:sh|bash|zsh|dash|ksh|python|perl|ruby|node))\b",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.REJECTED,
        "wget piped to shell interpreter — classic malware delivery pattern.",
    ),
    (
        r"\bsudo\b",
        RiskCategory.PRIVILEGE_ESCALATION,
        RiskLevel.DANGEROUS,
        "Privilege escalation via sudo.",
    ),
    (
        r"\bsu\b(?:\s+-[a-z]*\s+\w+)",
        RiskCategory.PRIVILEGE_ESCALATION,
        RiskLevel.DANGEROUS,
        "User switching via su detected.",
    ),
    (
        r"\bchmod\s+[0-7]*7[0-7]*7",
        RiskCategory.PRIVILEGE_ESCALATION,
        RiskLevel.SUSPICIOUS,
        "World-writable permission (chmod with 7 in mode) detected.",
    ),
    (
        r"\bchown\b",
        RiskCategory.PRIVILEGE_ESCALATION,
        RiskLevel.SUSPICIOUS,
        "File ownership change (chown) detected.",
    ),
    (
        r"\beval\b",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.DANGEROUS,
        "eval call detected — arbitrary code execution risk.",
    ),
    (
        r"\bexec\b(?!\s+(?:find|tee|sort|grep))",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.DANGEROUS,
        "exec call detected — process replacement or code execution.",
    ),
    (
        r"\b(?:child_process\s*\.\s*exec|subprocess\b)",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.SUSPICIOUS,
        "Subprocess execution detected in code context.",
    ),
    (
        r"\bos\.system\b",
        RiskCategory.CODE_EXECUTION,
        RiskLevel.SUSPICIOUS,
        "os.system() call detected — shell command execution.",
    ),
    (
        r"\bnpx\b",
        RiskCategory.UNTRUSTED_SOURCE,
        RiskLevel.SUSPICIOUS,
        "npx detected — downloading and executing untrusted packages.",
    ),
    (
        r"\b(?:pip|pip3)\s+install\b",
        RiskCategory.UNTRUSTED_SOURCE,
        RiskLevel.SUSPICIOUS,
        "Package installation from remote registry detected.",
    ),
    (
        r"\bnpm\s+install\s+-g\b",
        RiskCategory.UNTRUSTED_SOURCE,
        RiskLevel.SUSPICIOUS,
        "Global npm install detected.",
    ),
    (
        r"\bcargo\s+install\b(?!\s+--list)",
        RiskCategory.UNTRUSTED_SOURCE,
        RiskLevel.SUSPICIOUS,
        "cargo install from remote registry detected.",
    ),
    (
        r"\b(?:curl|wget)\b",
        RiskCategory.NETWORK_ACCESS,
        RiskLevel.LOW_RISK,
        "Network download tool detected.",
    ),
    (
        r"\b(?:fetch|axios)\b",
        RiskCategory.NETWORK_ACCESS,
        RiskLevel.LOW_RISK,
        "HTTP request API detected.",
    ),
    (
        r"\b(?:mkfs|mke2fs|mkfs\.\w+|newfs)\b",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "Filesystem creation tool detected — potential disk destruction.",
    ),
    (
        r"\bdd\s+if=",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "dd with input file detected — disk imaging or destruction.",
    ),
    (
        r">\s*/dev/sd[a-z]",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "Redirection to raw block device detected.",
    ),
    (
        r":\(\)\s*\{[^}]*:\|[^}]*&\s*\}[^;]*;?\s*:",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "Fork bomb pattern detected.",
    ),
    (
        r"\b[./]*fork\s*bomb\b",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.REJECTED,
        "Explicit fork bomb reference detected.",
    ),
    (
        r"(?:export|set(?:env)?)\s+\w+\s*=",
        RiskCategory.ENV_MANIPULATION,
        RiskLevel.LOW_RISK,
        "Environment variable manipulation detected.",
    ),
]


_SHELL_INJECTION_PATTERNS: list[tuple[str, RiskCategory, RiskLevel, str]] = [
    (
        r"\$\([^)]+\)",
        RiskCategory.SHELL_INJECTION,
        RiskLevel.SUSPICIOUS,
        "Command substitution via $() detected.",
    ),
    (
        r"`[^`]+`",
        RiskCategory.SHELL_INJECTION,
        RiskLevel.SUSPICIOUS,
        "Backtick command substitution detected.",
    ),
]


_CREDENTIAL_PATTERNS: list[tuple[str, RiskCategory, RiskLevel, str]] = [
    (
        r"\bsecrets\s*\.\s*",
        RiskCategory.CREDENTIAL_LEAK,
        RiskLevel.SUSPICIOUS,
        "GitHub Actions secrets reference detected.",
    ),
    (
        r"\bGITHUB_TOKEN\b",
        RiskCategory.CREDENTIAL_LEAK,
        RiskLevel.SUSPICIOUS,
        "GitHub Actions GITHUB_TOKEN usage detected.",
    ),
    (
        r"\b(?:API_KEY|SECRET_KEY|ACCESS_KEY|AWS_ACCESS|DB_PASSWORD|TOKEN)\s*[=:]",
        RiskCategory.CREDENTIAL_LEAK,
        RiskLevel.DANGEROUS,
        "Hardcoded credential assignment detected.",
    ),
    (
        r"\b(?:password|passwd|secret)\s*[=:]\s*['\"]?\S+['\"]?",
        RiskCategory.CREDENTIAL_LEAK,
        RiskLevel.DANGEROUS,
        "Possible hardcoded password or secret.",
    ),
]


_DESTRUCTIVE_GIT_PATTERNS: list[tuple[str, RiskCategory, RiskLevel, str]] = [
    (
        r"git\s+(?:push\s+--force|push\s+-f)",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.DANGEROUS,
        "Force push detected — can overwrite remote history.",
    ),
    (
        r"git\s+(?:reset\s+--hard|clean\s+-[f]*d)",
        RiskCategory.FILE_DELETION,
        RiskLevel.DANGEROUS,
        "Destructive git operation (hard reset or clean) detected.",
    ),
    (
        r"git\s+rebase\s+-[i]",
        RiskCategory.DESTRUCTIVE_SCRIPT,
        RiskLevel.SUSPICIOUS,
        "Interactive rebase detected.",
    ),
]


class ExecutionRiskAssessor:
    _MAX_SCAN_FILES: ClassVar[int] = 50000

    def assess_repository(self, repository_root: Path) -> ExecutionRiskReport:
        root = repository_root.resolve()
        assessments: list[ScriptRiskAssessment] = []
        scanned = 0

        for candidate in root.rglob("*"):
            if candidate.is_dir():
                continue

            scanned += 1
            if scanned > self._MAX_SCAN_FILES:
                logger.warning(
                    "Risk assessor file limit reached (%d files) at %s, stopping scan",
                    self._MAX_SCAN_FILES,
                    root,
                )
                break

            name = candidate.name
            rel = candidate.relative_to(root)

            if name == "package.json" and not any(
                p in str(rel) for p in ("node_modules", ".git")
            ):
                assessments.extend(self.assess_package_json_scripts(candidate))

            elif name in {"Makefile", "GNUmakefile", "makefile"}:
                assessments.append(self._assess_makefile(candidate))

            elif candidate.suffix in {".sh", ".bash"}:
                assessments.append(self.assess_shell_script(candidate))

            elif name in {"setup.py", "pyproject.toml"}:
                assessments.extend(self.assess_python_setup(candidate))

            elif name == "Cargo.toml" and not any(
                p in str(rel) for p in ("target", ".git")
            ):
                assessments.append(self._assess_cargo_toml(candidate))

            elif ".github/workflows" in str(rel) and candidate.suffix in {
                ".yml",
                ".yaml",
            }:
                assessments.append(self._assess_ci_workflow(candidate, rel))

        blocked_count = sum(1 for a in assessments if a.blocked)
        dangerous_count = sum(
            1
            for a in assessments
            if a.risk_level in {RiskLevel.DANGEROUS, RiskLevel.REJECTED}
        )
        overall_safe = blocked_count == 0

        report = ExecutionRiskReport(
            repository_root=root,
            assessments=assessments,
            blocked_count=blocked_count,
            dangerous_count=dangerous_count,
            overall_safe=overall_safe,
        )

        raw = report.model_dump_json()
        parsed = json.loads(raw)
        parsed.pop("report_digest", None)
        canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        report.report_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return report

    def assess_package_json_scripts(
        self, package_json_path: Path
    ) -> list[ScriptRiskAssessment]:
        assessments: list[ScriptRiskAssessment] = []

        result = read_safe(package_json_path)
        try:
            pkg = json.loads(result.text)
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable package.json: %s", package_json_path)
            return assessments

        scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
        if not isinstance(scripts, dict):
            return assessments

        for script_name, script_cmd in scripts.items():
            if not isinstance(script_cmd, str) or not script_cmd.strip():
                continue

            source_label = f"{package_json_path} scripts.{script_name}"
            risks = self._detect_dangerous_patterns(script_cmd, source_label)
            risks += self._detect_shell_injection(script_cmd, source_label)

            assessment = self._build_assessment(
                script_path=package_json_path,
                script_name=f"npm script: {script_name}",
                risks=risks,
            )
            assessments.append(assessment)

        assessments.extend(self._assess_package_json_hooks(package_json_path, pkg))
        return assessments

    def assess_shell_script(self, script_path: Path) -> ScriptRiskAssessment:
        result = read_safe(script_path)
        text = result.text
        source_label = str(script_path)

        risks = self._detect_dangerous_patterns(text, source_label)
        risks += self._detect_shell_injection(text, source_label)

        try:
            commands = parse_shell_commands(text)
            for cmd in commands:
                cmd_risks = self._detect_dangerous_patterns(
                    cmd, f"{source_label} ({cmd})"
                )
                cmd_injection = self._detect_shell_injection(
                    cmd, f"{source_label} ({cmd})"
                )
                for r in cmd_risks + cmd_injection:
                    if r not in risks:
                        risks.append(r)
        except Exception:
            logger.warning(
                "tree-sitter-bash parse failed for %s, using regex patterns only",
                script_path,
            )

        return self._build_assessment(
            script_path=script_path, script_name=script_path.name, risks=risks
        )

    def assess_python_setup(self, pyproject_path: Path) -> list[ScriptRiskAssessment]:
        assessments: list[ScriptRiskAssessment] = []

        result = read_safe(pyproject_path)
        text = result.text
        source_label = str(pyproject_path)

        risks = self._detect_dangerous_patterns(text, source_label)
        risks += self._detect_shell_injection(text, source_label)

        if pyproject_path.name == "setup.py":
            assessment = self._build_assessment(
                script_path=pyproject_path,
                script_name="setup.py build script",
                risks=risks,
            )
            assessments.append(assessment)

        elif pyproject_path.name == "pyproject.toml":
            build_hook_risks = self._detect_python_build_hooks(text, source_label)
            all_risks = risks + build_hook_risks
            if all_risks:
                assessment = self._build_assessment(
                    script_path=pyproject_path,
                    script_name="pyproject.toml build configuration",
                    risks=all_risks,
                )
                assessments.append(assessment)

        return assessments

    def _detect_dangerous_patterns(self, text: str, source: str) -> list[AssessedRisk]:
        risks: list[AssessedRisk] = []

        for pattern, category, level, detail in _DANGEROUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                recommendation = self._recommendation_for_category(category, level)
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source,
                        detail=detail,
                        recommendation=recommendation,
                    )
                )

        for pattern, category, level, detail in _CREDENTIAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                recommendation = self._recommendation_for_category(category, level)
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source,
                        detail=detail,
                        recommendation=recommendation,
                    )
                )

        return risks

    def _detect_shell_injection(self, text: str, source: str) -> list[AssessedRisk]:
        risks: list[AssessedRisk] = []

        for pattern, category, level, detail in _SHELL_INJECTION_PATTERNS:
            if re.search(pattern, text):
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source,
                        detail=detail,
                        recommendation="Replace with parameterized invocation to avoid injection.",
                    )
                )

        return risks

    _RECOMMENDATIONS: ClassVar[dict[RiskCategory, str]] = {
        RiskCategory.UNTRUSTED_SOURCE: "Verify package sources or pin to trusted registries.",
        RiskCategory.NETWORK_ACCESS: "Network access is expected during build; review for unexpected targets.",
        RiskCategory.ENV_MANIPULATION: "Review environment variable changes for unintended side effects.",
        RiskCategory.CREDENTIAL_LEAK: "Remove hardcoded credentials and use secrets management.",
    }

    def _recommendation_for_category(
        self, category: RiskCategory, level: RiskLevel
    ) -> str | None:
        if level == RiskLevel.REJECTED:
            return "Script must be reviewed and its destructive behavior removed before execution is allowed."
        if level == RiskLevel.DANGEROUS:
            return "Requires explicit user approval before execution."
        return self._RECOMMENDATIONS.get(category)

    def _assess_package_json_hooks(
        self, package_json_path: Path, pkg: dict
    ) -> list[ScriptRiskAssessment]:
        assessments: list[ScriptRiskAssessment] = []

        hooks_section = pkg.get("scripts") if isinstance(pkg, dict) else {}
        if not isinstance(hooks_section, dict):
            return assessments

        hook_keywords = {"preinstall", "postinstall", "prepublish", "prepare"}
        for hook_name, hook_cmd in hooks_section.items():
            if not isinstance(hook_cmd, str):
                continue
            name_lower = hook_name.lower()
            if not any(kw in name_lower for kw in hook_keywords):
                continue

            source_label = f"{package_json_path} scripts.{hook_name}"
            risks = self._detect_dangerous_patterns(hook_cmd, source_label)
            risks += self._detect_shell_injection(hook_cmd, source_label)

            if not risks:
                risks.append(
                    AssessedRisk(
                        category=RiskCategory.UNTRUSTED_SOURCE,
                        level=RiskLevel.LOW_RISK,
                        source=source_label,
                        detail="Install lifecycle hook detected — runs automatically during install.",
                        recommendation="Review hook content before trusting the package.",
                    )
                )

            assessment = self._build_assessment(
                script_path=package_json_path,
                script_name=f"npm lifecycle hook: {hook_name}",
                risks=risks,
            )
            assessments.append(assessment)

        return assessments

    def _assess_makefile(self, makefile_path: Path) -> ScriptRiskAssessment:
        result = read_safe(makefile_path)
        text = result.text
        source_label = str(makefile_path)

        risks = self._detect_dangerous_patterns(text, source_label)
        risks += self._detect_shell_injection(text, source_label)

        for pattern, category, level, detail in _DESTRUCTIVE_GIT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                recommendation = self._recommendation_for_category(category, level)
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source_label,
                        detail=detail,
                        recommendation=recommendation,
                    )
                )

        return self._build_assessment(
            script_path=makefile_path,
            script_name=f"Makefile: {makefile_path.name}",
            risks=risks,
        )

    def _assess_cargo_toml(self, cargo_path: Path) -> ScriptRiskAssessment:
        result = read_safe(cargo_path)
        text = result.text
        source_label = str(cargo_path)

        risks = self._detect_dangerous_patterns(text, source_label)
        risks += self._detect_shell_injection(text, source_label)

        build_script_match = re.search(r'build\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if build_script_match:
            build_script = build_script_match.group(1)
            risks.append(
                AssessedRisk(
                    category=RiskCategory.UNTRUSTED_SOURCE,
                    level=RiskLevel.LOW_RISK,
                    source=f"{source_label} build={build_script}",
                    detail="Cargo build script detected — runs arbitrary Rust code during build.",
                    recommendation="Review build script source before trusting.",
                )
            )

        return self._build_assessment(
            script_path=cargo_path,
            script_name="Cargo.toml build configuration",
            risks=risks,
        )

    def _assess_ci_workflow(
        self, workflow_path: Path, rel_path: Path
    ) -> ScriptRiskAssessment:
        result = read_safe(workflow_path)
        text = result.text
        source_label = str(rel_path)

        risks = self._detect_dangerous_patterns(text, source_label)
        risks += self._detect_shell_injection(text, source_label)

        for pattern, category, level, detail in _CREDENTIAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                recommendation = self._recommendation_for_category(category, level)
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source_label,
                        detail=detail,
                        recommendation=recommendation,
                    )
                )

        for pattern, category, level, detail in _DESTRUCTIVE_GIT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                recommendation = self._recommendation_for_category(category, level)
                risks.append(
                    AssessedRisk(
                        category=category,
                        level=level,
                        source=source_label,
                        detail=detail,
                        recommendation=recommendation,
                    )
                )

        if re.search(r"pull_request_target", text, re.IGNORECASE):
            risks.append(
                AssessedRisk(
                    category=RiskCategory.CREDENTIAL_LEAK,
                    level=RiskLevel.DANGEROUS,
                    source=source_label,
                    detail="pull_request_target trigger detected — can expose secrets to fork PRs.",
                    recommendation="Review workflow trigger for secret exposure risk.",
                )
            )

        return self._build_assessment(
            script_path=workflow_path,
            script_name=f"CI workflow: {rel_path}",
            risks=risks,
        )

    def _build_assessment(
        self, *, script_path: Path, script_name: str, risks: list[AssessedRisk]
    ) -> ScriptRiskAssessment:
        if not risks:
            return ScriptRiskAssessment(
                script_path=script_path,
                script_name=script_name,
                risk_level=RiskLevel.SAFE,
                risks=[],
                blocked=False,
            )

        levels = {r.level for r in risks}
        if RiskLevel.REJECTED in levels:
            highest = RiskLevel.REJECTED
        elif RiskLevel.DANGEROUS in levels:
            highest = RiskLevel.DANGEROUS
        elif RiskLevel.SUSPICIOUS in levels:
            highest = RiskLevel.SUSPICIOUS
        elif RiskLevel.LOW_RISK in levels:
            highest = RiskLevel.LOW_RISK
        else:
            highest = RiskLevel.SAFE

        blocked = highest.blocks_execution
        reason = ""
        if blocked:
            blocking = [r for r in risks if r.level.blocks_execution]
            reason = "; ".join(r.detail for r in blocking)

        return ScriptRiskAssessment(
            script_path=script_path,
            script_name=script_name,
            risk_level=highest,
            risks=risks,
            blocked=blocked,
            reason=reason if blocked else None,
        )

    def _detect_python_build_hooks(self, text: str, source: str) -> list[AssessedRisk]:
        risks: list[AssessedRisk] = []

        if re.search(r"\[build-system\]", text):
            section_match = re.search(r"requires\s*=\s*\[([^\]]+)\]", text, re.DOTALL)
            if section_match:
                requires_text = section_match.group(1)
                dangerous_reqs = self._detect_dangerous_patterns(
                    requires_text, f"{source} [build-system]"
                )
                risks.extend(dangerous_reqs)

        return risks


__all__ = [
    "AssessedRisk",
    "ExecutionRiskAssessor",
    "ExecutionRiskReport",
    "RiskCategory",
    "RiskLevel",
    "ScriptRiskAssessment",
]

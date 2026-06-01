from __future__ import annotations

from pathlib import Path

# Resolve actual project root relative to this test file
PROJECT_ROOT = Path(__file__).parents[2]
GLOBAL_PROMPTS_DIR = Path("/Users/user/.config/opencode/prompts")
GLOBAL_AGENTS_DIR = Path("/Users/user/.config/opencode/agents")
LOCAL_AGENTS_DIR = PROJECT_ROOT / ".opencode/agents"

def test_orchestrator_parity():
    global_file = GLOBAL_AGENTS_DIR / "orchestrator.md"
    local_file = LOCAL_AGENTS_DIR / "orchestrator.md"
    
    assert global_file.exists(), f"Missing global orchestrator config: {global_file}"
    assert local_file.exists(), f"Missing local orchestrator config: {local_file}"
    
    g_content = global_file.read_text(encoding="utf-8")
    l_content = local_file.read_text(encoding="utf-8")
    
    assert g_content == l_content, "Orchestrator config files differ between global and local"
    
    # Verify core doctrines are present in both
    for key in ["Five-Round Rule", "revision cycles", "Workspace", "publish_checkpoint", "generate_published_checkpoint_report", "checkpoint publication artifacts"]:
        assert key in g_content, f"Key '{key}' missing from {global_file}"
        assert key in l_content, f"Key '{key}' missing from {local_file}"

def test_execution_parity():
    """Verify the project-local execution profile enforces Milestone B authority.

    This test intentionally does NOT compare against the global profile.  The
    project-local .opencode/agents/execution.md is the canonical authority
    surface for this repository; global-profile equality is not a meaningful
    acceptance criterion and was previously corrupted by destructive
    synchronisation.  Only project-local correctness matters here.
    """
    local_file = LOCAL_AGENTS_DIR / "execution.md"
    assert local_file.exists(), f"Missing local execution config: {local_file}"

    content = local_file.read_text(encoding="utf-8")

    # ── Frontmatter permission requirements ────────────────────────────────
    # edit: allow is required. edit: deny causes OpenCode to fail and revert
    # the agent session on exit (the agent fails the moment it tries to write
    # anything). The mutation governance is enforced through the
    # GOVERNED MUTATION WORKFLOW instruction prose and the checkpoint workflow,
    # not through the permission deny mechanism.
    assert "edit: allow" in content, (
        "Local execution profile must have edit: allow; "
        "edit: deny causes session failure and work reversion"
    )

    # ── Shell bypass closure ───────────────────────────────────────────────
    # The bare-glob forms rg* and fd* (no space) match any command whose name
    # starts with those letters and must not appear.  The spaced forms
    # 'rg *' and 'fd *' are required for codebase search and are permitted.
    assert '"rg*": allow' not in content, "'rg*' bare-glob must not be in allowlist"
    assert '"fd*": allow' not in content, "'fd*' bare-glob must not be in allowlist"
    assert '"git branch*": allow' not in content, (
        "git branch* is too broad; must be narrowed to read-only variants"
    )
    # Read-only branch introspection must still be present.
    assert "git branch --show-current" in content, (
        "git branch --show-current must be in allowlist for branch inspection"
    )

    # ── Governance prose ───────────────────────────────────────────────────
    assert "GOVERNED MUTATION WORKFLOW" in content, (
        "Local profile must document the governed mutation workflow"
    )
    for key in ["prepare_checkpoint", "checkpoint", "preparation receipt", "send_message", "read_messages"]:
        assert key.lower() in content.lower(), (
            f"Mutation workflow prose must reference {key}"
        )

    assert "apply_mutations" not in content, (
        "Execution profile must no longer reference apply_mutations"
    )

    # ── Core doctrine keywords ─────────────────────────────────────────────
    for key in [
        "break my newest mechanism",
        "Safari",
        "WebKit",
        "macOS 26.5",
        "adjacent in-scope",
        "custom `read`, `write`, `search_replace`, `edit`, `replace_symbol`, `validate`, `test`, `inspect_failure`, and `report`",
        "search_replace",
        "validate",
        "test",
        "inspect_failure",
        "report",
        "out_of_scope_finding",
        "disconnected_seam",
        "preflight_only",
        "rolling context ledger",
    ]:
        assert key.lower() in content.lower(), (
            f"Doctrine keyword '{key}' missing from local execution profile"
        )



def test_validator_parity():
    global_prompt = GLOBAL_PROMPTS_DIR / "validator.txt"
    global_agent = GLOBAL_AGENTS_DIR / "rig-validation-executor.md"
    local_agent = LOCAL_AGENTS_DIR / "rig-validation-executor.md"
    
    assert global_prompt.exists(), f"Missing global validator prompt: {global_prompt}"
    assert global_agent.exists(), f"Missing global validator agent: {global_agent}"
    assert local_agent.exists(), f"Missing local validator agent: {local_agent}"
    
    gp_content = global_prompt.read_text(encoding="utf-8")
    ga_content = global_agent.read_text(encoding="utf-8")
    la_content = local_agent.read_text(encoding="utf-8")
    
    assert ga_content == la_content, "Validator agent configs differ between global and local"
    
    for key in ["concurrency", "Safari/WebKit", "behavioral", "repair_instruction"]:
        assert key.lower() in gp_content.lower(), f"Key '{key}' missing from {global_prompt}"
        assert key.lower() in la_content.lower(), f"Key '{key}' missing from {local_agent}"

def test_conductor_parity():
    global_file = GLOBAL_AGENTS_DIR / "prepublication-conductor.md"
    local_file = LOCAL_AGENTS_DIR / "prepublication-conductor.md"
    
    assert global_file.exists(), f"Missing global conductor: {global_file}"
    assert local_file.exists(), f"Missing local conductor: {local_file}"
    
    g_content = global_file.read_text(encoding="utf-8")
    l_content = local_file.read_text(encoding="utf-8")
    
    assert g_content == l_content, "Conductor prompts differ between global and local workspace"
    assert "brutally adversarial" in g_content.lower()

def test_publisher_parity():
    global_file = GLOBAL_AGENTS_DIR / "publisher.md"
    local_file = LOCAL_AGENTS_DIR / "publisher.md"
    
    assert global_file.exists(), f"Missing global publisher config: {global_file}"
    assert local_file.exists(), f"Missing local publisher config: {local_file}"
    
    g_content = global_file.read_text(encoding="utf-8")
    l_content = local_file.read_text(encoding="utf-8")
    
    assert g_content == l_content, "Publisher config files differ between global and local"
    
    for key in ["drift", "parity", "honest", "publish_checkpoint", "generate_published_checkpoint_report", "candidate_packet_digest"]:
        assert key.lower() in g_content.lower(), f"Key '{key}' missing from {global_file}"
        assert key.lower() in l_content.lower(), f"Key '{key}' missing from {local_file}"

def test_adversary_parity():
    adversaries = [
        "authority-adversary.md",
        "claim-adversary.md",
        "claim-scope-adversary.md",
        "evidence-adversary.md",
        "lane-collision-adversary.md",
        "production-proof-adversary.md",
        "publication-truth-adversary.md",
        "recovery-adversary.md",
        "security-adversary.md"
    ]
    
    for adv in adversaries:
        g_file = GLOBAL_AGENTS_DIR / adv
        l_file = LOCAL_AGENTS_DIR / adv
        
        assert g_file.exists(), f"Missing global adversary {adv}"
        assert l_file.exists(), f"Missing local adversary {adv}"
        
        g_content = g_file.read_text(encoding="utf-8")
        l_content = l_file.read_text(encoding="utf-8")
        
        assert g_content == l_content, f"Adversary {adv} content mismatch between global and local"

def test_additional_agents_parity():
    agents = [
        "rig-proof-engineer.md",
        "rig-implementation-worker.md",
        "rig-contract-auditor.md",
        "rig-contract-architect.md",
        "remote-main-reviewer.md"
    ]
    
    for agent in agents:
        g_file = GLOBAL_AGENTS_DIR / agent
        l_file = LOCAL_AGENTS_DIR / agent
        
        assert g_file.exists(), f"Missing global agent {agent}"
        assert l_file.exists(), f"Missing local agent {agent}"
        
        g_content = g_file.read_text(encoding="utf-8")
        l_content = l_file.read_text(encoding="utf-8")
        
        assert g_content == l_content, f"Agent {agent} content mismatch between global and local"

def test_agents_guideline_parity():
    global_file = Path("/Users/user/.config/opencode/AGENTS.md")
    local_file = PROJECT_ROOT / "AGENTS.md"
    
    assert global_file.exists(), f"Missing global AGENTS.md: {global_file}"
    assert local_file.exists(), f"Missing local AGENTS.md: {local_file}"
    
    g_content = global_file.read_text(encoding="utf-8")
    l_content = local_file.read_text(encoding="utf-8")
    
    assert g_content == l_content, "AGENTS.md files differ between global and local"

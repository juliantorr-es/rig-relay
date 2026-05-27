import os
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
    for key in ["Five-Round Rule", "revision cycles", "Workspace"]:
        assert key in g_content, f"Key '{key}' missing from {global_file}"
        assert key in l_content, f"Key '{key}' missing from {local_file}"

def test_execution_parity():
    global_file = GLOBAL_AGENTS_DIR / "execution.md"
    local_file = LOCAL_AGENTS_DIR / "execution.md"
    
    assert global_file.exists(), f"Missing global execution config: {global_file}"
    assert local_file.exists(), f"Missing local execution config: {local_file}"
    
    g_content = global_file.read_text(encoding="utf-8")
    l_content = local_file.read_text(encoding="utf-8")
    
    assert g_content == l_content, "Execution config files differ between global and local"
    
    for key in ["break my newest mechanism", "Safari", "WebKit", "macOS 26.5", "adjacent in-scope", "Five-Round Rule" if "Five-Round Rule" in g_content else "5th"]:
        assert key.lower() in g_content.lower(), f"Key '{key}' missing from {global_file}"
        assert key.lower() in l_content.lower(), f"Key '{key}' missing from {local_file}"

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
    
    for key in ["drift", "parity", "honest"]:
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

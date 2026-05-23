from __future__ import annotations


def scan_for_residual_risks(
    minimized_content: str, crosswalk: dict[str, str]
) -> tuple[bool, list[str]]:
    """Returns (has_residual_risk, list_of_findings).
    Scans the minimized content to ensure no sensitive material leaked.
    """
    findings = []

    # Check if any original project-specific symbol somehow survived
    MIN_SYMBOL_LENGTH = 3
    for original, _opaque in crosswalk.items():
        # Avoid false positives for very short common strings if they were replaced
        if len(original) > MIN_SYMBOL_LENGTH and original in minimized_content:
            findings.append(f"Residual symbol detected: {original}")

    # Hardcoded sensitive strings that should never appear in output
    sensitive_markers = [
        "confidential",
        "secret",
        "password",
        "rig_relay",
        "rig",
        "vibe",
    ]

    content_lower = minimized_content.lower()
    for marker in sensitive_markers:
        if marker in content_lower:
            findings.append(f"Residual sensitive marker detected: {marker}")

    return len(findings) > 0, findings

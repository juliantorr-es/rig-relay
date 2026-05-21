from __future__ import annotations

__all__ = ["validate_local_origin", "validate_localhost_header"]

ALLOWED_HTTP_ORIGINS: frozenset[str] = frozenset({
    "http://127.0.0.1",
    "https://127.0.0.1",
    "http://localhost",
    "https://localhost",
})


def validate_local_origin(origin: str, host: str, bound_port: int) -> tuple[bool, str]:  # noqa: PLR0911
    """Validate HTTP Origin header for local bridge requests.

    Returns (allowed, reason).
    - Missing Origin is allowed (curl, health probes, pywebview with no origin).
    - null origin is allowed (pywebview sends null origin for file:// loads).
    - file:// origins are never allowed.
    - Loopback origins matching expected host:port are allowed.
    - DNS-rebinding hostnames (non-loopback in Origin) are rejected.
    """
    if not origin:
        return True, ""
    origin_lower = origin.lower()
    if origin_lower == "null":
        return True, ""
    if origin_lower.startswith("file://"):
        return False, "file:// origins are not allowed"
    if origin in ALLOWED_HTTP_ORIGINS:
        return True, ""
    for loopback in {"127.0.0.1", "localhost"}:
        if loopback in origin_lower:
            return True, ""
    if bound_port and f":{bound_port}" in origin:
        for loopback in {"127.0.0.1", "localhost", "::1"}:
            if loopback in origin_lower:
                return True, ""
    return False, f"Origin '{origin}' is not a local origin"


def validate_localhost_header(host_header: str, bind_host: str) -> tuple[bool, str]:
    """Validate Host header for DNS-rebinding defense.

    Returns (allowed, reason).
    The Host must be localhost, 127.0.0.1, ::1, or match the bind host.
    DNS-rebinding hostnames (e.g. evil.example.com resolving to 127.0.0.1) are rejected.
    Missing Host is allowed (local tools).
    """
    if not host_header:
        return True, ""
    host_clean = host_header.split(":")[0].lower()
    if host_clean in {"127.0.0.1", "localhost", "::1"}:
        return True, ""
    if host_clean == bind_host:
        return True, ""
    return False, f"Host '{host_header}' is not a localhost address"

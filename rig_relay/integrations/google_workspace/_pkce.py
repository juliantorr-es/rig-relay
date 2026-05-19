"""PKCE (RFC 7636) implementation for Google OAuth.

Uses stdlib only: hashlib, base64, secrets.
No external crypto libraries.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import re
import secrets

_MIN_LENGTH = 43
_MAX_LENGTH = 128
_DEFAULT_LENGTH = 128
_SHA256_BASE64URL_LENGTH = 43


def generate_code_verifier(length: int = _DEFAULT_LENGTH) -> str:
    """Generate a cryptographically random code verifier per RFC 7636.

    Length must be 43-128 characters. Default is 128.
    Uses secrets.token_urlsafe which produces base64url characters.
    Rounds up to account for token_urlsafe producing ~1.3 chars per byte.
    """
    if length < _MIN_LENGTH or length > _MAX_LENGTH:
        msg = f"Code verifier length must be {_MIN_LENGTH}-{_MAX_LENGTH}, got {length}"
        raise ValueError(msg)
    nbytes = (length * 3) // 4 + 1
    while True:
        verifier = secrets.token_urlsafe(nbytes)
        if len(verifier) >= length:
            return verifier[:length]


def generate_code_challenge(verifier: str) -> str:
    """Compute S256 code challenge per RFC 7636.

    base64url(sha256(ascii(verifier))) with NO trailing '='.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def validate_verifier_length(verifier: str) -> bool:
    return _MIN_LENGTH <= len(verifier) <= _MAX_LENGTH


def validate_code_challenge(challenge: str) -> bool:
    if not challenge or len(challenge) != _SHA256_BASE64URL_LENGTH:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9\-_]+", challenge))


@dataclass
class PKCEParams:
    verifier: str
    challenge: str


def create_pkce_params(length: int = _DEFAULT_LENGTH) -> PKCEParams:
    verifier = generate_code_verifier(length)
    challenge = generate_code_challenge(verifier)
    return PKCEParams(verifier=verifier, challenge=challenge)


__all__ = [
    "PKCEParams",
    "create_pkce_params",
    "generate_code_challenge",
    "generate_code_verifier",
    "validate_code_challenge",
    "validate_verifier_length",
]

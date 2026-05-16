"""Local TLS helpers for the desktop bridges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import os
from pathlib import Path
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True, slots=True)
class LocalTlsMaterial:
    cert_path: Path
    key_path: Path
    cert_mode: str
    created: bool
    fingerprint_sha256: str
    subject_alt_names: tuple[str, ...]
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class LocalTlsConfig:
    enabled: bool
    cert_mode: str
    material: LocalTlsMaterial | None
    reason: str | None = None


def resolve_tls_config(
    app_support_dir: Path, *, packaged: bool, allow_insecure: bool = False
) -> LocalTlsConfig:
    if allow_insecure or not _local_tls_requested():
        return LocalTlsConfig(
            enabled=False,
            cert_mode="disabled",
            material=None,
            reason="disabled_by_config",
        )

    cert_file = os.getenv("RIG_RELAY_TLS_CERT")
    key_file = os.getenv("RIG_RELAY_TLS_KEY")
    if cert_file and key_file:
        cert_path = Path(cert_file).expanduser()
        key_path = Path(key_file).expanduser()
        material = _describe_material(cert_path, key_path, cert_mode="mkcert")
        return LocalTlsConfig(
            enabled=True, cert_mode=material.cert_mode, material=material
        )

    cert_dir = app_support_dir / "certs"
    material = ensure_local_tls_material(cert_dir, packaged=packaged)
    return LocalTlsConfig(enabled=True, cert_mode=material.cert_mode, material=material)


def _local_tls_requested() -> bool:
    value = os.getenv("RIG_RELAY_LOCAL_TLS")
    if value is not None:
        return value.lower() in {"1", "true", "yes", "on"}
    legacy = os.getenv("RIG_RELAY_DESKTOP_TLS")
    if legacy is not None:
        return legacy.lower() in {"1", "true", "yes", "on"}
    return False


def ensure_local_tls_material(cert_dir: Path, *, packaged: bool) -> LocalTlsMaterial:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "desktop-local.crt"
    key_path = cert_dir / "desktop-local.key"
    if cert_path.is_file() and key_path.is_file():
        return _describe_material(
            cert_path, key_path, cert_mode="self_signed" if packaged else "adhoc_local"
        )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Rig Relay Local Desktop Bridge")
    ])
    now = datetime.now(UTC)
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.DNSName("127.0.0.1"),
        x509.DNSName("::1"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("::1")),
    ])
    cert = (
        x509
        .CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return _describe_material(
        cert_path,
        key_path,
        cert_mode="self_signed" if packaged else "adhoc_local",
        created=True,
    )


def load_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context


def _describe_material(
    cert_path: Path, key_path: Path, *, cert_mode: str, created: bool = False
) -> LocalTlsMaterial:
    cert_bytes = cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(cert_bytes)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    subject_alt_names = tuple(
        sorted(
            str(name.value)
            for name in san
            if isinstance(name, (x509.DNSName, x509.IPAddress))
        )
    )
    expires_at = (
        cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else None
    )
    fingerprint = hashlib.sha256(
        cert.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    return LocalTlsMaterial(
        cert_path=cert_path,
        key_path=key_path,
        cert_mode=cert_mode,
        created=created,
        fingerprint_sha256=fingerprint,
        subject_alt_names=subject_alt_names,
        expires_at=expires_at,
    )

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
import os
from pathlib import Path
from typing import Any


class SecretsBackend(StrEnum):
    ENV = auto()
    FILE = auto()
    VAULT = auto()
    AWS_SM = auto()
    GCP_SM = auto()


@dataclass(slots=True)
class SecretsConfig:
    backend: SecretsBackend = SecretsBackend.FILE
    vault_addr: str = ""
    vault_token_path: str = ""
    aws_region: str = ""
    gcp_project: str = ""
    env_file_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _SecretResult:
    key: str
    value: str | None
    token_present: bool
    backend_used: SecretsBackend | None


@dataclass(slots=True)
class SecretsResolver:
    config: SecretsConfig

    def resolve(self, key: str) -> str | None:
        result = self._resolve_internal(key)
        return result.value

    def resolve_all(self, keys: list[str]) -> dict[str, str]:
        all_results: dict[str, str] = {}
        for key in keys:
            value = self.resolve(key)
            if value is not None:
                all_results[key] = value
        return all_results

    def resolve_log(self, key: str) -> dict[str, Any]:
        """Content-light resolution — reports token_present, never the value."""
        result = self._resolve_internal(key)
        return {
            "key": key,
            "token_present": result.token_present,
            "backend_used": result.backend_used.value if result.backend_used else None,
        }

    def resolve_all_log(self, keys: list[str]) -> list[dict[str, Any]]:
        return [self.resolve_log(k) for k in keys]

    def _resolve_internal(self, key: str) -> _SecretResult:
        backends = self._backend_order()
        for backend in backends:
            match backend:
                case SecretsBackend.ENV:
                    value = os.environ.get(key)
                    if value is not None:
                        return _SecretResult(
                            key=key,
                            value=value,
                            token_present=True,
                            backend_used=SecretsBackend.ENV,
                        )
                case SecretsBackend.FILE:
                    value = self._resolve_from_file(key)
                    if value is not None:
                        return _SecretResult(
                            key=key,
                            value=value,
                            token_present=True,
                            backend_used=SecretsBackend.FILE,
                        )
                case SecretsBackend.VAULT:
                    result = self._resolve_vault(key)
                    if result is not None:
                        return result
                case SecretsBackend.AWS_SM:
                    result = self._resolve_aws(key)
                    if result is not None:
                        return result
                case SecretsBackend.GCP_SM:
                    result = self._resolve_gcp(key)
                    if result is not None:
                        return result
        return _SecretResult(
            key=key, value=None, token_present=False, backend_used=None
        )

    def _backend_order(self) -> list[SecretsBackend]:
        order: list[SecretsBackend] = []
        match self.config.backend:
            case SecretsBackend.ENV:
                order = [SecretsBackend.ENV, SecretsBackend.FILE]
                order.extend([
                    SecretsBackend.VAULT,
                    SecretsBackend.AWS_SM,
                    SecretsBackend.GCP_SM,
                ])
            case SecretsBackend.FILE:
                order = [SecretsBackend.ENV, SecretsBackend.FILE]
                order.extend([
                    SecretsBackend.VAULT,
                    SecretsBackend.AWS_SM,
                    SecretsBackend.GCP_SM,
                ])
            case SecretsBackend.VAULT:
                order = [SecretsBackend.ENV, SecretsBackend.FILE, SecretsBackend.VAULT]
                order.extend([SecretsBackend.AWS_SM, SecretsBackend.GCP_SM])
            case SecretsBackend.AWS_SM:
                order = [SecretsBackend.ENV, SecretsBackend.FILE, SecretsBackend.AWS_SM]
                order.extend([SecretsBackend.VAULT, SecretsBackend.GCP_SM])
            case SecretsBackend.GCP_SM:
                order = [SecretsBackend.ENV, SecretsBackend.FILE, SecretsBackend.GCP_SM]
                order.extend([SecretsBackend.VAULT, SecretsBackend.AWS_SM])
        return order

    def _resolve_from_file(self, key: str) -> str | None:
        try:
            from dotenv import dotenv_values
        except ImportError:
            return None
        paths = self.config.env_file_paths
        if not paths:
            paths = [
                str(Path.home() / ".rig" / "relay" / ".env"),
                str(Path(".rig") / "relay" / ".env"),
            ]
        for path_str in paths:
            try:
                values = dotenv_values(path_str)
                val = values.get(key)
                if val is not None:
                    return val
            except Exception:
                continue
        return None

    def _resolve_vault(self, key: str) -> _SecretResult | None:
        if not self.config.vault_addr:
            return _SecretResult(
                key=key,
                value=None,
                token_present=False,
                backend_used=SecretsBackend.VAULT,
            )
        return _SecretResult(
            key=key,
            value="not_implemented: Vault integration pending",
            token_present=False,
            backend_used=SecretsBackend.VAULT,
        )

    def _resolve_aws(self, key: str) -> _SecretResult | None:
        if not self.config.aws_region:
            return _SecretResult(
                key=key,
                value=None,
                token_present=False,
                backend_used=SecretsBackend.AWS_SM,
            )
        return _SecretResult(
            key=key,
            value="not_implemented: AWS Secrets Manager integration pending",
            token_present=False,
            backend_used=SecretsBackend.AWS_SM,
        )

    def _resolve_gcp(self, key: str) -> _SecretResult | None:
        if not self.config.gcp_project:
            return _SecretResult(
                key=key,
                value=None,
                token_present=False,
                backend_used=SecretsBackend.GCP_SM,
            )
        return _SecretResult(
            key=key,
            value="not_implemented: GCP Secret Manager integration pending",
            token_present=False,
            backend_used=SecretsBackend.GCP_SM,
        )


__all__ = ["SecretsBackend", "SecretsConfig", "SecretsResolver"]

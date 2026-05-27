"""Typed PostgreSQL connection configuration with secrets masking."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PostgresConnectionConfig(BaseModel):
    """PostgreSQL connection configuration.

    Secrets (password, DSN) are masked in repr and logs via SecretStr.
    The DSN is stored as a SecretStr to prevent accidental exposure;
    call ``dsn.get_secret_value()`` to use it.
    """

    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="127.0.0.1", description="PostgreSQL host")
    port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL port")
    dbname: str = Field(default="rig_relay", description="Database name")
    user: str = Field(default="rig_relay", description="Database user")
    password: SecretStr = Field(
        default=SecretStr(""), description="Database password (masked in logs)"
    )
    schema_name: str = Field(
        default="operational",
        description="PostgreSQL schema for operational projections",
    )
    connect_timeout: int = Field(
        default=10, ge=1, le=60, description="Connection timeout in seconds"
    )
    autocommit: bool = Field(
        default=True, description="Use autocommit mode to prevent idle-in-transaction"
    )
    application_name: str = Field(
        default="rig-relay-data-plane",
        description="Application name for pg_stat_activity",
    )

    def build_dsn(self) -> str:
        """Build a psycopg-compatible connection string.

        Secrets are unmasked here intentionally — this is the only place
        they are read for actual connection use.

        Empty field values are omitted to avoid DSN parsing issues with
        psycopg (e.g., ``user=`` causes ``connect_timeout`` to be parsed
        as the username).
        """
        pw = self.password.get_secret_value()
        params: list[str] = []
        if self.host:
            params.append(f"host={self.host}")
        if self.port:
            params.append(f"port={self.port}")
        if self.dbname:
            params.append(f"dbname={self.dbname}")
        if self.user:
            params.append(f"user={self.user}")
        if self.connect_timeout:
            params.append(f"connect_timeout={self.connect_timeout}")
        if self.application_name:
            params.append(f"application_name={self.application_name}")
        if pw:
            params.append(f"password={pw}")
        return " ".join(params)

    def safe_summary(self) -> dict[str, Any]:
        """Return a content-light summary safe for logs and audit output."""
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "schema_name": self.schema_name,
            "application_name": self.application_name,
            "autocommit": self.autocommit,
            "connect_timeout": self.connect_timeout,
            "password_configured": bool(self.password.get_secret_value()),
        }

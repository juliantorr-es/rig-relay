"""PostgreSQL configuration tests — masking, validation, safe summary."""

from __future__ import annotations

from pydantic import SecretStr
import pytest

from rig_relay.data_plane.postgres._config import PostgresConnectionConfig


class TestPostgresConnectionConfig:
    def test_default_values(self) -> None:
        config = PostgresConnectionConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 5432
        assert config.dbname == "rig_relay"
        assert config.schema_name == "operational"
        assert config.autocommit is True

    def test_build_dsn_no_password(self) -> None:
        config = PostgresConnectionConfig(
            host="localhost", port=5432, dbname="mydb", user="myuser"
        )
        dsn = config.build_dsn()
        assert "host=localhost" in dsn
        assert "port=5432" in dsn
        assert "dbname=mydb" in dsn
        assert "user=myuser" in dsn
        assert "password" not in dsn

    def test_build_dsn_with_password(self) -> None:
        config = PostgresConnectionConfig(
            password=SecretStr("s3cret"),
            host="localhost",
            port=5432,
            dbname="mydb",
            user="myuser",
        )
        dsn = config.build_dsn()
        assert "password=s3cret" in dsn

    def test_password_masked_in_repr(self) -> None:
        config = PostgresConnectionConfig(password=SecretStr("s3cret"))
        repr_str = repr(config)
        assert "s3cret" not in repr_str
        assert "SecretStr" in repr_str

    def test_safe_summary_masks_password(self) -> None:
        config = PostgresConnectionConfig(password=SecretStr("s3cret"))
        summary = config.safe_summary()
        assert "s3cret" not in str(summary)
        assert summary["password_configured"] is True
        assert summary["host"] == "127.0.0.1"

    def test_safe_summary_no_password(self) -> None:
        config = PostgresConnectionConfig()
        summary = config.safe_summary()
        assert summary["password_configured"] is False

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PostgresConnectionConfig.model_validate({
                "host": "h",
                "some_unknown_field": 42,
            })

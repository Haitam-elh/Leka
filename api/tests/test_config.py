"""The environment contract.

A missing variable must stop the process on startup, naming what is missing.
These tests exist because the alternative — a None discovered in production
three weeks later — is the failure mode this whole file was written against.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leka.core.config import ConfigurationError, Settings, _load_settings

REQUIRED = ("LEKA_DATABASE_URL", "LEKA_REDIS_URL", "LEKA_SECRET_KEY")

VALID = {
    "database_url": "postgresql+asyncpg://leka:leka@127.0.0.1:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "not-a-real-secret",
}


def test_optional_settings_fall_back_to_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With only the required variables set, the rest must be usable.

    The optional variables are deleted explicitly: this test asserts what the
    DEFAULTS are, so it must not read whatever the surrounding shell happens
    to export. CI sets LEKA_ENVIRONMENT=ci, and an earlier version of this
    test failed there for exactly that reason.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("LEKA_ENVIRONMENT", "LEKA_DEBUG", "LEKA_LOG_LEVEL", "LEKA_LOG_FORMAT"):
        monkeypatch.delenv(name, raising=False)

    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]

    assert config.environment == "local"
    assert config.api_v1_prefix == "/api/v1"
    assert config.debug is False
    assert config.is_production is False


def test_environment_variable_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings must actually read the environment, not just hold defaults."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("LEKA_ENVIRONMENT", "production")

    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]

    assert config.environment == "production"
    assert config.is_production is True


def test_missing_required_variables_are_all_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One crash naming three missing variables beats three crashes."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError) as caught:
        _load_settings()

    message = str(caught.value)
    for name in REQUIRED:
        assert name in message
    assert ".env.example" in message


def test_synchronous_dsn_is_rejected() -> None:
    """postgresql:// would fail much later, deep inside the first query."""
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(_env_file=None, **{**VALID, "database_url": "postgresql://u:p@h:5432/d"})  # type: ignore[arg-type]


def test_secret_is_not_printable() -> None:
    """A secret must not leak into a log line or a traceback."""
    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]
    assert "not-a-real-secret" not in repr(config)
    assert config.secret_key.get_secret_value() == "not-a-real-secret"

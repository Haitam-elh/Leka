"""The environment contract.

A missing variable must stop the process on startup, naming what is missing.
These tests exist because the alternative — a None discovered in production
three weeks later — is the failure mode this whole file was written against.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from leka.core.config import REPO_ROOT, ConfigurationError, Settings, _load_settings
from leka.core.settings.database import DatabaseSettings
from leka.core.settings.email import EmailSettings
from leka.core.settings.model_access import ModelAccessSettings
from leka.core.settings.runtime import RuntimeSettings
from leka.core.settings.security import SecuritySettings
from leka.core.settings.storage import StorageSettings

REQUIRED = (
    "LEKA_DATABASE_URL",
    "LEKA_REDIS_URL",
    "LEKA_SECRET_KEY",
    "LEKA_ENCRYPTION_KEYS",
)

VALID = {
    "database_url": "postgresql+asyncpg://leka:leka@127.0.0.1:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "not-a-real-secret",
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}

# Production asks for more than the required four. The startup guards exist
# for settings that work perfectly in every test and quietly stop protecting
# anyone in production — a cookie without Secure, an object store on a
# container's ephemeral disk. Anything asserting something ABOUT production
# has to satisfy them first.
PRODUCTION = {
    **VALID,
    "object_store": "s3",
    "s3_bucket": "leka-payloads",
    "s3_access_key_id": "not-a-real-key",
    "s3_secret_access_key": "not-a-real-secret",
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

    config = Settings(_env_file=None, **PRODUCTION)  # type: ignore[arg-type]

    assert config.environment == "production"
    assert config.is_production is True


def test_production_refuses_a_local_object_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A container's filesystem is not durable storage.

    LocalObjectStore is the right default everywhere else — it is what makes
    the platform runnable with no account anywhere. In production it would
    write customer payloads to an ephemeral disk: the next deploy takes them
    all, and every raw_payloads row is left pointing at nothing. Silently.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("LEKA_ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="LEKA_OBJECT_STORE=local in production"):
        Settings(_env_file=None, **VALID)  # type: ignore[arg-type]


def test_production_names_every_missing_s3_setting_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One crash naming three missing variables beats three deploys."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("LEKA_ENVIRONMENT", "production")

    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None, object_store="s3", **VALID)  # type: ignore[arg-type]

    message = str(refused.value)
    assert "LEKA_S3_BUCKET" in message
    assert "LEKA_S3_ACCESS_KEY_ID" in message
    assert "LEKA_S3_SECRET_ACCESS_KEY" in message


def test_a_local_object_store_is_fine_everywhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must bite in production and nowhere else, or it would make
    the default unusable and someone would configure their way around it."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for environment in ("local", "ci", "staging"):
        monkeypatch.setenv("LEKA_ENVIRONMENT", environment)
        config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]
        assert config.object_store == "local"
        assert config.object_store_root.is_absolute()


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


# ── Model access ─────────────────────────────────────────────────────────────


def test_no_model_is_configured_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The platform boots and serves without a model. Rule 7 says only
    leka.capabilities may care."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("LEKA_LLM_PROVIDER", "LEKA_ANTHROPIC_API_KEY", "LEKA_MISTRAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]

    # Mistral by default: the commercial argument is "your data stays in
    # Europe", and that only holds if the European path is the one exercised
    # every day rather than an option nobody runs.
    assert config.llm_provider == "mistral"
    assert config.has_model_access is False
    assert config.llm_api_key is None


@pytest.mark.parametrize(
    ("provider", "variable"),
    [("anthropic", "LEKA_ANTHROPIC_API_KEY"), ("mistral", "LEKA_MISTRAL_API_KEY")],
)
def test_the_selected_provider_key_is_the_one_returned(
    monkeypatch: pytest.MonkeyPatch, provider: str, variable: str
) -> None:
    """Two providers from the start: an abstraction validated against one
    implementation only fits that one."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("LEKA_LLM_PROVIDER", provider)
    monkeypatch.setenv(variable, "a-real-looking-key")

    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]

    assert config.has_model_access is True
    assert config.llm_api_key is not None
    assert config.llm_api_key.get_secret_value() == "a-real-looking-key"


def test_an_empty_key_counts_as_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """.env.example ships these blank, so a copied .env yields "" rather than
    an absent variable. Without this, a key nobody filled in reads as
    configured and the failure moves to the first model call."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("LEKA_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LEKA_MISTRAL_API_KEY", "   ")

    config = Settings(_env_file=None, **VALID)  # type: ignore[arg-type]

    assert config.anthropic_api_key is None
    assert config.mistral_api_key is None
    assert config.has_model_access is False


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "llm_provider": "openai"})  # type: ignore[arg-type]


# ── Credential encryption keys ───────────────────────────────────────────────


def test_a_malformed_encryption_key_stops_startup() -> None:
    """Fernet only objects when first used — which would be the first sync of
    the first connector, hours after deploy, in a worker log nobody watches."""
    with pytest.raises(ValidationError, match="Fernet"):
        Settings(_env_file=None, **{**VALID, "encryption_keys": ["not-a-fernet-key"]})  # type: ignore[arg-type]


def test_at_least_one_encryption_key_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "encryption_keys": []})  # type: ignore[arg-type]


# ── The settings split, and the trap inside it ───────────────────────────────


DOMAIN_MIXINS = (
    RuntimeSettings,
    DatabaseSettings,
    SecuritySettings,
    EmailSettings,
    ModelAccessSettings,
    StorageSettings,
)


def test_no_two_domains_define_the_same_method_name() -> None:
    """A name collision between mixins is silent, and it disables a validator.

    Python resolves methods by MRO: two domains defining
    `_blank_is_not_configured` leave exactly one alive, and the other's
    fields simply stop being validated. No error, no warning, nothing from
    pydantic.

    This is not hypothetical. It happened while the split was being written:
    three domains used that exact name, only the email one survived, and
    blank S3 and model keys went back to being "" — which is the bug the
    validator exists to prevent, reintroduced by the refactor meant to be
    behaviour-neutral. The test below caught it; this one makes sure nobody
    has to be that lucky twice.
    """
    seen: dict[str, str] = {}
    collisions: list[str] = []

    for mixin in DOMAIN_MIXINS:
        for name, value in vars(mixin).items():
            if name.startswith("__") or not callable(getattr(value, "__func__", value)):
                continue
            if name in seen:
                collisions.append(f"{name}: {seen[name]} and {mixin.__name__}")
            seen[name] = mixin.__name__

    assert not collisions, (
        "two settings domains define the same method, and only one of them "
        "will run:\n  " + "\n  ".join(collisions) + "\n\nPrefix it with the "
        "domain — _blank_s3_field_is_not_configured, not _blank_is_not_configured."
    )


def test_every_domain_is_assembled_into_settings() -> None:
    """A domain file nobody mixed in is a file whose settings do not exist.

    It would import cleanly, read cleanly, and have no effect whatsoever —
    the fields simply would not be on Settings.
    """
    missing = [mixin.__name__ for mixin in DOMAIN_MIXINS if mixin not in Settings.__mro__]
    assert not missing, f"domain settings declared but never mixed in: {missing}"


def test_every_declared_field_belongs_to_a_domain() -> None:
    """Settings itself declares no fields; they all live in a domain file.

    If a field appears directly on Settings, the next person adding one will
    follow that example, and the file goes back to being the place where two
    tickets collide.
    """
    own_fields = [
        name
        for name, value in vars(Settings).get("__annotations__", {}).items()
        if not name.startswith("_") and name != "model_config"
    ]
    assert not own_fields, (
        f"these fields are declared on Settings rather than in a domain file: "
        f"{own_fields}. Put them in core/settings/<domain>.py."
    )


# ── The documentation cannot fall behind ─────────────────────────────────────

# Read by the test suite and CI, never by the application. Documented in
# their own section of docs/configuration.md.
TEST_ONLY_VARIABLES = frozenset(
    {
        "LEKA_PYTHON",
        "LEKA_REQUIRE_S3_TESTS",
        "LEKA_S3_TEST_ACCESS_KEY",
        "LEKA_S3_TEST_ENDPOINT",
        "LEKA_S3_TEST_SECRET_KEY",
        "LEKA_S3_TEST_TARGET",
    }
)


def test_every_setting_is_documented_and_nothing_else() -> None:
    """A variable nobody documented is one an operator meets in a stack trace;
    a documented variable that no longer exists is one they set for nothing."""
    doc = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"LEKA_[A-Z0-9_]+", doc))
    expected = {f"LEKA_{name.upper()}" for name in Settings.model_fields}

    assert not expected - documented, (
        f"undocumented: {sorted(expected - documented)}. Add them to docs/configuration.md."
    )
    stale = documented - expected - TEST_ONLY_VARIABLES
    assert not stale, f"docs/configuration.md names variables that do not exist: {sorted(stale)}"

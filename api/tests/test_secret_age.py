"""Knowing when a secret has lived too long, and saying so.

A secret does not expire by itself. "Rotation and expiration can be managed"
comes down to knowing when one is past its lifetime. Each secret declares
that lifetime next to its field (RotateEvery); when it was last rotated is a
fact about one environment, in LEKA_SECRETS_ROTATED_ON.

A warning, never a refusal to start: stopping because a key is a day past
its lifetime would be manufacturing an outage.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from leka.core.config import OverdueSecret, Settings, settings
from leka.core.logging import configure_logging
from leka.core.settings import RotateEvery
from tests.test_secret_access import SECRETS

TODAY = date(2026, 9, 22)
FIELDS = {name for name, why in SECRETS.items() if why != "a property returning a secret"}

VALID: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://leka:a-real-password@db:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": "not-a-real-secret",
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}


def _in(environment: str, **rotated_on: date) -> Settings:
    """Only the required secrets configured, each dated TODAY unless overridden.

    Built from nothing rather than copied from the running settings, so what
    a developer has in their .env cannot change what these tests see. Built
    as local, then moved: production's own startup guards — an S3 store,
    Secure cookies — are not what these tests are about.
    """
    dates = dict.fromkeys(("secret_key", "encryption_keys", "database_url"), TODAY)
    built = Settings(_env_file=None, **VALID, secrets_rotated_on={**dates, **rotated_on})
    return built.model_copy(update={"environment": environment})


def test_a_secret_past_its_lifetime_is_reported() -> None:
    overdue = _in("production", secret_key=TODAY - timedelta(days=400)).overdue_secrets(TODAY)

    assert overdue == [OverdueSecret("secret_key", 400, 365)]


def test_a_fresh_secret_is_not() -> None:
    assert _in("production").overdue_secrets(TODAY) == []


def test_a_configured_secret_of_unknown_age_is_reported() -> None:
    """Not knowing how old a production key is, is itself the finding."""
    unknown = _in("production").model_copy(
        update={"secrets_rotated_on": {"encryption_keys": TODAY, "database_url": TODAY}}
    )

    assert unknown.overdue_secrets(TODAY) == [OverdueSecret("secret_key", None, 365)]


def test_a_secret_that_is_not_configured_needs_no_date() -> None:
    """No SMTP password, no Redis password here: nothing to rotate, nothing to say."""
    reported = {item.setting for item in _in("production").overdue_secrets(TODAY)}

    assert "smtp_password" not in reported
    assert "redis_url" not in reported


@pytest.mark.parametrize("environment", ["local", "ci"])
def test_throwaway_environments_are_left_alone(environment: str) -> None:
    ancient = _in(environment, secret_key=TODAY - timedelta(days=4000))

    assert ancient.overdue_secrets(TODAY) == []


def test_staging_is_checked_like_production() -> None:
    old = _in("staging", secret_key=TODAY - timedelta(days=400))

    assert old.overdue_secrets(TODAY) == [OverdueSecret("secret_key", 400, 365)]


# ── A typo must not switch the check off ─────────────────────────────────────


def test_an_unknown_name_stops_startup() -> None:
    """`secret-key` instead of `secret_key` would record the age of nothing."""
    with pytest.raises(ValidationError, match="LEKA_SECRETS_ROTATED_ON"):
        Settings(_env_file=None, **VALID, secrets_rotated_on={"secret-key": TODAY})


def test_a_date_in_the_future_stops_startup() -> None:
    """2062 for 2026 would make a secret look fresh for decades."""
    later = datetime.now(UTC).date() + timedelta(days=30)

    with pytest.raises(ValidationError, match="future"):
        Settings(_env_file=None, **VALID, secrets_rotated_on={"secret_key": later})


# ── Every secret declares its lifetime ───────────────────────────────────────


def test_every_secret_field_declares_a_lifetime() -> None:
    """A secret without one would never be reported, however old."""
    declared = {
        name
        for name, field in Settings.model_fields.items()
        if any(isinstance(marker, RotateEvery) for marker in field.metadata)
    }
    assert FIELDS, "the secret inventory is empty — the check would pass over nothing"
    assert not FIELDS - declared, f"add RotateEvery(days=...) to: {sorted(FIELDS - declared)}"
    assert not declared - FIELDS, f"RotateEvery on fields that hold no secret: {declared - FIELDS}"


# ── And startup actually says so ─────────────────────────────────────────────


async def test_startup_warns_about_an_overdue_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A check nobody calls protects nothing. This runs the real lifespan."""
    import leka.main

    today = datetime.now(UTC).date()
    old = _in("production", secret_key=today - timedelta(days=4000)).model_copy(
        update={"log_level": "INFO", "log_format": "json"}
    )
    monkeypatch.setattr(leka.main, "settings", old)
    try:
        async with leka.main.lifespan(leka.main.app):
            pass
    finally:
        configure_logging(settings)

    written = capsys.readouterr().out
    assert "secret_rotation_overdue" in written, f"no warning at startup:\n{written}"
    assert '"setting": "secret_key"' in written

"""No configured secret reaches a log line, whatever key carries it.

core/logging.py masks by KEY — `password=`, `token=`, `api_key=`. That misses
a secret carried under an innocent name:

    logger.info("connecting", value=settings.s3_secret_access_key.get_secret_value())

`value` is on no list. These tests run that line, and its cousins, through
the REAL processor chain and read what was written. Not with
structlog.testing.capture_logs, which skips the processors and would pass
whether the masking worked or not.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog
from pydantic import PostgresDsn, SecretStr

from leka.core.config import Settings, settings
from leka.core.logging import MASK, configure_logging

S3_SECRET = "s3-secret-that-must-never-be-logged"
DB_PASSWORD = "db-password-that-must-never-be-logged"


@pytest.fixture(params=["console", "json"])
def configured(request: pytest.FixtureRequest) -> Iterator[Settings]:
    """Settings holding known secrets, and logging configured from them.

    Both renderers: a URL object is turned into text by the renderer, and
    each renderer does it its own way. Restored afterwards, because the
    structlog configuration is process-wide and the next test must not
    inherit these fakes.
    """
    fake = settings.model_copy(
        update={
            "log_format": request.param,
            "s3_secret_access_key": SecretStr(S3_SECRET),
            "database_url": PostgresDsn(f"postgresql+asyncpg://leka:{DB_PASSWORD}@db:5432/leka"),
        }
    )
    configure_logging(fake)
    yield fake
    configure_logging(settings)


def test_a_secret_under_an_innocent_key_is_masked(
    configured: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The line from the ticket, exactly."""
    assert configured.s3_secret_access_key is not None
    structlog.get_logger("masking").info(
        "connecting", value=configured.s3_secret_access_key.get_secret_value()
    )

    written = capsys.readouterr().out
    assert S3_SECRET not in written, f"the secret reached the log:\n{written}"
    assert MASK in written, f"the line was dropped rather than masked:\n{written}"


def test_a_secret_inside_a_sentence_is_masked(
    configured: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    structlog.get_logger("masking").warning(f"upload refused for key {S3_SECRET} at 3am")

    written = capsys.readouterr().out
    assert S3_SECRET not in written, f"the secret reached the log:\n{written}"
    assert "upload refused for key" in written, "the rest of the message must survive"


def test_a_password_inside_a_connection_url_is_masked(
    configured: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The URL object itself, not a string: text only once a renderer makes it so."""
    structlog.get_logger("masking").info("database", url=configured.database_url)

    written = capsys.readouterr().out
    assert DB_PASSWORD not in written, f"the password reached the log:\n{written}"
    assert "db:5432" in written, "the rest of the URL must survive"


def test_a_secret_in_a_traceback_is_masked(
    configured: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """An exception message is text like any other, and a traceback is logged whole."""
    try:
        raise RuntimeError(f"bucket refused {S3_SECRET}")
    except RuntimeError:
        structlog.get_logger("masking").exception("upload_failed")

    written = capsys.readouterr().out
    assert S3_SECRET not in written, f"the secret reached the log:\n{written}"
    assert "upload_failed" in written, "the line was never logged"


def test_a_short_value_is_not_masked(capsys: pytest.CaptureFixture[str]) -> None:
    """The local database password is "leka". Masked by value, the product's
    own name would vanish from every line, and a marker everywhere is a
    marker nobody reads."""
    local = settings.model_copy(
        update={"database_url": PostgresDsn("postgresql+asyncpg://leka:leka@db:5432/leka")}
    )
    configure_logging(local)
    try:
        structlog.get_logger("masking").info("leka_starting")
    finally:
        configure_logging(settings)

    assert "leka_starting" in capsys.readouterr().out

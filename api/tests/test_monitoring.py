"""What leaves the building when something breaks.

The one test on this file that is not negotiable: Sentry sends the local
variables of every frame in a traceback, and `settings` is a local variable
in more places than anyone can enumerate. It holds the database password,
the Fernet keys and the session signing key. LEKA-335 built a masker so a
secret can never reach a log line; an error reporter that bypassed it would
hand a third party exactly what that ticket was written to protect.

So this asserts on the shape Sentry actually produces — an exception, its
frames, and a `vars` dictionary six levels down — rather than on a flat
dictionary that would pass whatever the implementation did.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, cast

import pytest
import sentry_sdk
from pydantic import ValidationError

from leka.core.config import Settings
from leka.core.logging import MASK, configure_logging
from leka.platform.monitoring import _scrub_event, configure_monitoring

if TYPE_CHECKING:  # pragma: no cover
    from sentry_sdk.types import Event

DATABASE_PASSWORD = "an-extremely-secret-database-password"
SIGNING_KEY = "another-secret-value-entirely"

VALID: dict[str, Any] = {
    "database_url": f"postgresql+asyncpg://leka:{DATABASE_PASSWORD}@127.0.0.1:5432/leka",
    "redis_url": "redis://127.0.0.1:6379/0",
    "secret_key": SIGNING_KEY,
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}


@pytest.fixture(autouse=True)
def _no_live_client_afterwards() -> Iterator[None]:
    """Some tests here start Sentry for real, with a DSN that exists only in
    this file. Left running, it would try to send every deliberate failure
    in the rest of the suite over the network — from CI, to sentry.io."""
    yield
    sentry_sdk.init()


@pytest.fixture
def configured() -> Settings:
    """A settings object whose secrets the masker knows about."""
    settings = Settings(_env_file=None, **VALID)
    configure_logging(settings)
    return settings


def sentry_shaped_event() -> Event:
    """An event with a secret where Sentry really puts one.

    Not a flat dictionary: the value that gets someone fired sits inside
    exception → values → stacktrace → frames → vars, which is the depth the
    log processor never had to walk.
    """
    return cast(
        "Event",
        {
            "level": "error",
            "environment": "staging",
            "exception": {
                "values": [
                    {
                        "type": "OperationalError",
                        "value": f"could not connect to {VALID['database_url']}",
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "connect",
                                    "vars": {
                                        "url": VALID["database_url"],
                                        "signing_key": SIGNING_KEY,
                                        "retries": 3,
                                        "nested": [{"deep": SIGNING_KEY}],
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        },
    )


def flatten(value: object) -> str:
    return repr(value)


class TestScrubbing:
    def test_no_secret_survives_anywhere_in_the_event(self, configured: Settings) -> None:
        scrubbed = _scrub_event(sentry_shaped_event(), {})

        assert scrubbed is not None
        text = flatten(scrubbed)
        assert DATABASE_PASSWORD not in text
        assert SIGNING_KEY not in text
        assert MASK in text

    def test_it_reaches_the_deepest_frame(self, configured: Settings) -> None:
        scrubbed = _scrub_event(sentry_shaped_event(), {})

        assert scrubbed is not None
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert frame["vars"]["signing_key"] == MASK
        assert frame["vars"]["nested"][0]["deep"] == MASK

    def test_it_keeps_everything_that_is_not_a_secret(self, configured: Settings) -> None:
        scrubbed = _scrub_event(sentry_shaped_event(), {})

        assert scrubbed is not None
        # An event stripped of its context is an event nobody can act on.
        assert scrubbed["level"] == "error"
        assert scrubbed["environment"] == "staging"
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert frame["function"] == "connect"
        assert frame["vars"]["retries"] == 3

    def test_a_structure_that_refers_to_itself_does_not_hang(self, configured: Settings) -> None:
        """The worst possible moment to take the process down is while it is
        reporting the error that caused it."""
        event: dict[str, Any] = {"extra": {}}
        event["extra"]["self"] = event

        assert _scrub_event(cast("Event", event), {}) is not None


class TestConfiguration:
    def test_does_nothing_without_a_project(self, configured: Settings) -> None:
        assert configured.sentry_dsn is None
        assert configure_monitoring(configured) is False

    def test_starts_when_a_project_is_configured(self) -> None:
        settings = Settings(
            _env_file=None,
            sentry_dsn="https://public@o0.ingest.sentry.io/0",
            release="abc1234",
            **VALID,
        )
        configure_logging(settings)

        assert configure_monitoring(settings) is True

    def test_never_sends_personal_data(self) -> None:
        """Typed as unchangeable: PII here is a customer's e-mail address on
        a third party's servers, which is a data-protection decision."""
        with pytest.raises(ValidationError):
            Settings(_env_file=None, sentry_send_default_pii=True, **VALID)

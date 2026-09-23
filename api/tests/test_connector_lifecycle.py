"""The lifecycle of a source, pair by pair (LEKA-344).

Every (status, event) pair is either in the table or refused — no third
option, and no pair left untested. The table is the specification; these
tests pin the pairs that matter by name, then sweep all the others.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from leka.connectors import InvalidTransitionError, LifecycleEvent, SourceStatus, next_status
from leka.connectors.lifecycle import TRANSITIONS, fingerprint

S = SourceStatus
E = LifecycleEvent

VALID = [
    (S.DRAFT, E.TEST_SUCCEEDED, S.TESTED),
    (S.DRAFT, E.TEST_FAILED, S.DRAFT),
    (S.TESTED, E.TEST_FAILED, S.DRAFT),
    (S.TESTED, E.ACTIVATE, S.ACTIVE),
    (S.DISABLED, E.ACTIVATE, S.ACTIVE),
    (S.ACTIVE, E.TEST_FAILED, S.ERROR),
    (S.ERROR, E.TEST_SUCCEEDED, S.ACTIVE),
    (S.ACTIVE, E.DEGRADED, S.DEGRADED),
    (S.DEGRADED, E.HEALTHY, S.ACTIVE),
    (S.ACTIVE, E.UNHEALTHY, S.ERROR),
    (S.ACTIVE, E.RECONFIGURE, S.DRAFT),
    (S.DISABLED, E.RECONFIGURE, S.DRAFT),
    (S.ACTIVE, E.DISABLE, S.DISABLED),
    (S.DRAFT, E.DISABLE, S.DISABLED),
    # Health never activates what was not activated.
    (S.DRAFT, E.HEALTHY, S.DRAFT),
    (S.TESTED, E.UNHEALTHY, S.TESTED),
]

INVALID = [
    (S.DRAFT, E.ACTIVATE),  # untested
    (S.ACTIVE, E.ACTIVATE),  # already on
    (S.ERROR, E.ACTIVATE),
    (S.DEGRADED, E.ACTIVATE),
    (S.DISABLED, E.DISABLE),
]


@pytest.mark.parametrize(("current", "event", "expected"), VALID)
def test_a_valid_transition(current: S, event: E, expected: S) -> None:
    assert next_status(current, event) is expected


@pytest.mark.parametrize(("current", "event"), INVALID)
def test_an_invalid_transition_is_refused(current: S, event: E) -> None:
    with pytest.raises(InvalidTransitionError):
        next_status(current, event)


@pytest.mark.parametrize("current", list(SourceStatus))
@pytest.mark.parametrize("event", list(LifecycleEvent))
def test_every_pair_is_either_in_the_table_or_refused(current: S, event: E) -> None:
    if (current, event) in TRANSITIONS:
        assert next_status(current, event) is TRANSITIONS[(current, event)]
    else:
        with pytest.raises(InvalidTransitionError):
            next_status(current, event)


def test_the_fingerprint_follows_the_config_and_the_credentials_revision() -> None:
    config: dict[str, object] = {"organization": "acme"}
    first = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    second = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)

    assert fingerprint(config, first) == fingerprint(dict(config), first)
    assert fingerprint(config, first) != fingerprint({"organization": "other"}, first)
    assert fingerprint(config, first) != fingerprint(config, second)

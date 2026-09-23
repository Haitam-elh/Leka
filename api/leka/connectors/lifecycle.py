"""The lifecycle of a source, in one table.

    draft ──test ok──▶ tested ──activate──▶ active ◀──▶ degraded / error
      ▲                                        │
      └──── config or credentials changed ─────┘          any ──▶ disabled

Every status change goes through `next_status`, and nothing else writes
`sources.status`. A pair that is not in the table is refused — the API
answers 409 — so an impossible state cannot be reached by a route that
forgot a check. Each pair is tested on its own (tests/test_connector_lifecycle.py).

Activation has one more condition the table cannot express, checked by the
service: the last successful test must have been run against the config
and credentials the source has NOW (see `fingerprint`).
"""

from __future__ import annotations

import enum
import hashlib
import json
from datetime import datetime

from leka.connectors.models import SourceStatus


class LifecycleEvent(enum.StrEnum):
    TEST_SUCCEEDED = "test_succeeded"
    TEST_FAILED = "test_failed"
    ACTIVATE = "activate"
    DISABLE = "disable"
    RECONFIGURE = "reconfigure"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


S = SourceStatus
E = LifecycleEvent
_ACTIVATED = (S.ACTIVE, S.DEGRADED, S.ERROR)
_ALL = tuple(SourceStatus)

TRANSITIONS: dict[tuple[SourceStatus, LifecycleEvent], SourceStatus] = {
    # A test proves the settings; an activated source that passes is back up.
    (S.DRAFT, E.TEST_SUCCEEDED): S.TESTED,
    (S.TESTED, E.TEST_SUCCEEDED): S.TESTED,
    **{(status, E.TEST_SUCCEEDED): S.ACTIVE for status in _ACTIVATED},
    (S.DISABLED, E.TEST_SUCCEEDED): S.DISABLED,
    # A failed test takes back the proof; an activated source is in error.
    (S.DRAFT, E.TEST_FAILED): S.DRAFT,
    (S.TESTED, E.TEST_FAILED): S.DRAFT,
    **{(status, E.TEST_FAILED): S.ERROR for status in _ACTIVATED},
    (S.DISABLED, E.TEST_FAILED): S.DISABLED,
    # Only a tested source is switched on — or a disabled one, back on.
    (S.TESTED, E.ACTIVATE): S.ACTIVE,
    (S.DISABLED, E.ACTIVATE): S.ACTIVE,
    **{(status, E.DISABLE): S.DISABLED for status in _ALL if status is not S.DISABLED},
    # New settings are unproven settings, whatever the source was.
    **{(status, E.RECONFIGURE): S.DRAFT for status in _ALL},
    # Health moves only a source that was activated; it does not activate one.
    **{(status, E.HEALTHY): S.ACTIVE for status in _ACTIVATED},
    **{(status, E.DEGRADED): S.DEGRADED for status in _ACTIVATED},
    **{(status, E.UNHEALTHY): S.ERROR for status in _ACTIVATED},
    **{
        (status, event): status
        for status in (S.DRAFT, S.TESTED, S.DISABLED)
        for event in (E.HEALTHY, E.DEGRADED, E.UNHEALTHY)
    },
}


class InvalidTransitionError(Exception):
    def __init__(self, current: SourceStatus, event: LifecycleEvent) -> None:
        super().__init__(f"cannot {event.value} a source that is {current.value}")
        self.current = current
        self.event = event


def next_status(current: SourceStatus, event: LifecycleEvent) -> SourceStatus:
    try:
        return TRANSITIONS[(current, event)]
    except KeyError as error:
        raise InvalidTransitionError(current, event) from error


def fingerprint(config: dict[str, object], credentials_rotated_at: datetime | None) -> str:
    """What a test was run against: the config, and WHICH credentials.

    The credentials enter by their revision — when they were last set — not
    by their value: a hash of a secret stored in the database is a copy of
    the secret, a little harder to use. A key rotation re-encrypts without
    changing the revision, so it does not force a retest; replacing the
    token does.
    """
    material = json.dumps(
        {
            "config": config,
            "credentials": credentials_rotated_at.isoformat() if credentials_rotated_at else None,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()

"""How long a raw payload is ours to keep.

ONE PLACE. Not an `if` in the writer, another in the sweep and a third in
whatever reads them next — a retention rule scattered across three files is
a rule that is three different rules within a year, and the one nobody
changed is the one that keeps a customer's data past what we promised.

The shape is deliberately small: a class of data maps to a duration, and
everything else asks this module. Writing a payload asks it for an expiry;
the sweep asks nothing at all, because the expiry is already a column.

WHY THE NUMBERS DIFFER BY SOURCE. Code, tickets and documentation describe
structure: they change slowly, they are small, and re-reading one from six
weeks ago is how a question about "when did this change?" gets answered.
Observability is the opposite — enormous, and worthless within days, because
nobody asks what p99 was last quarter from a raw log export.

Ninety days and thirty. The long end is bounded by what a customer contract
will say and the short end by what an incident investigation needs, which is
days rather than weeks.

The email tokens of LEKA-330 are not here and must not be added: they carry
their own expiry and their own sweep, in leka.identity.tasks. Audit and
execution traces will bring their own when their tickets do.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from leka.connectors import SourceKind
from leka.core.config import settings

# What a source kind is worth keeping, in days.
#
# Structure — slow-moving, small, worth re-reading.
# Observability — enormous, stale in days.
DEFAULT_RETENTION_DAYS: dict[SourceKind, int] = {
    SourceKind.GITHUB: 90,
    SourceKind.GITLAB: 90,
    SourceKind.BITBUCKET: 90,
    SourceKind.JIRA: 90,
    SourceKind.CONFLUENCE: 90,
    SourceKind.LINEAR: 90,
    SourceKind.NOTION: 90,
    SourceKind.ASANA: 90,
    SourceKind.TRELLO: 90,
    SourceKind.CLICKUP: 90,
    SourceKind.MONDAY: 90,
    SourceKind.SLAB: 90,
    SourceKind.GURU: 90,
    SourceKind.GOOGLE_WORKSPACE: 90,
    SourceKind.MICROSOFT_365: 90,
    # Incidents and the services they are about: small, and what a
    # post-mortem reads weeks later.
    SourceKind.PAGERDUTY: 90,
    # A database's catalogue: small, and what explains a table for as long
    # as the table lives.
    SourceKind.POSTGRESQL: 90,
    SourceKind.MYSQL: 90,
    SourceKind.MONGODB: 90,
    SourceKind.SUPABASE: 90,
    SourceKind.SLACK: 30,
    SourceKind.AWS: 30,
    SourceKind.AZURE: 30,
    SourceKind.GCP: 30,
    SourceKind.DATADOG: 30,
    SourceKind.GRAFANA: 30,
}

# A source kind nobody thought about must not mean "keep for ever". The
# shortest policy is the safe default: keeping too little is a resync, and
# keeping too much is a promise broken.
FALLBACK_RETENTION_DAYS = 30


def retention_days(kind: SourceKind) -> int:
    """How many days this kind of payload is kept.

    Configuration wins over the table above, so a customer contract or a
    regulator can move a number without a deploy. The value is bounded at
    startup — see Settings._retention_is_within_reason — so nothing here has
    to defend against a 0 that would delete on arrival.
    """
    override = settings.raw_payload_retention_days.get(kind.value)
    if override is not None:
        return override
    return DEFAULT_RETENTION_DAYS.get(kind, FALLBACK_RETENTION_DAYS)


def expires_at(kind: SourceKind, fetched_at: datetime, *, days: int | None = None) -> datetime:
    """When this payload stops being ours to keep.

    `days` is the source's own retention (its settings, LEKA-348): a source
    may keep less than its kind's policy, never more — the policy is what
    was promised.

    Computed once, at write time, and stored as a column rather than worked
    out again by every reader. Two things follow from that, and both matter:
    the sweep is an indexed range scan instead of a walk of every row through
    a Python function, and changing the policy does not retroactively delete
    what was collected under the old one — which is the behaviour you want
    when a customer asks what happened to data they still expected to find.
    """
    policy = retention_days(kind)
    return fetched_at + timedelta(days=min(days, policy) if days else policy)


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "FALLBACK_RETENTION_DAYS",
    "expires_at",
    "retention_days",
]

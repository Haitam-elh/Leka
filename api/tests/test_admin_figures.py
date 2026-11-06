"""How LEKA ADMIN's figures are cut (LEKA-548), without a database: the
monthly retention of each month's sign-ups, never a share for a month that
has not come or that LEKA did not track; and the days (or months) a period
is drawn over, each one, in UTC."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from leka.admin.overview import buckets, cohorts, window_of

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def test_each_month_s_people_are_followed_month_by_month_after_it() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    signed_up = [
        (a, datetime(2026, 8, 3, tzinfo=UTC)),
        (b, datetime(2026, 8, 20, tzinfo=UTC)),
        (c, datetime(2026, 9, 1, tzinfo=UTC)),
        (d, datetime(2026, 11, 2, tzinfo=UTC)),
    ]
    seen = [
        (a, datetime(2026, 9, 9, tzinfo=UTC)),
        (b, datetime(2026, 9, 30, tzinfo=UTC)),
        (a, datetime(2026, 10, 2, tzinfo=UTC)),
        (c, datetime(2026, 11, 5, tzinfo=UTC)),
    ]
    found = cohorts(signed_up, seen, now=NOW, tracked_since=datetime(2026, 9, 1, tzinfo=UTC))
    by_month = {cohort.month: cohort for cohort in found}
    assert [cohort.month for cohort in found] == [
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]
    august = by_month[date(2026, 8, 1)]
    # September: both seen; October: one of two; November so far: none; then not yet.
    assert (august.size, august.retained) == (2, [1.0, 0.5, 0.0, None, None])
    september = by_month[date(2026, 9, 1)]
    assert september.retained == [0.0, 1.0, None, None, None]
    # Nobody signed up in June: no share at all, rather than 0.
    assert by_month[date(2026, 6, 1)].retained == [None] * 5
    # The month in progress has no month after it yet.
    assert by_month[date(2026, 11, 1)].retained == [None] * 5


def test_a_month_before_activity_was_tracked_is_not_known_not_zero() -> None:
    person = uuid.uuid4()
    found = cohorts(
        [(person, datetime(2026, 7, 10, tzinfo=UTC))],
        [],
        now=NOW,
        tracked_since=datetime(2026, 10, 20, tzinfo=UTC),
    )
    july = next(cohort for cohort in found if cohort.month == date(2026, 7, 1))
    # August and September: before LEKA tracked anyone; October and November: not seen.
    assert july.retained == [None, None, 0.0, 0.0, None]
    assert cohorts([(person, NOW)], [], now=NOW, tracked_since=None)[-1].retained == [None] * 5


def test_a_period_is_drawn_over_each_of_its_days_or_months() -> None:
    week = window_of("7d", now=NOW)
    days = buckets(week)
    assert len(days) == 8
    assert days[0] == datetime(2026, 10, 30, tzinfo=UTC)
    assert days[-1] == datetime(2026, 11, 6, tzinfo=UTC)
    year = window_of("12m", now=NOW)
    months = buckets(year)
    assert year.bucket == "month"
    assert (months[0], months[-1], len(months)) == (
        datetime(2025, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 1, tzinfo=UTC),
        13,
    )
    today = buckets(window_of("today", now=NOW))
    assert today == [datetime(2026, 11, 6, tzinfo=UTC)]

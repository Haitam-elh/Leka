"""What came of it (LEKA-392), pure.

What these protect: an expectation is kept only when it can be checked —
its kind, what it is about, a metric's name and comparison, a number to
compare, what a person confirms; LEKA's defaults — healthy after what heals,
the incidents open on it resolved, once per thing; each kind read as it is
— healthy from the incidents open on it and its state, an incident resolved
from its state, a metric from the model or from what the system reported,
a confirmation awaiting a person — nothing said met that was not observed,
nor from what the model held before it ran;
a person's word kept when read again; the verdict — succeeded when all are
met, still verifying until the deadline, then partial or failed; and a
system's measures read from its answer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.intentions.execution import outcome_of
from leka.intentions.outcome import (
    Expectation,
    ExpectationError,
    Observed,
    Result,
    Seen,
    Thing,
    check,
    expected_for,
    observe,
    reported,
    validated,
    verdict,
)

BILLING = str(uuid.uuid4())
INCIDENT = str(uuid.uuid4())
TARGET = {"id": BILLING, "name": "Billing API", "type": "service"}


def healthy() -> Expectation:
    return Expectation(id="healthy", kind="healthy", target=TARGET)


def test_an_expectation_is_kept_only_when_it_can_be_checked() -> None:
    assert validated(healthy()) == healthy()
    metric = Expectation(
        id="p95", kind="metric", name="p95_ms", comparator="lte", value=300, source="system"
    )
    assert validated(metric) == metric
    for wrong in (
        Expectation(id="x", kind="vibes", target=TARGET),
        Expectation(id="x", kind="healthy"),
        Expectation(id="x", kind="healthy", target={"id": "not-a-uuid"}),
        Expectation(id="x", kind="metric", target=TARGET, comparator="lte", value=1),
        Expectation(id="x", kind="metric", target=TARGET, name="p95", comparator="about", value=1),
        Expectation(
            id="x", kind="metric", target=TARGET, name="p95", comparator="lt", value="fast"
        ),
        Expectation(id="x", kind="confirmed", said="  "),
    ):
        with pytest.raises(ExpectationError):
            validated(wrong)
    # Kept, and read back, the same.
    assert Expectation.from_dict(metric.as_dict()) == metric


def test_lekas_defaults_healthy_after_what_heals_its_incidents_resolved() -> None:
    found = expected_for(
        [
            {"action": "restart", "targets": [TARGET]},
            {"action": "rollback", "targets": [TARGET]},
            {
                "action": "notify",
                "targets": [{"id": str(uuid.uuid4()), "name": "x", "type": "team"}],
            },
        ],
        {BILLING: [INCIDENT]},
    )
    assert [(e.id, e.kind) for e in found] == [
        (f"healthy:{BILLING}", "healthy"),
        (f"incidents:{BILLING}", "incident_resolved"),
    ]
    assert found[1].incidents == (INCIDENT,)


def seen(expectation: Expectation, observed: Observed) -> tuple[Seen, object]:
    result = check(expectation, observed)
    return result.seen, result.value


def thing(*incidents: str, known: bool = True, **attributes: object) -> Observed:
    return Observed(
        things={BILLING: Thing("service", "active", attributes, open_incidents=incidents)},
        incidents_known=known,
    )


def test_healthy_is_read_from_the_model() -> None:
    # No incident open on it, where the model holds incidents.
    assert seen(healthy(), thing(team="payments")) == (Seen.MET, 0)
    assert seen(healthy(), thing(INCIDENT, str(uuid.uuid4()))) == (Seen.NOT_MET, 2)
    # Its state: a resource's, normalised; a service's, as its tool says it;
    # on its way, read again.
    assert seen(healthy(), thing(state="running")) == (Seen.MET, "running")
    assert seen(healthy(), thing(state="active", known=False)) == (Seen.MET, "active")
    assert seen(healthy(), thing(state="failed")) == (Seen.NOT_MET, "failed")
    assert seen(healthy(), thing(state="stopped"))[0] is Seen.NOT_MET
    assert seen(healthy(), thing(state="critical"))[0] is Seen.NOT_MET
    assert seen(healthy(), thing(state="starting"))[0] is Seen.UNKNOWN
    assert seen(healthy(), thing(state="maintenance"))[0] is Seen.UNKNOWN
    assert seen(healthy(), thing(INCIDENT, state="running"))[0] is Seen.NOT_MET
    # Nothing that says its health — no state, no incident ever read: not assumed.
    assert seen(healthy(), thing(team="payments", known=False))[0] is Seen.UNKNOWN
    assert seen(healthy(), Observed())[0] is Seen.UNKNOWN
    gone = Observed(things={BILLING: Thing("service", "removed", {})}, incidents_known=True)
    assert seen(healthy(), gone)[0] is Seen.NOT_MET


def test_met_only_when_shown_since_it_ran() -> None:
    ran = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)

    def at(seen_at: datetime | None, **attributes: object) -> Observed:
        found = Thing("service", "active", attributes, seen_at=seen_at)
        return Observed(things={BILLING: found}, incidents_known=True, since=ran)

    after, before = ran + timedelta(minutes=5), ran - timedelta(hours=1)
    assert seen(healthy(), at(after, state="active"))[0] is Seen.MET
    stale = check(healthy(), at(before, state="active"))
    assert (stale.seen, stale.detail) == (Seen.UNKNOWN, "not_seen_since")
    assert seen(healthy(), at(None))[0] is Seen.UNKNOWN
    # What is not met stays so: read again until its deadline.
    assert seen(healthy(), at(before, state="critical"))[0] is Seen.NOT_MET
    replicas = Expectation(
        id="r", kind="metric", target=TARGET, name="replicas", comparator="gte", value=3
    )
    assert seen(replicas, at(before, replicas=4))[0] is Seen.UNKNOWN


def test_an_incident_resolved_a_metric_a_confirmation() -> None:
    resolved = Expectation(
        id="incidents", kind="incident_resolved", target=TARGET, incidents=(INCIDENT,)
    )

    def incident(state: str) -> Observed:
        return Observed(things={INCIDENT: Thing("incident", "active", {"state": state})})

    assert seen(resolved, incident("closed"))[0] is Seen.MET
    assert seen(resolved, incident("open")) == (Seen.NOT_MET, 1)
    assert seen(resolved, Observed())[0] is Seen.UNKNOWN

    model = Expectation(
        id="replicas", kind="metric", target=TARGET, name="replicas", comparator="gte", value=3
    )
    assert seen(model, thing(replicas=4)) == (Seen.MET, 4)
    assert seen(model, thing(replicas=2)) == (Seen.NOT_MET, 2)
    assert seen(model, thing())[0] is Seen.UNKNOWN

    system = Expectation(
        id="p95", kind="metric", name="p95_ms", comparator="lt", value=300, source="system"
    )
    assert seen(system, Observed(metrics={"p95_ms": 180})) == (Seen.MET, 180)
    assert seen(system, Observed(metrics={"p95_ms": 900})) == (Seen.NOT_MET, 900)
    assert seen(system, Observed())[0] is Seen.UNKNOWN
    version = Expectation(
        id="v", kind="metric", name="version", comparator="eq", value="2.7.9", source="system"
    )
    assert seen(version, Observed(metrics={"version": "2.7.9"}))[0] is Seen.MET

    asked = Expectation(id="ok", kind="confirmed", said="Checkout works end to end")
    assert seen(asked, Observed())[0] is Seen.AWAITING


def test_a_persons_word_is_kept_when_read_again() -> None:
    asked = Expectation(id="ok", kind="confirmed", said="Checkout works")
    said = reported(
        Result("ok", Seen.AWAITING), met=True, note="Tried it", link=None, by="u", at="t"
    )
    [kept] = observe([asked], Observed(), {"ok": said})
    assert (kept.seen, kept.reported) == (Seen.MET, said.reported)
    assert Result.from_dict(kept.as_dict()) == kept


def test_the_verdict() -> None:
    met, missed = Result("a", Seen.MET), Result("b", Seen.NOT_MET)
    unknown = Result("c", Seen.UNKNOWN)
    assert verdict([met, met], final=False) == "succeeded"
    assert verdict([met, missed], final=False) == "verifying"
    assert verdict([met, missed], final=True) == "partial"
    assert verdict([missed, unknown], final=True) == "failed"
    # Nothing expected: what ran is the outcome.
    assert verdict([], final=False) == "succeeded"


def test_a_systems_measures_are_read_from_its_answer() -> None:
    answer = b'{"status": "succeeded", "metrics": {"p95_ms": 180, "ok": true, "v": "2.7.9"}}'
    assert dict(outcome_of(200, answer).metrics) == {"p95_ms": 180, "v": "2.7.9"}
    assert dict(outcome_of(200, b'{"metrics": "lots"}').metrics) == {}

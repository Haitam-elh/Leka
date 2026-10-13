"""What an approved decision becomes (LEKA-391), pure.

What these protect: an authorized system runs only the actions, in the
environments, on the things it was authorized for — disabled, nothing; a
step goes to the first one authorized, else to a person; a window asked —
the night, the weekend, outside business hours — is read in the plan's
time zone, and when it next opens; a deadline is the end of its day; every
check said, a failing one blocking; a call signed so the endpoint can tell
it is LEKA, now — a tampered body or an old timestamp refused; an answer
taken as it is — done only when the system says so, accepted waiting for a
person, anything else failed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from leka.intentions.execution import (
    Endpoint,
    Situation,
    blocking,
    body_of,
    checks,
    deadline_of,
    in_window,
    next_window,
    outcome_of,
    plan_of,
    scheduled_for,
    sign,
    verify,
)

PARIS = ZoneInfo("Europe/Paris")
BILLING = uuid.uuid4()
OTHER = uuid.uuid4()
ADA, BOB = uuid.uuid4(), uuid.uuid4()
OPS = Endpoint(uuid.uuid4(), "Ops runbooks", frozenset({"restart"}), frozenset({"production"}))
# A Wednesday, 14:00 in Paris.
WEDNESDAY = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def proposal(
    action: str = "restart", environment: str | None = "production", **more: object
) -> dict[str, object]:
    return {
        "id": action,
        "action": action,
        "targets": [{"id": str(BILLING), "name": "Billing API", "type": "service"}],
        "environment": environment,
        "constraints": more.get("constraints", []),
        "reversible": True,
    }


def test_an_endpoint_runs_only_what_it_was_authorized_for() -> None:
    assert OPS.allows("restart", "production", [BILLING])
    assert not OPS.allows("rollback", "production", [BILLING])
    assert not OPS.allows("restart", "staging", [BILLING])
    narrow = Endpoint(
        uuid.uuid4(), "Billing only", frozenset({"*"}), frozenset({"*"}), frozenset({BILLING})
    )
    assert narrow.allows("deploy", "anywhere", [BILLING])
    assert not narrow.allows("deploy", "anywhere", [BILLING, OTHER])
    off = Endpoint(OPS.id, OPS.name, OPS.actions, OPS.environments, enabled=False)
    assert not off.allows("restart", "production", [BILLING])


def test_a_step_goes_to_an_authorized_system_else_to_a_person() -> None:
    steps = plan_of([proposal(), proposal("scale")], [OPS])
    assert [(s.position, s.action, s.executor, s.endpoint_id) for s in steps] == [
        (1, "restart", "webhook", OPS.id),
        (2, "scale", "manual", None),
    ]
    assert steps[0].targets == ({"id": str(BILLING), "name": "Billing API", "type": "service"},)


def test_a_window_is_read_in_the_plans_time_zone() -> None:
    assert in_window("cette nuit", WEDNESDAY, PARIS) is False
    assert in_window("cette nuit", datetime(2026, 10, 7, 21, 30, tzinfo=UTC), PARIS) is True
    assert in_window("ce week end", WEDNESDAY, PARIS) is False
    assert in_window("ce week end", datetime(2026, 10, 10, 9, 0, tzinfo=UTC), PARIS) is True
    assert in_window("hors heures ouvrees", WEDNESDAY, PARIS) is False
    assert in_window("hors heures ouvrees", datetime(2026, 10, 7, 18, 0, tzinfo=UTC), PARIS) is True
    assert in_window("quand tu peux", WEDNESDAY, PARIS) is None
    # Next: 22:00 Paris, 20:00 UTC.
    assert next_window("tonight", WEDNESDAY, PARIS) == datetime(2026, 10, 7, 20, 0, tzinfo=UTC)
    assert next_window("ce week end", WEDNESDAY, PARIS) == datetime(2026, 10, 9, 22, 0, tzinfo=UTC)
    steps = plan_of([proposal(constraints=[{"kind": "window", "value": "cette nuit"}])], [OPS])
    assert scheduled_for(steps, WEDNESDAY, PARIS) == datetime(2026, 10, 7, 20, 0, tzinfo=UTC)
    assert scheduled_for(plan_of([proposal()], [OPS]), WEDNESDAY, PARIS) is None


def test_a_window_said_by_its_hours_is_read_in_the_plans_time_zone() -> None:
    """« Ce soir après 22h », « between 9pm and 11pm » (LEKA-440)."""
    evening = datetime(2026, 10, 7, 20, 30, tzinfo=UTC)  # 22:30 Paris
    assert in_window("ce soir apres 22h", WEDNESDAY, PARIS) is False
    assert in_window("ce soir apres 22h", evening, PARIS) is True
    # After midnight, still the night it was said for; the morning, not.
    assert in_window("after 10pm", datetime(2026, 10, 7, 23, 0, tzinfo=UTC), PARIS) is True
    assert in_window("after 10pm", datetime(2026, 10, 8, 6, 0, tzinfo=UTC), PARIS) is False
    assert in_window("entre 22h et 23h30", evening, PARIS) is True
    assert (
        in_window("between 9pm and 11pm", datetime(2026, 10, 7, 21, 30, tzinfo=UTC), PARIS) is False
    )
    assert in_window("ce soir", evening, PARIS) is True
    # Next: 22:00 Paris, 20:00 UTC.
    assert next_window("ce soir apres 22h", WEDNESDAY, PARIS) == datetime(
        2026, 10, 7, 20, 0, tzinfo=UTC
    )


def test_a_deadline_is_the_end_of_its_day() -> None:
    assert deadline_of("2026-10-08", PARIS) == datetime(2026, 10, 8, 22, 0, tzinfo=UTC)
    assert deadline_of(None, PARIS) is None
    assert deadline_of("demain", PARIS) is None


def situation(**changes: object) -> Situation:
    base: dict[str, object] = {
        "decision_status": "approved",
        "decision_revision": 1,
        "plan_revision": 1,
        "approvers": (ADA,),
        "allowed": frozenset({ADA}),
        "required": 1,
        "endpoints": {OPS.id: OPS},
        "present": frozenset({BILLING}),
        "now": datetime(2026, 10, 7, 21, 30, tzinfo=UTC),
        "zone": PARIS,
    }
    base.update(changes)
    return Situation(**base)  # type: ignore[arg-type]


def test_every_check_is_said_one_failing_blocks() -> None:
    steps = plan_of(
        [
            proposal(
                constraints=[
                    {"kind": "window", "value": "cette nuit"},
                    {"kind": "deadline", "value": "2026-10-08"},
                ]
            )
        ],
        [OPS],
    )
    found = checks(steps, situation())
    assert [(c.code, c.passed) for c in found] == [
        ("decision_approved", True),
        ("approvers_allowed", True),
        ("endpoint_allows", True),
        ("targets_present", True),
        ("in_window", True),
        ("before_deadline", True),
    ]
    assert blocking(found) == []

    def failing(**changes: object) -> list[str]:
        return [c.code for c in blocking(checks(steps, situation(**changes)))]

    assert failing(decision_revision=2) == ["decision_approved"]
    assert failing(allowed=frozenset()) == ["approvers_allowed"]
    disabled = Endpoint(OPS.id, OPS.name, OPS.actions, OPS.environments, enabled=False)
    assert failing(endpoints={OPS.id: disabled}) == ["endpoint_allows"]
    assert failing(endpoints={}) == ["endpoint_allows"]
    assert failing(present=frozenset()) == ["targets_present"]
    assert failing(now=WEDNESDAY) == ["in_window"]
    assert failing(now=datetime(2026, 10, 9, 21, 30, tzinfo=UTC)) == ["before_deadline"]


def test_a_call_is_signed_and_verified() -> None:
    body = body_of({"action": "restart", "b": 1, "a": 2})
    assert body == b'{"a":2,"action":"restart","b":1}'
    header = sign("lks_secret", 1_760_000_000, body)
    assert header.startswith("t=1760000000,v1=")
    assert verify("lks_secret", header, body, now=1_760_000_100)
    assert not verify("lks_secret", header, body + b" ", now=1_760_000_100)
    assert not verify("another", header, body, now=1_760_000_100)
    assert not verify("lks_secret", header, body, now=1_760_001_000)  # too old
    assert not verify("lks_secret", "v1=nothing", body, now=1_760_000_000)


def test_an_answer_is_taken_as_it_is() -> None:
    def said(code: int, body: object = b"") -> tuple[str, str | None]:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        outcome = outcome_of(code, raw)
        return outcome.status, outcome.reason

    assert said(200, {"status": "succeeded", "ref": "run-42"}) == ("succeeded", None)
    assert outcome_of(200, b'{"status":"succeeded","ref":"run-42"}').ref == "run-42"
    # Accepted is not done: a person confirms it.
    assert said(202) == ("awaiting", "accepted")
    for working in ("accepted", "pending", "running", "queued"):
        assert said(200, {"status": working}) == ("awaiting", "accepted")
    # Done only when the contract says so (LEKA-435): an empty, unreadable or
    # unknown answer may have acted — a person confirms, never assumed done.
    for unsaid in (b"", b"<html>ok</html>", b"{not json", {}, {"status": "done"}, ["ok"]):
        assert said(200, unsaid) == ("awaiting", "unconfirmed"), unsaid
    assert said(204) == ("awaiting", "unconfirmed")
    assert said(202, {"status": "succeeded"}) == ("awaiting", "accepted")
    assert said(200, {"status": "failed", "detail": "pod crashloop"}) == (
        "failed",
        "reported_failed",
    )
    assert said(500, {"status": "succeeded"}) == ("failed", "http_500")
    assert said(403) == ("failed", "http_403")

"""Watching the environment (LEKA-442), pure: what a plan includes, what
opens an alert, what keeps it, what resolves it.

What these protect:
- Free sees, never alerted; alerts from Starter, by e-mail from Growth;
  Enterprise by contract — the catalogue's word, said provisional;
- unavailable and degraded open an alert — confirmed by a record, suspected
  from a deduction, unverified from stale data; a source failing too;
- the same trouble seen again never opens a second: the open one follows
  it, made worse or milder;
- only a fresh signal — a tool's measure, a provider's word — resolves it,
  said which; silence, staleness, a deduction keep it open, unverified;
- a thing gone from the model closes it, said why;
- the e-mail lists what opened, how sure, in the reader's language.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from leka.billing import catalogue
from leka.monitoring import MonitoringAlert, Open, Seen, entitlement_of, judge, message

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
PAYMENT = uuid.uuid5(uuid.NAMESPACE_URL, "payment-api")
RUNBOOKS = uuid.uuid5(uuid.NAMESPACE_URL, "runbooks")


def seen(state: str, **more: object) -> Seen:
    return Seen("entity", PAYMENT, "payment-api", state, **more)  # type: ignore[arg-type]


def alert(kind: str = "degraded", certainty: str = "confirmed") -> Open:
    return Open(uuid.uuid4(), "entity", PAYMENT, "health", kind, "medium", certainty)


def test_free_sees_paid_plans_are_alerted_email_from_growth() -> None:
    free = entitlement_of("free")
    assert not free.monitoring.proactive and free.monitoring.alerts == ()
    assert (free.alerts_from, free.email_from) == ("starter", "growth")
    assert entitlement_of("starter").monitoring.alerts == ("in_app",)
    assert entitlement_of("growth").monitoring.alerts == ("in_app", "email")
    assert entitlement_of("business").monitoring.alerts == ("in_app", "email")
    assert entitlement_of("enterprise").monitoring.contractual
    # Decided for the launch: said provisional.
    assert all(p.monitoring.provisional or p.monitoring.contractual for p in catalogue().plans)


def test_trouble_opens_an_alert_said_how_sure() -> None:
    judged = judge(
        [
            seen("unavailable", basis="measured", reason="incident_open"),
            Seen("source", RUNBOOKS, "Runbooks space", "error", reason="401 Unauthorized"),
        ],
        [],
        NOW,
    )
    by_kind = {a["kind"]: a for a in judged.opened}
    assert by_kind["unavailable"]["severity"] == "high"
    assert by_kind["unavailable"]["certainty"] == "confirmed"
    assert by_kind["source_failing"]["subject_name"] == "Runbooks space"
    suspected = judge([seen("degraded", basis="deduced", certainty="suspected")], [], NOW)
    assert suspected.opened[0]["certainty"] == "suspected"
    stale = judge([seen("degraded", fresh=False)], [], NOW)
    assert stale.opened[0]["certainty"] == "unverified"
    # Well, unknown, not covered, stale: nothing opened.
    for state in ("operational", "unknown", "not_covered", "stale"):
        assert not judge([seen(state)], [], NOW).opened


def test_the_same_trouble_seen_again_follows_the_open_alert() -> None:
    open_one = alert("degraded")
    worse = judge([seen("unavailable", basis="measured")], [open_one], NOW)
    assert not worse.opened
    [(alert_id, values)] = worse.updated
    assert alert_id == open_one.id
    assert (values["kind"], values["severity"], values["last_seen_at"]) == (
        "unavailable",
        "high",
        NOW,
    )


def test_only_a_fresh_signal_resolves_silence_keeps_it_open_unverified() -> None:
    open_one = alert()
    measured = judge(
        [seen("operational", basis="measured", reason="monitored_quiet", signal=("acme-eu",))],
        [open_one],
        NOW,
    )
    [(alert_id, resolution)] = measured.resolved
    assert alert_id == open_one.id
    assert resolution["signal"] == ["acme-eu"] and resolution["basis"] == "measured"
    for state, basis, fresh in (
        ("unknown", "none", True),
        ("not_covered", "none", True),
        ("stale", "measured", False),
        ("operational", "deduced", True),
        ("operational", "measured", False),
    ):
        kept = judge([seen(state, basis=basis, fresh=fresh)], [open_one], NOW)
        assert not kept.resolved, state
        assert kept.updated == [(open_one.id, {"certainty": "unverified"})]
    # Already unverified: nothing more to say.
    assert not judge([seen("unknown")], [alert(certainty="unverified")], NOW).updated


def test_a_source_read_again_resolves_its_alert_a_thing_gone_closes_it() -> None:
    failing = Open(
        uuid.uuid4(), "source", RUNBOOKS, "source", "source_failing", "medium", "confirmed"
    )
    read = judge([Seen("source", RUNBOOKS, "Runbooks space", "read")], [failing], NOW)
    assert [a for a, _ in read.resolved] == [failing.id]
    gone = judge([], [alert()], NOW)
    assert gone.closed[0][1]["reason"] == "subject_gone"


def test_the_email_lists_what_opened_and_how_sure_in_its_language() -> None:
    alerts = [
        MonitoringAlert(
            subject_name="payment-api", kind="unavailable", severity="high", certainty="confirmed"
        ),
        MonitoringAlert(
            subject_name="Runbooks space",
            kind="source_failing",
            severity="medium",
            certainty="confirmed",
        ),
    ]
    fr = message(alerts, "Acme Corp", "fr")
    assert fr.subject == "LEKA — 2 alertes sur Acme Corp"
    assert "- payment-api: indisponible (confirmé)" in fr.body
    assert "- Runbooks space: source en échec (confirmé)" in fr.body
    en = message(alerts[:1], None, "en")
    assert en.subject == "LEKA — 1 alert on your workspace"
    assert en.language == "en"

"""Knowledge conflicts (LEKA-382), the judgement, pure.

What the model's sources disagree on and the workspace's authority rules,
in; conflicts — every side weighed, one recommended — out. No database.

What these protect: a source is believed by its family on what is
disagreed on — the cloud on where a thing runs, the monitoring tool on its
state, the code host on who owns it, a catalogue on how critical; the
workspace's rule beats that, on the attribute before everything; a value
said lately and by a source that reads is worth more, said by several more
still; an inferred tie less; the best side is recommended — by the rule,
clearly, weakly — with its reasons, and none when no side stands out; each
conflict is keyed by its thing and what about, says itself in a sentence,
keeps its sides' sources; it is a conflict, not a finding; without the
disputes read, the analysis is skipped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.intelligence import ANALYZERS, Authority, Material, execute
from leka.intelligence.conflicts import (
    ANALYZER,
    assess,
    default_authority,
    domain,
    find_conflicts,
    freshness,
    stance,
)
from leka.knowledge import (
    Dispute,
    DisputeSide,
    DisputeSource,
    EntityBrief,
    EntityType,
    Lifecycle,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
GITHUB, DATADOG, AWS, JIRA = (uuid.uuid4() for _ in range(4))
CATEGORIES = {"github": "code", "datadog": "observability", "aws": "cloud", "jira": "project"}
PAYMENT = EntityBrief(
    id=uuid.uuid4(),
    type=EntityType.SERVICE,
    key="service:payment-api",
    name="payment-api",
    lifecycle=Lifecycle.ACTIVE,
)


def said_by(
    source: uuid.UUID,
    kind: str,
    *,
    days: float | None = 1,
    status: str = "active",
) -> DisputeSource:
    return DisputeSource(
        source_id=source,
        kind=kind,
        name={"github": "acme/backend", "datadog": "acme-eu", "aws": "production", "jira": "OPS"}[
            kind
        ],
        status=status,
        synced_at=NOW,
        observed_at=NOW - timedelta(days=days) if days is not None else None,
    )


def dispute(
    about: str,
    *sides: tuple[str, list[DisputeSource]],
    chosen: str | None = None,
    kind: str = "attribute",
    origins: tuple[str | None, ...] = (),
) -> Dispute:
    return Dispute(
        kind=kind,
        entity=PAYMENT,
        about=about,
        relationship="owned_by" if kind == "relationship" else None,
        chosen=chosen,
        sides=[
            DisputeSide(
                value=value,
                sources=sources,
                origin=origins[i] if i < len(origins) else None,
            )
            for i, (value, sources) in enumerate(sides)
        ],
    )


def material(*disputes: Dispute, rules: tuple[Authority, ...] = ()) -> Material:
    return Material(
        now=NOW,
        built_at=NOW,
        categories=CATEGORIES,
        disputes=disputes,
        authority=rules,
    )


# ── how much a source is believed ──────────────────────────────────────────


def test_a_source_is_believed_by_its_family_on_what_is_disagreed_on() -> None:
    assert domain("region") == "runtime"
    assert default_authority("cloud", "region") > default_authority("code", "region")
    assert default_authority("observability", "status") == 1.0
    assert default_authority("code", "owner") > default_authority("project", "owner")
    assert default_authority("custom", "criticality") == 1.0
    # Of no known family: believed little.
    assert default_authority(None, "region") == 0.3


def test_the_workspace_s_rule_beats_the_family_on_the_attribute_first() -> None:
    rules = (
        Authority("*", DATADOG, "avoid"),
        Authority("sla", DATADOG, "prefer"),
    )
    assert stance(rules, said_by(DATADOG, "datadog"), "sla") == "prefer"
    assert stance(rules, said_by(DATADOG, "datadog"), "region") == "avoid"
    assert stance(rules, said_by(GITHUB, "github"), "sla") is None


def test_a_value_said_lately_by_a_source_that_reads_is_fresher() -> None:
    assert freshness(said_by(GITHUB, "github", days=2), NOW) == 1.0
    assert freshness(said_by(GITHUB, "github", days=20), NOW) == 0.8
    assert freshness(said_by(GITHUB, "github", days=60), NOW) == 0.5
    assert freshness(said_by(GITHUB, "github", days=400), NOW) == 0.3
    assert freshness(said_by(GITHUB, "github", days=None), NOW) == 0.5
    assert freshness(said_by(GITHUB, "github", days=2, status="error"), NOW) == 0.6
    assert freshness(said_by(GITHUB, "github", days=2, status="disabled"), NOW) == 0.3


# ── the recommendation ─────────────────────────────────────────────────────


def test_the_best_side_is_recommended_with_its_reasons() -> None:
    region = dispute(
        "region",
        ("eu-west-3", [said_by(AWS, "aws", days=1), said_by(DATADOG, "datadog", days=1)]),
        ("eu-west-1", [said_by(GITHUB, "github", days=200)]),
        chosen="eu-west-1",
    )
    sides, recommended = assess(region, material(region))

    assert recommended["side"] == 0
    assert recommended["strength"] == "clear"
    assert recommended["reasons"] == ["authority", "fresher", "corroborated"]
    aws = sides[0]
    # 0.55 x 1 + 0.3 x 1 + 0.15 x 2/3
    assert aws["score"] == pytest.approx(0.95, abs=0.001)
    assert aws["sources"][0]["authority"] == 1.0  # type: ignore[index]
    assert sides[1]["freshness"] == 0.3


def test_a_rule_makes_the_recommendation() -> None:
    sla = dispute(
        "sla",
        ("99.95", [said_by(GITHUB, "github")]),
        ("99.9", [said_by(DATADOG, "datadog")]),
        chosen="99.95",
    )
    _, by_family = assess(sla, material(sla))
    assert (by_family["side"], by_family["reasons"]) == (0, ["authority", "chosen"])

    rules = (Authority("sla", DATADOG, "prefer"),)
    sides, ruled = assess(sla, material(sla, rules=rules))
    assert (ruled["side"], ruled["strength"]) == (1, "rule")
    reasons = ruled["reasons"]
    assert isinstance(reasons, list) and reasons[0] == "rule"
    said = sides[1]["sources"]
    assert isinstance(said, list)
    assert said[0]["rule"] == "prefer"


def test_no_side_stands_out_no_recommendation() -> None:
    even = dispute(
        "description",
        ("Payments", [said_by(GITHUB, "github")]),
        ("Card payments", [said_by(GITHUB, "github")]),
    )
    _, recommended = assess(even, material(even))
    assert recommended == {"side": None, "strength": "none", "reasons": [], "margin": 0.0}


def test_close_sides_are_a_weak_recommendation() -> None:
    near = dispute(
        "sla",
        ("99.95", [said_by(GITHUB, "github")]),
        ("99.9", [said_by(DATADOG, "datadog")]),
    )
    _, recommended = assess(near, material(near))
    assert recommended["strength"] == "weak"


def test_an_inferred_tie_is_believed_less() -> None:
    owner = dispute(
        "owner",
        ("Payments", [said_by(GITHUB, "github")]),
        ("Platform", [said_by(GITHUB, "github")]),
        kind="relationship",
        origins=("stated", "inferred"),
    )
    sides, recommended = assess(owner, material(owner))
    assert sides[1]["authority"] == pytest.approx(sides[0]["authority"] * 0.6)  # type: ignore[operator]
    assert recommended["side"] == 0


# ── as an analysis ─────────────────────────────────────────────────────────


def test_each_disagreement_is_a_conflict_keyed_said_and_sourced() -> None:
    sla = dispute(
        "sla",
        ("99.95", [said_by(GITHUB, "github")]),
        ("99.9", [said_by(DATADOG, "datadog")]),
        chosen="99.95",
    )
    (conflict,) = find_conflicts(material(sla))

    assert conflict.key == f"conflict.attribute:{PAYMENT.id}:sla"
    assert (conflict.subject.id, conflict.subject.kind) == (PAYMENT.id, "service")
    assert conflict.statement == (
        "payment-api's sources disagree on sla: 99.95 (acme/backend); 99.9 (acme-eu). "
        "LEKA recommends 99.95 (authority, chosen)."
    )
    assert conflict.sources == ("datadog", "github")
    assert conflict.chosen == "99.95"


async def test_a_conflict_is_not_a_finding_and_needs_its_disputes() -> None:
    sla = dispute(
        "sla", ("99.95", [said_by(GITHUB, "github")]), ("99.9", [said_by(DATADOG, "datadog")])
    )
    outcome = await execute(ANALYZER, material(sla))
    assert outcome.status == "succeeded"
    assert outcome.drafts == () and outcome.proposals == ()
    assert [c.about for c in outcome.conflicts] == ["sla"]

    skipped = await execute(ANALYZER, Material(now=NOW, built_at=NOW))
    assert (skipped.status, skipped.reason) == ("skipped", "no_material")
    assert ANALYZER in ANALYZERS

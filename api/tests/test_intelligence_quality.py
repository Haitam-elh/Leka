"""Knowledge quality (LEKA-381), pure.

The architecture, what the model holds around each thing — its merges'
confidence, its records' quality, when it was last seen, its sources, its
attributes' origins, what is disputed, what its relationships break — and
what the sources disagree on, in; scores and findings out — no database.

What these protect: four defined dimensions, each read from what the model
and the other analyses already say — the gaps of LEKA-379 called, not found
again; a factor nothing measures left out, never guessed; the context's
thresholds (LEKA-375), so the product says one thing; a contradiction left
open holds a thing to medium, a settled one does not count; every score
says what lowers it; areas weigh what is relied on more; low quality said
as findings, the more relied on first, the evidence kept.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from leka.context.quality import HIGH as CONTEXT_HIGH
from leka.context.quality import MEDIUM as CONTEXT_MEDIUM
from leka.intelligence import ANALYZERS, Draft, Material, QualityScore, Reads, Severity, execute
from leka.intelligence.quality import (
    ANALYZER,
    CAPPED,
    HIGH,
    MEDIUM,
    WEIGHTS,
    level,
    measure,
)
from leka.knowledge import (
    ArchitectureCardRead,
    ArchitectureLinkRead,
    Dispute,
    EntityBrief,
    EntityStanding,
    EntityType,
    Lifecycle,
)
from tests.test_intelligence_gaps import of, source, world
from tests.test_intelligence_rules import NOW, card, link


def known(
    name: str,
    *,
    team: str | None = "Payments",
    column: str = "services",
    type_: str = "service",
    description: str | None = "What it does.",
) -> ArchitectureCardRead:
    """A thing whose runtime, code, owner and purpose are known."""
    return card(name, team=team, column=column, type_=type_).model_copy(
        update={"host_id": "cluster", "repository_id": "repo", "description": description}
    )


def standing(
    *,
    documents: int = 1,
    fresh: int = 1,
    seen: timedelta | None = timedelta(days=1),
    confidence: float = 1.0,
    quality: float | None = 0.9,
    sources: tuple[uuid.UUID, ...] = (),
    origins: dict[str, int] | None = None,
    disputed: tuple[str, ...] = (),
    issues: tuple[int, int] = (0, 0),
    criticality: str | None = None,
) -> EntityStanding:
    return EntityStanding(
        criticality=criticality,
        lifecycle=Lifecycle.ACTIVE,
        documents=documents,
        fresh_documents=fresh,
        last_documented_at=None,
        business=True,
        confidence=confidence,
        quality=quality,
        last_seen_at=NOW - seen if seen is not None else None,
        source_ids=sources,
        origins=origins if origins is not None else {"source": 4},
        disputed=disputed,
        issues=issues,
    )


GITHUB = source("github")


def scores(said: list[Draft | QualityScore]) -> dict[str, QualityScore]:
    return {item.key: item for item in said if isinstance(item, QualityScore)}


def findings(said: list[Draft | QualityScore]) -> list[Draft]:
    return [item for item in said if isinstance(item, Draft)]


def of_card(said: list[Draft | QualityScore], thing: ArchitectureCardRead) -> QualityScore:
    return scores(said)[f"entity:{of(thing)}"]


def lacking(score: QualityScore) -> list[str]:
    return [str(lack["code"]) for lack in score.missing]


def pair(
    a: ArchitectureCardRead | None = None, b: ArchitectureCardRead | None = None
) -> tuple[ArchitectureCardRead, ArchitectureCardRead, list[ArchitectureLinkRead]]:
    a = a or known("payment-api")
    b = b or known("ledger-db", column="data", type_="database")
    return a, b, [link(a, b, "stores")]


def material(
    cards: list[ArchitectureCardRead],
    links: list[ArchitectureLinkRead],
    standings: dict[uuid.UUID, EntityStanding] | None = None,
    **kwargs: object,
) -> Material:
    found = world(
        cards,
        links,
        sources=(GITHUB, "datadog", "aws", "postgresql"),
        standings=standings
        if standings is not None
        else {of(c): standing(sources=(GITHUB.source_id,)) for c in cards},
        **kwargs,  # type: ignore[arg-type]
    )
    return found


# ── the method, as documented ──────────────────────────────────────────────


def test_the_levels_are_the_contexts() -> None:
    assert (HIGH, MEDIUM) == (CONTEXT_HIGH, CONTEXT_MEDIUM)
    assert level(0.85) == "high"
    assert level(0.8499) == "medium"
    assert level(0.6) == "medium"
    assert level(0.5999) == "low"
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_a_thing_well_known_is_high_and_lacks_nothing() -> None:
    api, db, links = pair()
    said = measure(material([api, db], links))
    score = of_card(said, api)
    assert score.level == "high"
    assert score.score >= HIGH
    assert score.dimensions == {
        "completeness": 1.0,
        "freshness": 1.0,
        "consistency": 1.0,
        "confidence": pytest.approx(0.97, abs=0.01),
    }
    assert score.missing == ()
    assert score.capped is None
    assert set(score.areas) == {"column:services", f"team:{api.team.id if api.team else ''}"}
    assert score.sources == ("github",)
    assert findings(said) == []


def test_completeness_reuses_the_gaps_and_names_what_is_missing() -> None:
    """Tied to nothing, owned by no one, described by nothing: the gaps of
    LEKA-379 — isolated, undocumented — and what no source says."""
    lonely = known("lonely-api", team=None, description=None)
    other, db, links = pair()
    said = measure(
        material(
            [lonely, other, db],
            links,
            standings={
                of(lonely): standing(documents=0, fresh=0, sources=(GITHUB.source_id,)),
                of(other): standing(sources=(GITHUB.source_id,)),
                of(db): standing(sources=(GITHUB.source_id,)),
            },
        )
    )
    score = of_card(said, lonely)
    assert lacking(score)[:2] == ["isolated", "no_owner"]
    assert set(lacking(score)) == {"isolated", "no_owner", "undocumented", "no_description"}
    # 1 - .35 - .25 - .2 - .1
    assert score.dimensions["completeness"] == pytest.approx(0.1)
    for lack in score.missing:
        assert lack["dimension"] == "completeness"
        assert lack["detail"]


def test_a_gap_is_only_counted_where_its_family_is_connected() -> None:
    """No cloud source: where a service runs is not asked of it (coverage
    says it, once)."""
    api, db, links = pair(known("payment-api").model_copy(update={"host_id": None}))
    with_cloud = of_card(measure(material([api, db], links)), api)
    found = world(
        [api, db],
        links,
        sources=(GITHUB, "datadog", "postgresql"),
        standings={of(c): standing(sources=(GITHUB.source_id,)) for c in (api, db)},
    )
    without = of_card(measure(found), api)
    assert "runtime" in lacking(with_cloud)
    assert "runtime" not in lacking(without)


def test_what_is_not_asked_is_unknown_never_guessed() -> None:
    """A cloud resource is asked no owner; a thing with no standing has no
    freshness, no records — the score is over what is known."""
    api, db, links = pair()
    vm = card("vm-1", column="cloud", type_="infra_resource")
    standings = {of(c): standing(sources=(GITHUB.source_id,)) for c in (api, db)}
    said = measure(material([api, db, vm], [*links, link(api, vm, "deployed_on")], standings))
    score = of_card(said, vm)
    assert score.dimensions["completeness"] is None
    assert score.dimensions["freshness"] is None
    assert score.factors["confidence"] == {
        "merge": None,
        "records": None,
        "attributes": None,
        "ties": 1.0,
    }
    # consistency 1, confidence 1 (its tie, stated): what is known is sound.
    assert score.score == pytest.approx(1.0)


def test_freshness_reads_when_seen_its_sources_and_its_documents() -> None:
    failing = source("github", status="error", name="old")
    api, db, links = pair()
    found = world(
        [api, db],
        links,
        sources=(failing, "datadog", "aws", "postgresql"),
        standings={
            of(api): standing(
                seen=timedelta(days=30), documents=2, fresh=0, sources=(failing.source_id,)
            ),
            of(db): standing(seen=timedelta(days=19), sources=(failing.source_id,)),
        },
    )
    said = measure(found)
    stale = of_card(said, api)
    assert stale.factors["freshness"] == {"seen": 0.0, "sources": 0.3, "documents": 0.0}
    assert set(lacking(stale)) >= {"unseen", "source_unhealthy", "stale_documents"}
    # 19 days: half way from 8 to 30.
    assert of_card(said, db).factors["freshness"]["seen"] == pytest.approx(0.5)  # type: ignore[index]


def test_a_source_not_read_for_days_is_late() -> None:
    late = source("github", read=timedelta(days=5), name="late")
    api, db, links = pair()
    found = world(
        [api, db],
        links,
        sources=(late, "datadog", "aws", "postgresql"),
        standings={of(c): standing(sources=(late.source_id,)) for c in (api, db)},
    )
    assert of_card(measure(found), api).factors["freshness"]["sources"] == 0.5  # type: ignore[index]


def test_an_open_contradiction_holds_it_to_medium() -> None:
    api, db, links = pair()
    said = measure(
        material(
            [api, db],
            links,
            standings={
                of(api): standing(disputed=("sla",), sources=(GITHUB.source_id,)),
                of(db): standing(issues=(1, 2), sources=(GITHUB.source_id,)),
            },
        )
    )
    disputed = of_card(said, api)
    # The SLA decides an answer: 0.35.
    assert disputed.dimensions["consistency"] == pytest.approx(0.65)
    assert disputed.score == CAPPED
    assert disputed.level == "medium"
    assert disputed.capped == "contradiction"
    broken = of_card(said, db)
    assert broken.dimensions["consistency"] == pytest.approx(1 - 0.25 - 0.2)
    assert set(lacking(broken)) >= {"relationship_error", "relationship_warning"}


def test_the_conflicts_read_say_what_is_settled() -> None:
    """Read (LEKA-382), the conflicts are what counts: a settled one no
    longer does; a relationship a thing has one of, said to several, does."""
    api, db, links = pair()
    brief = EntityBrief(
        id=of(api),
        type=EntityType.SERVICE,
        key="service:payment-api",
        name="payment-api",
        lifecycle=Lifecycle.ACTIVE,
    )

    def dispute(about: str, kind: str = "attribute", settled: bool = False) -> Dispute:
        return Dispute(
            kind=kind,
            entity=brief,
            about=about,
            relationship="owned_by" if kind == "relationship" else None,
            chosen=None,
            sides=[],
            settled={"side": 0} if settled else None,
        )

    found = material(
        [api, db],
        links,
        standings={
            of(api): standing(disputed=("sla", "colour"), sources=(GITHUB.source_id,)),
            of(db): standing(sources=(GITHUB.source_id,)),
        },
        owners=None,
    )
    found = Material(
        **{
            **found.__dict__,
            "disputes": (dispute("sla", settled=True), dispute("owner", "relationship")),
        }
    )
    score = of_card(measure(found), api)
    assert score.dimensions["consistency"] == pytest.approx(0.65)
    assert [lack["detail"] for lack in score.missing if lack["code"] == "disputed"] == [
        "its sources disagree on its owner, and no one settled it"
    ]


def test_confidence_reads_how_it_was_made() -> None:
    api = known("payment-api")
    db = known("ledger-db", column="data", type_="database")
    cache = known("cache", column="data", type_="database")
    links = [
        link(api, db, "stores", origin="inferred", confidence=0.6),
        link(api, cache, "cache", origin="inferred", confidence=0.6),
    ]
    said = measure(
        material(
            [api, db, cache],
            links,
            standings={
                of(api): standing(
                    confidence=0.5,
                    quality=0.4,
                    origins={"source": 2, "enrichment": 1, "accepted": 1},
                    sources=(GITHUB.source_id,),
                ),
                of(db): standing(sources=(GITHUB.source_id,)),
                of(cache): standing(sources=(GITHUB.source_id,)),
            },
        )
    )
    score = of_card(said, api)
    assert score.factors["confidence"] == {
        "merge": 0.5,
        "records": 0.4,
        "attributes": pytest.approx((2 + 0.7 + 0.9) / 4),
        "ties": 0.7,
    }
    assert set(lacking(score)) >= {"uncertain_identity", "weak_records", "mostly_inferred"}


# ── areas ──────────────────────────────────────────────────────────────────


def test_areas_weigh_what_is_relied_on() -> None:
    """A team's score is its things', what more rely on weighing more; an
    application holds its services; the workspace holds everything."""
    app = known("Checkout", type_="application")
    core = known("core-api")
    weak = known("legacy-api", description=None)
    users = [known(f"client-{n}", team="Web") for n in range(5)]
    links = [
        link(core, app, "part_of"),
        link(weak, app, "part_of"),
        *(link(user, core, "calls") for user in users),
        link(weak, core, "calls"),
    ]
    standings = {of(c): standing(sources=(GITHUB.source_id,)) for c in (app, core, *users)} | {
        of(weak): standing(quality=0.2, confidence=0.4, sources=(GITHUB.source_id,))
    }
    said = measure(material([app, core, weak, *users], links, standings))
    found = scores(said)
    team = found[f"team:{app.team.id if app.team else ''}"]
    application = found[f"application:{of(app)}"]
    assert application.entities == 3
    assert team.entities == 3
    core_score, weak_score = of_card(said, core).score, of_card(said, weak).score
    plain = (of_card(said, app).score + core_score + weak_score) / 3
    # core-api, relied on by six, weighs twice: the team is above the plain mean.
    assert team.score > plain
    assert team.factors["weakest"][0]["name"] == "legacy-api"  # type: ignore[index]
    assert found["workspace"].entities == 8
    assert {"column:services"} <= set(found)
    assert found["workspace"].subject.type == "workspace"


# ── what is said ───────────────────────────────────────────────────────────


def test_weak_knowledge_is_said_the_more_relied_on_first() -> None:
    shared = known("shared-db", team=None, column="data", type_="database", description=None)
    users = [known(f"user-{n}") for n in range(3)]
    alone = known("alone-db", team=None, column="data", type_="database", description=None)
    links = [*(link(user, shared, "stores") for user in users), link(users[0], alone, "stores")]
    poor = standing(
        seen=timedelta(days=40),
        documents=0,
        fresh=0,
        quality=0.2,
        confidence=0.4,
        sources=(GITHUB.source_id,),
    )
    standings = {of(c): standing(sources=(GITHUB.source_id,)) for c in users} | {
        of(shared): poor,
        of(alone): poor,
    }
    said = measure(material([shared, alone, *users], links, standings))
    found = {d.subject.name: d for d in findings(said) if d.code == "quality.low"}
    assert set(found) == {"shared-db", "alone-db"}
    assert found["shared-db"].severity is Severity.HIGH
    assert found["alone-db"].severity is Severity.MEDIUM
    weak = found["shared-db"]
    assert weak.key == f"entity:{of(shared)}"
    assert weak.params["level"] == "low"
    assert weak.params["dependents"] == 3
    assert weak.params["missing"]
    assert weak.evidence and all(e.kind == "quality" for e in weak.evidence)
    assert weak.sources == ("github",)
    assert weak.rank > found["alone-db"].rank


def test_a_weak_area_is_said_once_it_holds_enough() -> None:
    poor = standing(seen=timedelta(days=60), documents=0, fresh=0, quality=0.1, confidence=0.3)
    things = [known(f"svc-{n}", team="Legacy", description=None) for n in range(3)]
    hub = known("hub", team="Core")
    links = [link(thing, hub, "calls") for thing in things]
    standings = {of(t): poor for t in things} | {of(hub): standing()}
    said = measure(material([*things, hub], links, standings))
    areas = [d for d in findings(said) if d.code == "quality.low_area"]
    assert [d.params["scope"] for d in areas] == ["team"]
    assert areas[0].subject.name == "Legacy"
    assert areas[0].params["entities"] == 3


def test_nothing_known_measures_nothing() -> None:
    assert measure(Material(now=NOW, built_at=None)) == []
    assert measure(material([], [])) == []


# ── in the engine ──────────────────────────────────────────────────────────


def test_it_is_an_analysis_of_the_engine() -> None:
    assert ANALYZER in ANALYZERS
    assert ANALYZER.category == "quality"
    assert ANALYZER.reads == frozenset({Reads.MODEL})
    assert ANALYZER.heeds == frozenset({Reads.CONFLICTS})


async def test_it_runs_without_the_conflicts_and_keeps_its_scores() -> None:
    api, db, links = pair()
    outcome = await execute(ANALYZER, material([api, db], links))
    assert outcome.status == "succeeded"
    assert {score.key for score in outcome.scores} >= {
        f"entity:{of(api)}",
        f"entity:{of(db)}",
        "workspace",
        "column:services",
        "column:data",
    }
    assert outcome.drafts == ()

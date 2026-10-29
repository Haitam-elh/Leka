"""The capability router (LEKA-398), pure — representative scenarios.

What these protect: who owns something goes to LEKA's ownership analysis,
on its goal and kind; an architecture of a journey goes to the architect,
its words and its context lifting it past the dependencies analysis — and
says what it must be asked before it runs; the context decides between two
that the words cannot tell apart; a capability that cannot run here, or
that this person may not use, is never routed to and is said why — LEKA's
own takes its place, or LEKA's analysis when nothing else fits; an unclear
intention is clarified, with what to ask and what it could mean; a question
never goes to what proposes actions — a policy — a request does; what always runs is
not routed to, what is retired never; and every decision is kept as the
API reads it.
"""

from __future__ import annotations

from dataclasses import replace

from leka.capabilities import (
    Availability,
    Contract,
    Definition,
    Input,
    Kind,
    Lifecycle,
    Reason,
    RouteQuery,
    RoutingRead,
    route,
)
from leka.capabilities.router import decision_said, query_said


def rules(key: str, goals: set[str], kinds: set[str], **more: object) -> Definition:
    return Definition(
        key=key,
        title=key.capitalize(),
        summary=f"LEKA's own {key} analysis, from the company model.",
        category="knowledge",
        kind=Kind.RULES,
        version="1.0.0",
        lifecycle=Lifecycle.ACTIVE,
        goals=frozenset(goals),
        kinds=frozenset(kinds),
        **more,  # type: ignore[arg-type]
    )


OWNERSHIP = rules("ownership", {"find_owner"}, {"ownership"})
DEPENDENCIES = rules("dependencies", {"map_dependencies"}, {"dependency"})
SYNTHESIS = rules("synthesis", set(), set(), always=True)
ARCHITECT = Definition(
    key="application-architecture",
    title="Architecte applicatif",
    summary="Use when someone asks for the application architecture of a business journey.",
    category="architecture",
    kind=Kind.AGENT,
    version="18.0.0",
    lifecycle=Lifecycle.ACTIVE,
    contract=Contract(
        inputs=(
            Input("parcours"),
            Input("perimetre"),
            Input("vue_applicative", type="boolean", required=False),
        ),
        output="document",
        formats=("pptx", "pdf"),
    ),
    sources=(("confluence", "microsoft_365"),),
    model=True,
    goals=frozenset({"map_dependencies", "find_knowledge"}),
    kinds=frozenset({"dependency", "knowledge"}),
    entity_types=("business_process", "application", "service"),
    examples=("Construis l'architecture du parcours Paiement CB sur le périmètre Digital",),
    instructions="…",
)
RESTARTER = Definition(
    key="restart-planner",
    title="Restart planner",
    summary="Use when a service must be restarted: proposes how, in which order.",
    category="operations",
    kind=Kind.AGENT,
    version="1.0.0",
    lifecycle=Lifecycle.ACTIVE,
    model=True,
    mode="proposes_action",
    goals=frozenset({"act", "investigate"}),
    instructions="…",
)
EVERYTHING = (OWNERSHIP, DEPENDENCIES, SYNTHESIS, ARCHITECT, RESTARTER)
OK = Availability(True)


def able(**unavailable: tuple[str, ...]) -> dict[str, Availability]:
    found = {d.key: OK for d in EVERYTHING}
    for key, reasons in unavailable.items():
        found[key.replace("_", "-")] = Availability(False, tuple(Reason(r) for r in reasons))
    return found


def codes(candidate: object) -> list[str]:
    return [s.code for s in candidate.signals]  # type: ignore[attr-defined]


def test_who_owns_it_goes_to_the_ownership_analysis() -> None:
    asked = RouteQuery(
        text="Qui est responsable de payment-api ?", goal="find_owner", kind="ownership"
    )
    routed = route(asked, EVERYTHING, able())
    assert routed.outcome == "routed"
    assert [c.key for c in routed.selected] == ["ownership"]
    assert codes(routed.selected[0]) == ["goal", "kind"]
    assert routed.selected[0].score == 5
    # What runs with every analysis is not routed to.
    assert routed.background == ("synthesis",)


def test_an_architecture_goes_to_the_architect_who_says_what_to_ask() -> None:
    asked = RouteQuery(
        text="Construis l'architecture du parcours Paiement CB sur le périmètre Digital",
        goal="map_dependencies",
        kind="dependency",
        context_types=frozenset({"service", "team"}),
        context_sources=frozenset({"confluence", "pagerduty"}),
    )
    routed = route(asked, EVERYTHING, able())
    assert [c.key for c in routed.selected] == ["application-architecture"]
    architect, dependencies = routed.candidates[0], routed.candidates[1]
    assert codes(architect) == ["goal", "kind", "words", "context_types", "context_sources"]
    assert architect.score > dependencies.score + 1
    assert dependencies.eligible and not dependencies.selected
    assert architect.needs_inputs == ("parcours", "perimetre")


def test_the_context_decides_what_the_words_cannot() -> None:
    other = replace(ARCHITECT, key="data-architecture", entity_types=("database", "data_object"))
    asked = RouteQuery(text="Construis l'architecture", goal="map_dependencies", kind="dependency")
    tie = route(asked, (ARCHITECT, other), {ARCHITECT.key: OK, other.key: OK})
    assert {c.key for c in tie.selected} == {"application-architecture", "data-architecture"}
    held = replace(asked, context_types=frozenset({"database"}))
    decided = route(held, (ARCHITECT, other), {ARCHITECT.key: OK, other.key: OK})
    assert decided.candidates[0].key == "data-architecture"
    assert "context_types" in codes(decided.candidates[0])


def test_what_cannot_run_here_or_for_this_person_is_never_routed_to() -> None:
    asked = RouteQuery(
        text="Construis l'architecture du parcours Paiement CB",
        goal="map_dependencies",
        kind="dependency",
    )
    routed = route(asked, EVERYTHING, able(application_architecture=("missing_source",)))
    assert [c.key for c in routed.selected] == ["dependencies"]
    [left] = routed.excluded
    assert left.key == "application-architecture" and left.eligible
    assert [r.code for r in left.availability.reasons] == ["missing_source"]

    # Nothing else fits: LEKA's analysis, saying a better one was left out.
    alone = route(
        asked, (ARCHITECT,), {ARCHITECT.key: Availability(False, (Reason("not_permitted"),))}
    )
    assert (alone.outcome, alone.fallback, alone.why) == ("fallback", "analysis", "excluded")
    assert alone.selected == ()


def test_nothing_fits_falls_back_to_leka_s_analysis() -> None:
    asked = RouteQuery(text="Quel temps fait-il ?", goal="find_change", kind="change")
    routed = route(asked, EVERYTHING, able())
    assert (routed.outcome, routed.fallback, routed.why) == ("fallback", "analysis", "no_match")


def test_an_unclear_intention_is_clarified_with_what_it_could_mean() -> None:
    unclear = RouteQuery(
        text="payment",
        goal="find_owner",
        kind="ownership",
        clear=False,
        questions=("Which payment: payment-api or payment-worker?",),
    )
    routed = route(unclear, EVERYTHING, able())
    assert (routed.outcome, routed.why) == ("clarify", "unclear")
    assert routed.questions == ("Which payment: payment-api or payment-worker?",)
    assert routed.suggestions[0] == "ownership"

    pointless = RouteQuery(text="bonjour à tous", goal="unknown")
    said = route(pointless, EVERYTHING, able())
    assert (said.outcome, said.why) == ("clarify", "no_goal")


def test_a_question_never_goes_to_what_proposes_actions_a_request_does() -> None:
    question = RouteQuery(text="Pourquoi auth-service redémarre ?", goal="investigate")
    asked = route(question, EVERYTHING, able())
    [planner] = asked.excluded
    assert planner.key == "restart-planner"
    assert planner.availability.reasons[-1].detail == {"rule": "proposes_actions_to_a_question"}
    assert asked.outcome == "fallback" and asked.why == "excluded"

    request = RouteQuery(text="Redémarre auth-service", goal="act", mode="request", acting=True)
    routed = route(request, EVERYTHING, able())
    assert [c.key for c in routed.selected] == ["restart-planner"]
    assert codes(routed.selected[0]) == ["goal", "words", "mode"]

    # Asked to make something, nothing changed now: not a question either
    # (2026-10-29).
    proposal = RouteQuery(
        text="Propose un plan pour redémarrer auth-service", goal="investigate", mode="request"
    )
    made = route(proposal, EVERYTHING, able())
    assert "restart-planner" not in [c.key for c in made.excluded]


def test_retired_never_deprecated_said() -> None:
    old = replace(OWNERSHIP, key="old-ownership", lifecycle=Lifecycle.DEPRECATED)
    gone = replace(OWNERSHIP, key="gone-ownership", lifecycle=Lifecycle.RETIRED)
    asked = RouteQuery(text="Qui est responsable ?", goal="find_owner", kind="ownership")
    routed = route(asked, (OWNERSHIP, old, gone), {d.key: OK for d in (OWNERSHIP, old, gone)})
    assert [c.key for c in routed.candidates] == ["ownership", "old-ownership"]
    assert "deprecated" in codes(routed.candidates[1])
    # Within a point: both selected, the current first.
    assert [c.key for c in routed.selected] == ["ownership", "old-ownership"]


def test_every_decision_is_kept_as_the_api_reads_it() -> None:
    asked = RouteQuery(
        text="Construis l'architecture du parcours Paiement CB",
        goal="map_dependencies",
        kind="dependency",
    )
    routed = route(asked, EVERYTHING, able(application_architecture=("missing_source",)))
    read = RoutingRead.model_validate(
        {
            **decision_said(routed),
            "id": "00000000-0000-0000-0000-000000000001",
            "subject_type": "request",
            "subject_id": None,
            "version": routed.version,
            "outcome": routed.outcome,
            "selected": [c.key for c in routed.selected],
            "query": query_said(asked),
            "at": "2026-10-09T10:00:00Z",
        }
    )
    assert read.selected == ["dependencies"]
    assert read.excluded[0].reasons == [{"code": "missing_source"}]
    assert read.candidates[0].signals[0].code == "goal"
    assert read.query["goal"] == "map_dependencies"

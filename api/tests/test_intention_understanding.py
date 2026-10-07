"""What LEKA understands of an intention (LEKA-385), pure.

LEKA-373's reading (IntentPlan) is given as the context engine makes it —
its kind, the things named, the gaps — and the words; the understanding
out.

What these protect: representative intentions — why something is slow,
who owns it, what changed, what breaking it would reach, where a procedure
is, restart it, roll it back, document it — understood as a question or a
request, their goal, their actions — those that would change a customer's
systems said so — and the things they are about; ambiguous ones flagged,
blocking when LEKA cannot go on — too short, no goal, nothing named, an
action on nothing, the same words naming several things before acting —
and warnings when it can — two goals said as much, several requests, an
unknown environment; every part with the words it came from, the words
kept as asked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.context import IntentGap, IntentPlan
from leka.context.schemas import IntentKind, IntentPeriod, IntentSubject
from leka.intentions import UNDERSTANDING_VERSION, Understanding, understand
from leka.knowledge import fold

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
BILLING = uuid.uuid5(uuid.NAMESPACE_URL, "billing-api")
PAYMENT = uuid.uuid5(uuid.NAMESPACE_URL, "payment-api")


def subject(name: str, ident: uuid.UUID = BILLING, said: str | None = None) -> IntentSubject:
    return IntentSubject(
        entity_id=ident,
        name=name,
        type="service",
        facet="technical",
        how="named",
        said=said or name.casefold(),
        confidence=1.0,
    )


def plan(
    text: str,
    kind: IntentKind,
    said: list[str],
    *,
    subjects: list[IntentSubject] | None = None,
    gaps: list[IntentGap] | None = None,
    environment: str | None = None,
) -> IntentPlan:
    """LEKA-373's reading, as the context engine hands it."""
    return IntentPlan.model_construct(
        version=1,
        text=text,
        intention_id=None,
        kind=kind,
        kind_said=said,
        facets=["technical"],
        subjects=subjects if subjects is not None else [subject("Billing API")],
        period=IntentPeriod(since=NOW - timedelta(days=7), until=NOW, origin="kind"),
        environment=environment,
        constraints=[],
        # The context request it makes: not what understanding reads.
        request=None,  # type: ignore[arg-type]
        gaps=gaps or [],
    )


def gap(kind: str, severity: str = "critical", **detail: object) -> IntentGap:
    return IntentGap(kind=kind, severity=severity, said=kind, detail=detail)


def blocking(understood: Understanding) -> set[str]:
    return {a.kind for a in understood.ambiguities if a.blocking}


def warnings(understood: Understanding) -> set[str]:
    return {a.kind for a in understood.ambiguities if not a.blocking}


# ── representative intentions ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind", "said", "goal"),
    [
        (
            "Pourquoi Billing API est lente depuis hier ?",
            "diagnose",
            ["pourquoi", "lente"],
            "explain_cause",
        ),
        ("Qui est responsable de Billing API ?", "ownership", ["qui", "responsable"], "find_owner"),
        (
            "Qu'est-ce qui a changé sur Billing API cette semaine ?",
            "change",
            ["change"],
            "find_change",
        ),
        ("De quoi dépend Billing API ?", "dependency", ["depend"], "map_dependencies"),
        ("Quel est l'impact si Billing API tombe ?", "dependency", ["impact"], "assess_impact"),
        (
            "Billing API est-elle conforme au RGPD ?",
            "compliance",
            ["conforme", "rgpd"],
            "check_compliance",
        ),
        ("Comment migrer Billing API vers AWS ?", "migration", ["migrer"], "plan_migration"),
    ],
)
def test_a_question_is_understood_its_goal_said(
    text: str, kind: IntentKind, said: list[str], goal: str
) -> None:
    understood = understand(text, plan(text, kind, said))
    assert understood.mode == "question"
    assert understood.goal.code == goal
    assert understood.goal.confidence > 0
    assert [e.name for e in understood.entities] == ["Billing API"]
    assert understood.clear
    assert understood.text == text
    assert understood.version == UNDERSTANDING_VERSION


def test_where_a_procedure_is_needs_no_thing_named() -> None:
    text = "Où est la procédure de reprise des paiements ?"
    understood = understand(text, plan(text, "knowledge", ["procedure", "reprise"], subjects=[]))
    assert (understood.goal.code, understood.mode) == ("find_knowledge", "question")
    assert understood.goal.confidence == 0.8
    assert understood.clear


def test_a_request_to_act_is_said_with_what_it_would_change() -> None:
    text = "Redémarre Billing API en production"
    understood = understand(text, plan(text, "general", [], environment="production"))
    assert (understood.mode, understood.mode_said) == ("request", "redemarre")
    assert understood.goal.code == "act"
    assert understood.goal.confidence == 0.9
    [action] = understood.actions
    assert (action.code, action.said, action.changes_systems) == ("restart", "redemarre", True)
    assert understood.environment == "production"
    assert understood.clear


def test_asked_politely_with_a_question_mark_it_is_still_a_request() -> None:
    text = "Peux-tu faire un rollback de Billing API ?"
    understood = understand(text, plan(text, "general", []))
    assert (understood.mode, understood.mode_said) == ("request", "peux tu")
    assert understood.goal.code == "act"
    assert [a.code for a in understood.actions] == ["rollback"]


def test_the_noun_is_what_happened_the_verb_what_is_asked() -> None:
    """« Le déploiement » is a change to find; « déploie » an act."""
    text = "Pourquoi le déploiement de Billing API a échoué ?"
    understood = understand(text, plan(text, "diagnose", ["pourquoi", "echoue"]))
    assert understood.actions == []
    assert understood.goal.code == "explain_cause"


def test_documenting_or_opening_a_ticket_is_acting_without_changing_systems() -> None:
    text = "Documente Billing API et crée un ticket pour l'équipe"
    understood = understand(text, plan(text, "general", []))
    assert understood.goal.code == "act"
    assert {(a.code, a.changes_systems) for a in understood.actions} == {
        ("document", False),
        ("ticket", False),
    }
    assert understood.clear


def test_looking_without_a_known_kind_is_investigating() -> None:
    text = "Analyser les erreurs de connexion sur Billing API"
    understood = understand(text, plan(text, "general", []))
    assert understood.goal.code == "investigate"
    assert understood.goal.said == ["analyser"]


# ── ambiguous ──────────────────────────────────────────────────────────────


def test_too_short_or_without_a_goal_cannot_go_on() -> None:
    short = understand("Fais-le", plan("Fais-le", "general", [], subjects=[]))
    assert {"too_short", "unclear_goal"} <= blocking(short)
    assert not short.clear
    vague = "Bonjour LEKA, voici mon environnement"
    unclear = understand(vague, plan(vague, "general", [], subjects=[]))
    assert blocking(unclear) == {"unclear_goal"}
    [said] = [a for a in unclear.ambiguities if a.kind == "unclear_goal"]
    assert "explain_cause" in said.options


def test_naming_nothing_known_is_asked_what_with_what_it_may_mean() -> None:
    text = "Pourquoi c'est lent depuis hier ?"
    understood = understand(
        text,
        plan(
            text,
            "diagnose",
            ["pourquoi", "lent"],
            subjects=[],
            gaps=[gap("no_subject", maybe=["Billing API"])],
        ),
    )
    assert blocking(understood) == {"no_subject"}
    [said] = understood.ambiguities
    assert said.options == ["Billing API"]


def test_an_action_on_nothing_known_is_not_guessed() -> None:
    text = "Redémarre le service"
    understood = understand(text, plan(text, "general", [], subjects=[]))
    assert understood.goal.code == "act"
    assert understood.goal.confidence == 0.5
    assert "action_without_target" in blocking(understood)
    assert not understood.clear


def test_the_same_words_naming_several_things_block_an_act_not_a_question() -> None:
    things = [
        {"id": str(BILLING), "name": "Billing API"},
        {"id": str(PAYMENT), "name": "Payment API"},
    ]
    ambiguous = gap("ambiguous_subject", "warning", said="api", things=things)
    both = [subject("Billing API", said="api"), subject("Payment API", PAYMENT, said="api")]
    asked = "Pourquoi l'API est lente ?"
    question = understand(
        asked, plan(asked, "diagnose", ["pourquoi", "lente"], subjects=both, gaps=[ambiguous])
    )
    assert warnings(question) == {"ambiguous_subject"}
    assert question.clear
    act = "Redémarre l'API"
    request = understand(act, plan(act, "general", [], subjects=both, gaps=[ambiguous]))
    assert blocking(request) == {"ambiguous_subject"}
    [said] = request.ambiguities
    assert said.options == ["Billing API", "Payment API"]


def test_two_goals_said_as_much_are_flagged_the_first_read() -> None:
    text = "Qui a changé Billing API ?"
    understood = understand(text, plan(text, "change", ["change"]))
    assert understood.goal.code == "find_change"
    assert warnings(understood) == {"competing_goals"}
    [said] = understood.ambiguities
    assert said.options == ["find_change", "find_owner"]
    assert understood.clear


def test_several_requests_and_an_unknown_environment_are_warnings() -> None:
    text = "Redémarre Billing API et rollback Payment API en prod-eu"
    understood = understand(
        text,
        plan(
            text,
            "general",
            [],
            subjects=[subject("Billing API"), subject("Payment API", PAYMENT)],
            gaps=[
                gap("unknown_environment", "warning", environment="prod-eu", known=["production"])
            ],
        ),
    )
    assert warnings(understood) >= {"several_requests", "unknown_environment"}
    assert understood.clear
    [env] = [a for a in understood.ambiguities if a.kind == "unknown_environment"]
    assert env.options == ["production"]


# ── the words kept ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Redémarre Billing API en production",
        "Peux-tu faire un rollback de Billing API ?",
        "Pourquoi Billing API est lente depuis hier ?",
        "Documente Billing API et crée un ticket pour l'équipe",
    ],
)
def test_every_part_says_the_words_it_came_from(text: str) -> None:
    kind: IntentKind = "diagnose" if text.startswith("Pourquoi") else "general"
    said = ["pourquoi", "lente"] if kind == "diagnose" else []
    understood = understand(text, plan(text, kind, said))
    folded = fold(text)
    assert understood.text == text
    for word in understood.goal.said:
        assert word in folded
    for action in understood.actions:
        assert action.said in folded
    if understood.mode_said:
        assert understood.mode_said in folded or understood.mode_said == "?"


def test_without_lekas_reading_it_still_understands_what_it_can() -> None:
    understood = understand("Pourquoi Billing API est lente ?", None)
    assert understood.kind == "diagnose"
    assert understood.goal.code == "explain_cause"
    assert understood.entities == []
    assert understood.period is None

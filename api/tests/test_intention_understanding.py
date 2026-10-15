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

from leka.context import IntentGap, IntentPlan, kinds_said
from leka.context.schemas import IntentKind, IntentPeriod, IntentSubject
from leka.intentions import UNDERSTANDING_VERSION, Understanding, understand
from leka.intentions.understanding import unknown_names
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


def test_a_migration_to_assess_is_a_project_to_plan_never_an_act() -> None:
    # 2026-10-14: read without a model, it stopped on « à préciser ».
    text = "Je dois migrer les serveurs AWS vers Azure, évaluer les dépendances"
    understood = understand(text, plan(text, "general", [], subjects=[]))
    assert understood.goal.code == "plan_migration"
    assert not any(a.changes_systems for a in understood.actions)
    assert understood.clear
    # Asked alone, a migration is still what a person decides on.
    alone = "Migre Billing API vers AWS"
    assert understand(alone, plan(alone, "general", [])).goal.code == "act"


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


def test_a_question_naming_nothing_known_goes_on_with_what_it_may_mean() -> None:
    """LEKA's analyst looks for itself — what was slow since yesterday —
    and says what it may be about: the question is not stopped."""
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
    assert not blocking(understood)
    assert warnings(understood) == {"no_subject"}
    assert understood.clear
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


# ── negations, conditions, each action on its own (LEKA-434) ───────────────

TWO = [subject("Billing API"), subject("Payment API", PAYMENT)]


@pytest.mark.parametrize(
    "text",
    [
        "Ne redémarre pas Billing API en production",
        "Merci de ne pas redémarrer Billing API",
        "Redémarre pas Billing API",
        "Do not restart Billing API in production",
        "Don't restart Billing API",
        "Never restart Billing API",
    ],
)
def test_a_negated_action_is_not_asked_but_kept_said_so(text: str) -> None:
    understood = understand(text, plan(text, "general", []))
    assert understood.actions == []
    assert understood.goal.code != "act"
    [withheld] = understood.withheld
    assert (withheld.code, withheld.polarity) == ("restart", "negated")
    assert "ambiguous_action" not in blocking(understood)


@pytest.mark.parametrize(
    ("text", "polarity"),
    [
        ("Si Billing API tombe, redémarre-la", "conditional"),
        ("If Billing API is down, restart it", "conditional"),
        ("Je ne sais pas s'il faut redémarrer Billing API", "ambiguous"),
    ],
)
def test_a_conditional_or_doubtful_action_is_asked_before_anything(
    text: str, polarity: str
) -> None:
    understood = understand(text, plan(text, "general", []))
    assert understood.actions == []
    assert [(a.code, a.polarity) for a in understood.withheld] == [("restart", polarity)]
    assert "ambiguous_action" in blocking(understood)
    assert not understood.clear


def test_what_is_quoted_is_cited_not_asked() -> None:
    text = "Pourquoi le log de Billing API dit « restart failed » ?"
    understood = understand(text, plan(text, "diagnose", ["pourquoi"]))
    assert (understood.actions, understood.withheld) == ([], [])


def test_a_negation_after_the_action_is_not_on_it() -> None:
    text = "Redémarre Billing API qui ne répond plus"
    understood = understand(text, plan(text, "general", []))
    assert [(a.code, a.polarity) for a in understood.actions] == [("restart", "affirmed")]


@pytest.mark.parametrize(
    "text",
    [
        "Redémarre Billing API et rollback Payment API",
        "Restart Billing API and roll back Payment API",
    ],
)
def test_each_action_is_on_what_was_said_with_it(text: str) -> None:
    understood = understand(text, plan(text, "general", [], subjects=TWO))
    assert {a.code: a.targets for a in understood.actions} == {
        "restart": [BILLING],
        "rollback": [PAYMENT],
    }


def test_one_action_asked_the_other_refused() -> None:
    text = "Redémarre Billing API mais ne rollback pas Payment API"
    understood = understand(text, plan(text, "general", [], subjects=TWO))
    assert [(a.code, a.targets) for a in understood.actions] == [("restart", [BILLING])]
    assert [(a.code, a.polarity) for a in understood.withheld] == [("rollback", "negated")]


def test_two_actions_on_what_follows_them_both() -> None:
    text = "Redémarre et scale Billing API"
    understood = understand(text, plan(text, "general", []))
    assert {a.code: a.targets for a in understood.actions} == {
        "restart": [BILLING],
        "scale": [BILLING],
    }


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


# ── what a verb says without asking it (LEKA-440) ─────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Prépare un plan pour migrer Billing API vers AWS",
        "Prepare a plan to migrate Billing API to AWS",
        "Évalue le risque de migrer Billing API vers AWS",
        "Comment redémarrer Billing API proprement ?",
        "How to restart Billing API without downtime?",
    ],
)
def test_what_is_planned_or_explained_is_not_asked(text: str) -> None:
    understood = understand(text, plan(text, "general", []))
    # Evaluating is asked; migrating, what is evaluated, is not.
    assert not [a for a in understood.actions if a.changes_systems]
    assert understood.withheld == []
    assert understood.goal.code != "act"


def test_a_plan_does_not_hide_an_action_asked_with_it() -> None:
    text = "Fais un plan de migration, puis redémarre Billing API"
    understood = understand(text, plan(text, "migration", ["plan", "migration"]))
    assert [a.code for a in understood.actions] == ["restart"]


@pytest.mark.parametrize(
    "text",
    [
        "Est-ce que Billing API a été redémarrée récemment ?",
        "Qui a redémarré Billing API ?",
        "Has Billing API been restarted this week?",
        "Has Billing API been rolled back?",
    ],
)
def test_what_was_done_is_asked_about_never_asked(text: str) -> None:
    understood = understand(text, plan(text, "general", []))
    assert understood.actions == []
    assert understood.withheld == []
    assert understood.mode == "question"
    assert understood.goal.code in ("find_change", "find_owner")
    assert understood.clear


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("J'ai besoin de redémarrer Billing API", "restart"),
        ("I have to restart Billing API", "restart"),
        ("Do a rollback of Billing API", "rollback"),
        ("Pense à redémarrer Billing API", "restart"),
    ],
)
def test_an_infinitive_or_a_noun_after_an_article_is_still_asked(text: str, code: str) -> None:
    understood = understand(text, plan(text, "general", []))
    assert [a.code for a in understood.actions] == [code]


def test_updating_documentation_is_writing_it_not_changing_a_system() -> None:
    text = "Mets à jour la documentation de Billing API"
    understood = understand(text, plan(text, "knowledge", ["documentation"]))
    [action] = understood.actions
    assert (action.code, action.changes_systems) == ("document", False)
    system = "Mets à jour Billing API"
    [update] = understand(system, plan(system, "general", [])).actions
    assert (update.code, update.changes_systems) == ("update", True)


def test_a_question_about_something_known_asks_what_is_known_of_it() -> None:
    for text in ("Quel est le SLA de Billing API ?", "Sur quoi travaille Billing API ?"):
        understood = understand(text, plan(text, "general", []))
        assert understood.goal.code == "find_knowledge"
        assert understood.clear
    # Nothing that says it is a question: still asked what is wanted.
    vague = "Billing API, voilà"
    assert "unclear_goal" in blocking(understand(vague, plan(vague, "general", [])))


def test_a_name_nothing_answers_to_is_said_unknown_never_read_as_another() -> None:
    text = "Pourquoi billing-gateway est en panne ?"
    understood = understand(
        text,
        plan(text, "diagnose", ["pourquoi", "panne"], subjects=[], gaps=[gap("no_subject")]),
    )
    [unknown] = [a for a in understood.ambiguities if a.kind == "unknown_subject"]
    assert "billing-gateway" in unknown.said
    assert not unknown.blocking
    assert "no_subject" not in {a.kind for a in understood.ambiguities}
    # A verb and its pronoun, a common word, a version: not names.
    assert unknown_names("Dis-moi, peux-tu voir si le front-end en v2.8.4 est lent ?") == []
    assert unknown_names("Pourquoi billing-gateway et svc_orders sont lents ?") == [
        "billing-gateway",
        "svc_orders",
    ]


def test_what_changed_is_not_who() -> None:
    """« Qu'est-ce qui a changé »: what, not « qui » — no owner to find."""
    assert [kind for kind, _ in kinds_said("Qu'est-ce qui a changé sur Billing API ?")] == [
        "change"
    ]

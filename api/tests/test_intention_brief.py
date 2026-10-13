"""An intention's brief (LEKA-439), pure: what LEKA must know, what it knows,
what it asks — and what follows.

The words are read as LEKA reads them (understanding.py, with LEKA-373's
plan given as the context engine makes it), the answers applied as the
service applies them — the words with the rest, a thing chosen, an
environment — then the brief.

What these protect, as the ticket lists them:
- a clear intention, short or long, starts with no question;
- an incomplete one gets questions about what it lacks — never a generic
  « précisez » — each with what it could be: things by id, environments,
  goals, their own words, « je ne sais pas »;
- answers are kept and read again: a thing chosen, an environment, a goal,
  an action confirmed or declined, their own words;
- an action on an unknown target is blocked, never guessed; a question on
  one goes on, its limit said;
- a contradictory, negated or doubtful action never becomes one to propose
  until its asker says so;
- several requests in one, another language, a deliverable expected;
- what a model read is assumed, never shown as known.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from leka.context import IntentAsk
from leka.context.schemas import IntentKind, IntentSubject
from leka.intentions import understand
from leka.intentions.brief import answered, answered_ask, brief_of
from leka.intentions.schemas import (
    IntentionAnswer,
    IntentionBrief,
    Understanding,
    UnderstoodBy,
)
from tests.test_intention_understanding import NOW, gap, plan, subject

BILLING = uuid.uuid5(uuid.NAMESPACE_URL, "billing-api")
BILLING_V1 = uuid.uuid5(uuid.NAMESPACE_URL, "billing-api-v1")
PAYMENT = uuid.uuid5(uuid.NAMESPACE_URL, "payment-api")
ENVIRONMENTS = ("production", "staging")


def read(
    text: str,
    kind: IntentKind = "general",
    said: Sequence[str] = (),
    *,
    answers: Sequence[IntentionAnswer] = (),
    subjects: list[IntentSubject] | None = None,
    gaps: list[object] | None = None,
    environment: str | None = None,
    environments: Sequence[str] = (),
) -> tuple[Understanding, IntentionBrief]:
    """Read as the service reads it: answers applied to what is asked, the
    words understood, the answers taken, the brief."""
    asked = answered_ask(IntentAsk(text=text, environment=environment), answers)
    chosen = [s for s in asked.services]
    if chosen and subjects is None:
        subjects = [subject("Billing API", chosen[0])]
    understood = understand(
        asked.text,
        plan(
            asked.text,
            kind,
            list(said),
            subjects=subjects,
            gaps=gaps,  # type: ignore[arg-type]
            environment=asked.environment,
        ),
        environments=environments,
        now=NOW,
    )
    understood = answered(understood, answers)
    return understood, brief_of(understood, answers)


def slot(brief: IntentionBrief, name: str) -> tuple[str, str, str | None]:
    found = next(s for s in brief.slots if s.slot == name)
    return found.state, found.need, found.value


def asked(brief: IntentionBrief) -> list[tuple[str, bool]]:
    return [(q.kind, q.blocking) for q in brief.questions]


# ── clear: no question by reflex ────────────────────────────────────────────


def test_a_clear_short_question_starts_with_no_question() -> None:
    _, brief = read("Pourquoi Billing API est lente depuis hier ?", "diagnose", ["pourquoi"])
    assert brief.decision == "analyse"
    assert brief.questions == []
    assert slot(brief, "goal") == ("known", "blocking", "explain_cause")
    assert slot(brief, "target")[0] == "known"
    assert next(s for s in brief.slots if s.slot == "target").values == ["Billing API"]
    assert slot(brief, "expected") == ("known", "useful", "answer")
    assert not brief.acting


def test_a_long_clear_request_starts_with_no_question_either() -> None:
    text = (
        "Depuis la mise en production de mardi, plusieurs clients se plaignent que le "
        "paiement par carte échoue de temps en temps sur Billing API ; j'aimerais comprendre "
        "pourquoi les erreurs augmentent, ce qui a changé récemment et qui doit regarder ça."
    )
    _, brief = read(text, "diagnose", ["pourquoi", "erreurs"])
    assert brief.decision in ("analyse", "continue")
    assert all(not q.blocking for q in brief.questions)


def test_a_question_in_english_is_read_the_same() -> None:
    _, brief = read("Why is Billing API slow since yesterday?", "diagnose", ["why", "slow"])
    assert brief.decision == "analyse"
    assert slot(brief, "goal")[2] == "explain_cause"


def test_a_deliverable_asked_is_what_is_expected() -> None:
    text = "Fais-moi un deck PDF de l'architecture de Billing API"
    _, brief = read(text, "dependency", ["architecture"])
    assert slot(brief, "expected") == ("known", "useful", "document")


# ── incomplete: specific questions, answers read again ──────────────────────


def test_too_short_is_asked_in_their_words_then_read_with_them() -> None:
    _, brief = read("Billing", subjects=[])
    assert brief.decision == "clarify"
    [first, *_] = brief.questions
    assert first.blocking and first.free
    words = IntentionAnswer(question=first.kind, value="Qui est responsable de Billing API ?")
    _, after = read("Billing", "ownership", ["qui", "responsable"], answers=[words])
    assert after.decision == "analyse"
    assert slot(after, "goal")[2] == "find_owner"


def test_an_action_on_one_of_two_things_asks_which_by_id_then_acts_on_it() -> None:
    text = "Redémarre Billing API en production"
    things = [
        {"id": str(BILLING), "name": "Billing API", "type": "service"},
        {"id": str(BILLING_V1), "name": "Billing API v1", "type": "service"},
    ]
    understood, brief = read(
        text,
        environment="production",
        gaps=[gap("ambiguous_subject", "warning", said="billing api", things=things)],
    )
    assert brief.decision == "clarify"
    assert brief.acting
    [question] = [q for q in brief.questions if q.kind == "ambiguous_subject"]
    assert question.blocking and question.slot == "target"
    assert [(c.value, c.label) for c in question.choices] == [
        (str(BILLING), "Billing API"),
        (str(BILLING_V1), "Billing API v1"),
    ]
    # Chosen by id: its scope narrowed to it, the question no longer asked.
    chose = IntentionAnswer(question="ambiguous_subject", value=str(BILLING))
    assert answered_ask(IntentAsk(text=text), [chose]).services == [BILLING]
    _, after = read(text, environment="production", answers=[chose])
    assert after.decision == "analyse"
    assert next(s for s in after.slots if s.slot == "target").origin == "answer"


def test_an_action_on_nothing_known_asks_on_what_once_with_what_it_may_mean() -> None:
    text = "Redémarre le service en production"
    maybe = [{"id": str(PAYMENT), "name": "Payment API", "type": "service"}]
    _, brief = read(
        text,
        subjects=[],
        environment="production",
        gaps=[gap("no_subject", maybe=["Payment API"], maybe_things=maybe)],
    )
    assert brief.decision == "clarify"
    # One question about what it acts on, not two.
    targets = [q for q in brief.questions if q.slot == "target"]
    assert [q.kind for q in targets] == ["action_without_target"]
    assert [c.label for c in targets[0].choices] == ["Payment API"]


def test_an_action_whose_target_its_asker_does_not_know_is_blocked() -> None:
    text = "Redémarre le service en production"
    unknown = IntentionAnswer(question="action_without_target", unknown=True)
    understood, brief = read(text, subjects=[], environment="production", answers=[unknown])
    assert brief.decision == "block"
    assert not understood.clear
    assert slot(brief, "target")[0] == "unknown"


def test_a_question_whose_target_its_asker_does_not_know_goes_on_its_limit_said() -> None:
    text = "Pourquoi c'est lent depuis hier ?"
    unknown = IntentionAnswer(question="no_subject", unknown=True)
    understood, brief = read(
        text, "diagnose", ["pourquoi", "lent"], subjects=[], gaps=[gap("no_subject")],
        answers=[unknown],
    )
    assert brief.decision == "continue"
    assert "no_subject" in brief.limits
    assert understood.clear


def test_where_an_action_runs_is_asked_from_the_environments_known() -> None:
    text = "Redémarre Billing API"
    _, brief = read(text, environments=ENVIRONMENTS)
    [question] = [q for q in brief.questions if q.kind == "missing_environment"]
    assert question.blocking and question.slot == "scope"
    assert set(question.options) == set(ENVIRONMENTS)
    chose = IntentionAnswer(question="missing_environment", value="staging")
    understood, after = read(text, environments=ENVIRONMENTS, answers=[chose])
    assert after.decision == "analyse"
    assert slot(after, "scope")[2] == "staging"


# ── contradictory, negated, doubtful: never an action on a doubt ───────────


def test_a_negated_action_is_never_one_to_act_on() -> None:
    text = "Ne redémarre pas Billing API, dis-moi seulement pourquoi elle est lente"
    understood, brief = read(text, "diagnose", ["pourquoi", "lente"])
    assert not brief.acting
    assert understood.actions == [] or all(not a.changes_systems for a in understood.actions)
    assert brief.decision in ("analyse", "continue")


def test_a_doubtful_action_is_asked_then_done_only_on_a_yes() -> None:
    text = "Je ne sais pas s'il faut redémarrer Billing API en production"
    _, brief = read(text, environment="production")
    assert brief.decision == "clarify"
    assert ("ambiguous_action", True) in asked(brief)
    no = IntentionAnswer(question="ambiguous_action", value="no")
    understood, declined = read(text, environment="production", answers=[no])
    assert not declined.acting
    assert understood.actions == [] or all(not a.changes_systems for a in understood.actions)
    yes = IntentionAnswer(question="ambiguous_action", value="yes")
    understood, confirmed = read(text, environment="production", answers=[yes])
    assert confirmed.acting
    assert [a.code for a in understood.actions if a.changes_systems] == ["restart"]


def test_a_contradictory_request_is_asked_which_and_read_only_acts_on_nothing() -> None:
    text = "Redémarre Billing API en production sans rien modifier"
    _, brief = read(text, environment="production")
    assert brief.decision == "clarify"
    assert asked(brief) == [("conflicting_constraints", True)]
    # Only to look: nothing on systems — said, never proposed.
    look = IntentionAnswer(question="conflicting_constraints", value="read_only")
    understood, after = read(text, environment="production", answers=[look])
    assert not after.acting
    assert [a.code for a in understood.withheld] == ["restart"]
    assert after.decision == "analyse"
    # To act: « read only » no longer holds — the restart is asked.
    act = IntentionAnswer(question="conflicting_constraints", value="restart")
    understood, after = read(text, environment="production", answers=[act])
    assert after.acting and after.decision == "analyse"
    assert understood.scope is not None
    assert "read_only" not in {c.kind for c in understood.scope.constraints}


# ── several at once; a model's reading ─────────────────────────────────────


def test_several_requests_go_on_each_read_the_limit_said() -> None:
    text = "Pourquoi Billing API est lente ? Et qui en est responsable ?"
    _, brief = read(text, "diagnose", ["pourquoi", "lente"])
    assert brief.decision == "continue"
    assert "several_requests" in brief.limits


def test_a_goal_a_model_read_is_assumed_never_known() -> None:
    understood, _ = read("Billing API, c'est à qui de voir ça ?", "general", [])
    by_model = understood.model_copy(
        update={
            "goal": understood.goal.model_copy(
                update={"code": "find_owner", "said": [], "confidence": 0.8}
            ),
            "read_by": UnderstoodBy(method="model", provider="google", model="gemini"),
            "ambiguities": [],
            "clear": True,
        }
    )
    brief = brief_of(by_model)
    assert slot(brief, "goal") == ("assumed", "blocking", "find_owner")
    assert next(s for s in brief.slots if s.slot == "goal").origin == "model"


def test_the_latest_answer_to_a_question_is_the_one_kept() -> None:
    first = IntentionAnswer(question="missing_environment", value="production")
    then = IntentionAnswer(question="missing_environment", value="staging")
    asked_ = answered_ask(IntentAsk(text="Redémarre Billing API"), [first, then])
    assert asked_.environment == "staging"

"""An intention's scope (LEKA-386), pure.

LEKA-373's reading of the words, what the company model says of each thing
and the environments it knows, in; the scope and what is missing out.

What these protect: the things it is about resolved, each with what the
model says of it now, and those it excludes set apart; where — asked,
read, or held to « uniquement en staging »; when — and whether the asker
said it; deadlines, windows, read only, no downtime, urgency, a migration's
target, the services and sources the form held it to — each with its
words; and the critical information missing, routed to clarification —
where to act among several environments, where to migrate, acting while
read only, a thing removed, everything excluded — while a dormant thing is
only said.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from leka.context import IntentGap, IntentPlan
from leka.context.schemas import IntentConstraint, IntentKind, IntentPeriod, IntentSubject
from leka.intentions import Understanding, understand

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)  # a Wednesday
BILLING = uuid.uuid5(uuid.NAMESPACE_URL, "billing-api")
AUTH = uuid.uuid5(uuid.NAMESPACE_URL, "auth-service")
ENVIRONMENTS = ["production", "staging"]


def subject(name: str, ident: uuid.UUID, said: str) -> IntentSubject:
    return IntentSubject(
        entity_id=ident,
        name=name,
        type="service",
        facet="technical",
        how="named",
        said=said,
        confidence=1.0,
    )


BILLING_SAID = subject("Billing API", BILLING, "billing api")
AUTH_SAID = subject("auth-service", AUTH, "auth service")


def plan(
    text: str,
    kind: IntentKind = "general",
    *,
    subjects: list[IntentSubject] | None = None,
    environment: str | None = None,
    origin: str = "kind",
    said: str | None = None,
    constraints: list[IntentConstraint] | None = None,
    gaps: list[IntentGap] | None = None,
) -> IntentPlan:
    return IntentPlan.model_construct(
        version=1,
        text=text,
        intention_id=None,
        kind=kind,
        kind_said=[],
        facets=["technical"],
        subjects=subjects if subjects is not None else [BILLING_SAID],
        period=IntentPeriod(
            since=NOW - timedelta(days=1),
            until=NOW,
            origin=origin,
            said=said,
        ),
        environment=environment,
        constraints=constraints or [],
        request=None,  # type: ignore[arg-type]
        gaps=gaps or [],
    )


def read(
    text: str,
    reading: IntentPlan,
    *,
    lifecycles: dict[uuid.UUID, str] | None = None,
    environments: list[str] | None = None,
) -> Understanding:
    return understand(
        text,
        reading,
        lifecycles=lifecycles if lifecycles is not None else {BILLING: "active", AUTH: "active"},
        environments=ENVIRONMENTS if environments is None else environments,
        now=NOW,
    )


def constraints(understood: Understanding) -> dict[str, object]:
    assert understood.scope is not None
    return {c.kind: c.value for c in understood.scope.constraints}


def blocking(understood: Understanding) -> set[str]:
    return {a.kind for a in understood.ambiguities if a.blocking}


# ── scoped and constrained ─────────────────────────────────────────────────


def test_its_things_resolved_with_what_the_model_says_of_them_now() -> None:
    text = "Pourquoi Billing API est lente depuis hier en production ?"
    understood = read(
        text,
        plan(text, "diagnose", environment="production", origin="text", said="depuis hier"),
    )
    scope = understood.scope
    assert scope is not None
    assert [(e.name, e.lifecycle) for e in scope.entities] == [("Billing API", "active")]
    assert (scope.environments, scope.environment_origin) == (["production"], "text")
    assert scope.period is not None
    assert (scope.period.explicit, scope.period.said) == (True, "depuis hier")
    assert scope.missing == []
    assert understood.clear


def test_a_period_left_to_its_kind_is_said_not_explicit() -> None:
    text = "Pourquoi Billing API est lente ?"
    scope = read(text, plan(text, "diagnose")).scope
    assert scope is not None and scope.period is not None
    assert (scope.period.origin, scope.period.explicit) == ("kind", False)


def test_what_it_excludes_is_set_apart() -> None:
    text = "Qu'est-ce qui dépend de Billing API, sauf auth-service ?"
    understood = read(text, plan(text, "dependency", subjects=[BILLING_SAID, AUTH_SAID]))
    scope = understood.scope
    assert scope is not None
    assert [e.name for e in scope.entities] == ["Billing API"]
    assert [e.name for e in scope.excluded] == ["auth-service"]
    assert constraints(understood)["exclude"] == str(AUTH)
    assert [e.name for e in understood.entities] == ["Billing API"]


def test_boundaries_said_are_kept_with_their_words() -> None:
    text = (
        "Redémarre Billing API uniquement en staging, sans interruption, "
        "avant vendredi, hors heures ouvrées, c'est urgent"
    )
    understood = read(text, plan(text))
    found = constraints(understood)
    assert found["environment_only"] == "staging"
    assert found["no_downtime"] is True
    # Wednesday the 7th: Friday the 9th.
    assert found["deadline"] == "2026-10-09"
    assert found["window"] == "hors heures ouvrees"
    assert found["urgency"] == "high"
    scope = understood.scope
    assert scope is not None
    assert (scope.environments, scope.environment_origin) == (["staging"], "constraint")
    hard = {c.kind: c.hard for c in scope.constraints}
    assert hard["urgency"] is False and hard["deadline"] is True
    said = {c.kind: c.said for c in scope.constraints}
    assert said["deadline"] == "avant vendredi"
    assert understood.clear


def test_a_migration_says_where_to() -> None:
    text = "Comment migrer Billing API vers AWS ?"
    understood = read(text, plan(text, "migration"))
    assert understood.goal.code == "plan_migration"
    assert constraints(understood)["target"] == "aws"
    assert understood.clear


def test_what_the_form_held_it_to_is_a_hard_constraint() -> None:
    text = "Pourquoi Billing API est lente ?"
    source = uuid.uuid4()
    understood = read(
        text,
        plan(
            text,
            "diagnose",
            constraints=[
                IntentConstraint(
                    kind="services", value=[str(BILLING)], origin="asked", said="asked"
                ),
                IntentConstraint(kind="sources", value=[str(source)], origin="asked", said="asked"),
            ],
        ),
    )
    scope = understood.scope
    assert scope is not None
    assert scope.sources == [source]
    assert constraints(understood)["services"] == [str(BILLING)]


def test_reading_only_is_a_boundary_for_a_question() -> None:
    text = "Analyse les erreurs de Billing API sans rien modifier"
    understood = read(text, plan(text))
    assert constraints(understood)["read_only"] is True
    assert understood.clear


# ── incomplete, ambiguous, at odds ─────────────────────────────────────────


def test_acting_among_several_environments_asks_which() -> None:
    text = "Redémarre Billing API"
    understood = read(text, plan(text))
    assert blocking(understood) == {"missing_environment"}
    [missing] = [a for a in understood.ambiguities if a.kind == "missing_environment"]
    assert missing.options == ENVIRONMENTS
    assert understood.scope is not None and understood.scope.missing == ["missing_environment"]
    # One environment known: it is where.
    assert read(text, plan(text), environments=["production"]).clear


def test_a_migration_without_where_to_is_asked() -> None:
    text = "Il faut migrer Billing API"
    understood = read(text, plan(text, "migration"))
    assert "missing_target" in blocking(understood)


def test_acting_and_changing_nothing_are_at_odds() -> None:
    text = "Redémarre Billing API en production sans rien modifier"
    understood = read(text, plan(text, environment="production", origin="text"))
    assert blocking(understood) == {"conflicting_constraints"}


def test_a_thing_removed_is_not_acted_on_a_dormant_one_only_said() -> None:
    text = "Redémarre Billing API en production"
    gone = read(text, plan(text, environment="production"), lifecycles={BILLING: "removed"})
    assert blocking(gone) == {"subject_gone"}
    question = "Pourquoi Billing API est lente ?"
    dormant = read(question, plan(question, "diagnose"), lifecycles={BILLING: "dormant"})
    assert dormant.clear
    assert {a.kind for a in dormant.ambiguities} == {"subject_dormant"}


def test_everything_named_and_excluded_leaves_nothing_to_look_at() -> None:
    text = "Pourquoi tout est lent, sauf Billing API ?"
    understood = read(text, plan(text, "diagnose"))
    assert understood.scope is not None and understood.scope.entities == []
    assert "everything_excluded" in blocking(understood)


def test_without_the_model_s_word_the_scope_is_still_read() -> None:
    text = "Pourquoi Billing API est lente ?"
    understood = understand(text, plan(text, "diagnose"), now=NOW)
    scope = understood.scope
    assert scope is not None
    assert scope.entities[0].lifecycle is None
    assert understood.clear

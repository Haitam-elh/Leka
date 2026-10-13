"""What an intention asks for, read from its words (LEKA-373):
leka.context.intent.

Asked on Wednesday 7 October 2026 at 15:30 UTC, about Acme: payment-api,
its runbook, auth-service, postgres-prod.

What these protect: an intention's kind from its words, in French and in
English, a diagnosis first on a tie; each kind's profile; a period from
its words — yesterday, this week, last week, the last N days or hours,
since a weekday, a date as written or as said, since an event — and none
when they say none; where, from its words, an environment's alias or its
name, never a word of a thing's name; the things it names — by name, by
key, by every word of a name in either language — and what it only
guesses; what is missing before anything is read, and in a version.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from leka.context.intent import (
    PROFILES,
    Readable,
    environment_of,
    kind_of,
    named,
    period_of,
    plan_gaps,
    version_gaps,
)
from leka.context.schemas import (
    ContextConflictRead,
    ContextRequest,
    IntentPeriod,
    IntentPlan,
    IntentSubject,
    RetrieverRunRead,
)
from leka.knowledge import EntityBrief, EntityType, Lifecycle

NOW = datetime(2026, 10, 7, 15, 30, tzinfo=UTC)
TODAY = datetime(2026, 10, 7, tzinfo=UTC)


def _brief(name: str, kind: EntityType = EntityType.SERVICE, key: str | None = None) -> EntityBrief:
    return EntityBrief(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"intent/{name}"),
        type=kind,
        key=key or f"{kind.value}:{name.lower()}",
        name=name,
        lifecycle=Lifecycle.ACTIVE,
    )


PAYMENT = _brief("payment-api")
RUNBOOK = _brief("Payment API runbook", EntityType.DOCUMENT)
AUTH = _brief("auth-service", key="svc-auth")
POSTGRES = _brief("postgres-prod", EntityType.DATABASE)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Pourquoi l'API de paiement est-elle plus lente depuis hier ?", "diagnose"),
        ("Why does checkout fail since the deploy?", "diagnose"),
        ("Qu'est-ce qui a changé sur payment-api cette semaine ?", "change"),
        ("What was deployed to billing yesterday?", "change"),
        ("Qui est responsable de auth-service ?", "ownership"),
        ("Comment Checkout est-il relié à la facturation ?", "dependency"),
        ("Est-ce que user-service respecte nos règles de sécurité ?", "compliance"),
        ("Prépare un plan pour migrer postgres-prod sans interruption.", "migration"),
        ("Où est la procédure de reprise des paiements ?", "knowledge"),
        ("Montre-moi payment-api.", "general"),
    ],
)
def test_an_intentions_kind_is_read_from_its_words(text: str, kind: str) -> None:
    found, said = kind_of(text)
    assert found == kind
    assert bool(said) == (kind != "general")


def test_a_diagnosis_wins_a_tie_and_each_kind_has_its_profile() -> None:
    # "pourquoi" and "deploiement": one word each — the diagnosis first.
    assert kind_of("Pourquoi ce déploiement ?") == ("diagnose", ["pourquoi"])
    assert PROFILES["change"].weights == {"timeline": 2.0}
    assert PROFILES["diagnose"].events and PROFILES["diagnose"].subject
    assert "business" in PROFILES["dependency"].facets
    assert "owned_by" in PROFILES["ownership"].relationships


@pytest.mark.parametrize(
    ("text", "since", "until", "said"),
    [
        ("plus lente depuis hier", TODAY - timedelta(days=1), NOW, "hier"),
        ("what broke today?", TODAY, NOW, "today"),
        ("cette semaine", datetime(2026, 10, 5, tzinfo=UTC), NOW, "cette semaine"),
        (
            "la semaine dernière",
            datetime(2026, 9, 28, tzinfo=UTC),
            datetime(2026, 10, 5, tzinfo=UTC),
            "la semaine derniere",
        ),
        ("depuis 3 jours", NOW - timedelta(days=3), NOW, "3 jours"),
        ("in the last 24h", NOW - timedelta(hours=24), NOW, "24h"),
        ("les 2 dernières heures", NOW - timedelta(hours=2), NOW, "2 dernieres heures"),
        ("depuis lundi", datetime(2026, 10, 5, tzinfo=UTC), NOW, "depuis lundi"),
        ("since thursday", datetime(2026, 10, 1, tzinfo=UTC), NOW, "since thursday"),
        (
            "le 3 octobre",
            datetime(2026, 10, 3, tzinfo=UTC),
            datetime(2026, 10, 4, tzinfo=UTC),
            "2026-10-03",
        ),
        ("depuis le 2026-10-01", datetime(2026, 10, 1, tzinfo=UTC), NOW, "depuis 2026-10-01"),
        # Asked in October, "28 décembre" is last year's.
        (
            "le 28 décembre",
            datetime(2025, 12, 28, tzinfo=UTC),
            datetime(2025, 12, 29, tzinfo=UTC),
            "2025-12-28",
        ),
    ],
)
def test_a_period_is_read_from_its_words(
    text: str, since: datetime, until: datetime, said: str
) -> None:
    read = period_of(text, NOW)
    assert read is not None
    assert (read.since, read.until, read.said, read.anchor) == (since, until, said, None)


def test_since_an_event_is_read_later_and_no_word_no_period() -> None:
    read = period_of("Pourquoi c'est lent depuis le déploiement ?", NOW)
    assert read is not None
    assert (read.since, read.anchor, read.said) == (None, "deployment", "depuis le deploiement")
    assert period_of("since the last incident", NOW).anchor == "incident"  # type: ignore[union-attr]
    assert period_of("Qui est responsable de auth-service ?", NOW) is None
    # v2.8.4 and p99 are no period.
    assert period_of("payment-api v2.8.4 p99 above 2s", NOW) is None


def test_where_is_read_from_an_alias_or_a_name_never_a_thing_s_name() -> None:
    known = ["production", "staging", "eu-west"]
    assert environment_of("lent en prod ?", known) == ("production", "prod")
    assert environment_of("errors in eu-west", known) is None  # « eu west »: two words
    assert environment_of("en staging", known) == ("staging", "staging")
    assert environment_of("en recette", known) == ("staging", "recette")
    # The model knows none: the word's environment, as LEKA names it.
    assert environment_of("en recette", []) == ("staging", "recette")
    assert environment_of("migrer postgres-prod", known, besides={"postgres", "prod"}) is None
    assert environment_of("payment-api", known) is None


def test_what_it_names_by_name_key_or_every_word_and_what_it_guesses() -> None:
    found = named("Pourquoi l'API de paiement est lente ?", [PAYMENT, RUNBOOK, AUTH, POSTGRES])
    assert [(n.entity.name, n.confidence, n.said) for n in found] == [
        ("payment-api", 0.8, "payment api"),
        ("Payment API runbook", 0.5, "payment api"),
    ]
    assert [(n.entity.name, n.confidence) for n in named("et auth-service ?", [AUTH])] == [
        ("auth-service", 1.0)
    ]
    assert [n.entity.name for n in named("le service svc-auth", [AUTH])] == ["auth-service"]
    assert named("postgres", [POSTGRES]) == [] or named("postgres", [POSTGRES])[0].confidence == 0.5
    assert named("Qui gère la facturation ?", [PAYMENT, AUTH]) == []
    # A word a name takes as written names nothing else by what it means.
    billing, invoicing = _brief("Billing API"), _brief("Invoicing", EntityType.BUSINESS_CAPABILITY)
    assert [
        n.entity.name for n in named("Qu'a changé sur Billing API ?", [billing, invoicing])
    ] == ["Billing API"]
    # « facturation » is invoicing, and half of « Billing API »: a guess.
    assert [
        (n.entity.name, n.confidence) for n in named("la facturation", [billing, invoicing])
    ] == [
        ("Invoicing", 0.8),
        ("Billing API", 0.5),
    ]


def _readable(*capabilities: str) -> Readable:
    return Readable(uuid.uuid4(), "GitHub", "github", frozenset(capabilities))


def test_before_anything_is_read_what_is_missing_is_said() -> None:
    gaps = plan_gaps(
        "diagnose",
        subjects=0,
        guesses=named("l'API de paiement", [RUNBOOK]),
        ambiguous={"checkout": [_brief("Checkout"), _brief("Checkout", EntityType.APPLICATION)]},
        unknown_services=[uuid.uuid4()],
        environment=("recette", "recette"),
        known_environments=["production"],
        sources=[_readable("pages")],
        anchor="deployment",
        anchored=False,
        tried=["api", "paiement"],
    )
    assert [(g.kind, g.severity) for g in gaps] == [
        ("no_subject", "critical"),
        ("ambiguous_subject", "warning"),
        ("unknown_service", "critical"),
        ("unknown_environment", "warning"),
        ("no_source_for", "critical"),
        ("no_event_anchor", "warning"),
    ]
    detail = gaps[0].detail
    assert (detail["tried"], detail["maybe"]) == (["api", "paiement"], ["Payment API runbook"])
    # The same, by id, to be chosen (LEKA-439).
    assert [t["name"] for t in detail["maybe_things"]] == ["Payment API runbook"]  # type: ignore[union-attr,index]
    # A kind that needs no subject, sources that can read it: nothing.
    assert (
        plan_gaps(
            "knowledge",
            subjects=0,
            guesses=[],
            ambiguous={},
            unknown_services=[],
            environment=None,
            known_environments=[],
            sources=[_readable("pages")],
            anchor=None,
            anchored=False,
            tried=[],
        )
        == []
    )
    # Not about what happened: a source missing is a warning.
    (gap,) = plan_gaps(
        "ownership",
        subjects=1,
        guesses=[],
        ambiguous={},
        unknown_services=[],
        environment=None,
        known_environments=[],
        sources=[],
        anchor=None,
        anchored=False,
        tried=[],
    )
    assert (gap.kind, gap.severity) == ("no_source_for", "warning")


def _plan(kind: str = "change", facets: list[str] | None = None) -> IntentPlan:
    subject = IntentSubject(
        entity_id=PAYMENT.id,
        name="payment-api",
        type="service",
        facet="technical",
        how="named",
        confidence=1.0,
    )
    return IntentPlan.model_validate(
        {
            "version": 1,
            "text": "x",
            "intention_id": None,
            "kind": kind,
            "kind_said": [],
            "facets": facets or ["technical", "temporal"],
            "subjects": [subject],
            "period": IntentPeriod(since=NOW - timedelta(days=7), until=NOW, origin="kind"),
            "environment": None,
            "constraints": [],
            "request": ContextRequest.model_validate(
                {
                    "roots": [],
                    "query": "x",
                    "depth": 1,
                    "relationships": [],
                    "environment": None,
                    "limit": 100,
                    "window_days": 7,
                    "until": None,
                    "retrievers": [],
                    "strategy": "hybrid",
                }
            ),
            "gaps": [],
        }
    )


def _run(retriever: str, status: str = "ok", found: int = 3) -> RetrieverRunRead:
    return RetrieverRunRead.model_validate(
        {
            "retriever": retriever,
            "version": 1,
            "status": status,
            "found": found,
            "ms": 1,
            "detail": None,
            "error": None,
        }
    )


def test_in_a_version_what_is_missing_is_said() -> None:
    conflict = ContextConflictRead(
        id="attribute:x:tier",
        kind="attribute",
        subject=PAYMENT.id,
        label="payment-api",
        about="tier",
        values=[],
        refs=[PAYMENT.id],
        said="The sources of payment-api disagree on tier.",
    )
    gaps = version_gaps(
        _plan("change", ["technical", "business"]),
        retrieval=[_run("timeline", found=0), _run("content", "timeout", 0)],
        by_type={"service": 3},
        conflicts=[conflict],
        model_built_at=NOW - timedelta(days=3),
        assembled_at=NOW,
    )
    assert [(g.kind, g.severity) for g in gaps] == [
        ("model_stale", "warning"),
        ("nothing_happened", "critical"),
        ("retriever_failed", "warning"),
        ("no_business", "warning"),
        ("disputed_subject", "warning"),
    ]
    assert gaps[0].detail == {"hours": 72}
    # Never built; a diagnosis with nothing happened is a warning only.
    never = version_gaps(
        _plan("diagnose"),
        retrieval=[_run("timeline", found=0)],
        by_type={},
        conflicts=[],
        model_built_at=None,
        assembled_at=NOW,
    )
    assert [(g.kind, g.severity) for g in never] == [
        ("model_not_built", "critical"),
        ("nothing_happened", "warning"),
    ]
    # Something happened, a fresh model, the business side there: nothing.
    assert (
        version_gaps(
            _plan("dependency", ["technical", "business"]),
            retrieval=[_run("timeline")],
            by_type={"application": 1},
            conflicts=[],
            model_built_at=NOW - timedelta(hours=1),
            assembled_at=NOW,
        )
        == []
    )

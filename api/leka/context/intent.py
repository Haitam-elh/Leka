"""What an intention asks the company model for (LEKA-373): its kind, what
it is about, when, where — read from its words — and what it needs that is
missing.

Pure — no database, no clock: what the model holds and the time it is are
given. ContextService.plan_intent() gathers those and settles the request.

    kind_of()       its kind, from its words: diagnose — why is it slow,
                    failing, down; change — what changed, was deployed;
                    ownership — who owns, who answers; dependency — what is
                    tied to what; compliance — security, rules, audit;
                    migration — moving, replacing, planning; knowledge — a
                    procedure, a runbook; general otherwise
    PROFILES        what each kind reads: its facets — technical, business,
                    organizational, temporal — how far, how far back, which
                    retrievers weigh more, through which ties, and what its
                    sources must be able to read
    period_of()     when, from its words: « depuis hier », « cette semaine »,
                    « la semaine dernière », « depuis 3 jours », « since the
                    deploy », « le 3 octobre », 2026-10-03
    environment_of() where, from its words: « en production », « staging »
    named()         the things it names: by name, by key, or by every word
                    of a name — « l'API de paiement » names payment-api
    plan_gaps(), version_gaps()  what it needs that is missing, before
                    and after its context is assembled

Deliberately words, not a model: each reading says which words it came
from, so that what LEKA understood can be checked — and corrected by
asking differently, or by choosing the scope.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from leka.context.language import STOPWORDS, expanded, words
from leka.context.schemas import (
    ContextConflictRead,
    Facet,
    IntentGap,
    IntentKind,
    IntentPlan,
    RetrieverRunRead,
)
from leka.knowledge import EntityBrief, fold

# Raised each time intentions are read differently; kept with every plan.
INTENT_VERSION = 1
# What a thing named is, at least, to be a subject; below, a guess.
NAMED = 0.8
PARTIAL = 0.5
MAX_NAMED = 5
MAX_BUSINESS = 3
# A model older than this, against the time a context was made, is stale.
STALE = timedelta(hours=24)

# ── kinds ───────────────────────────────────────────────────────────────────


# The words that say each kind, folded, in French and in English. The first
# kind on a tie wins: a question about why something fails is a diagnosis,
# whatever else it mentions.
def _said(said: str) -> frozenset[str]:
    return frozenset(said.split())


KIND_WORDS: dict[IntentKind, frozenset[str]] = {
    "diagnose": _said(
        """pourquoi why lent lente lents lenteur slow slower latence latency panne down
        outage erreur erreurs error errors echec echoue echouent fail fails failing failed
        incident incidents bug bugs crash plante timeout timeouts indisponible unavailable
        degrade degradation ralenti ralentit broken casse"""
    ),
    "change": _said(
        """change changes changed changement changements change modifie modification
        modifications deploye deployee deploiement deploiements deploy deployed deployment
        deployments release releases livraison livre version versions merge merged"""
    ),
    # Not « migrations »: the plural is a thing of the code — « les migrations
    # Alembic » of a database review — far more than a move asked (2026-10-24).
    "migration": _said(
        """migrer migration migrate migrating remplacer replace replacing
        decommissionner decommission plan planifier moderniser modernize upgrade refonte
        deplacer move"""
    ),
    "compliance": _said(
        """conformite compliance conforme compliant securite security rgpd gdpr audit
        regles rules policy policies politique risque risk risques vulnerabilite
        vulnerabilites vulnerability chiffrement encryption"""
    ),
    "dependency": _said(
        """depend depends dependance dependances dependency dependencies relie reliee
        relies connecte connected lie liee linked architecture appelle calls utilise
        uses consomme consumes impacte impact impacts"""
    ),
    "ownership": _said(
        """qui who owner owners owns owned proprietaire proprietaires responsable
        responsables equipe team teams maintient maintains maintainer contact astreinte
        oncall lead"""
    ),
    "knowledge": _said(
        """procedure procedures runbook runbooks documentation doc docs comment how guide
        reprise recovery restaurer restore processus process"""
    ),
}


@dataclass(frozen=True)
class Profile:
    """What an intention of a kind reads, and needs."""

    facets: tuple[Facet, ...]
    depth: int
    window_days: int
    weights: Mapping[str, float] = field(default_factory=dict)
    relationships: tuple[str, ...] = ()
    # What its sources must be able to read — any of these capabilities.
    needs: frozenset[str] = frozenset()
    # Whether it is about a thing that must be found.
    subject: bool = False
    # Whether what happened is what it is about.
    events: bool = False


WHAT_HAPPENS = frozenset(
    {"incidents", "alerts", "events", "metrics", "logs", "deployments", "changes"}
)
WHAT_SHIPS = frozenset({"deployments", "changes", "releases", "commits", "pull_requests"})
WHO = frozenset({"teams", "people", "components", "repositories"})
WHAT_RUNS = frozenset(
    {"components", "services", "repositories", "instances", "clusters", "databases", "functions"}
)
WHAT_IS_WRITTEN = frozenset({"pages", "spaces", "files", "records"})

PROFILES: dict[IntentKind, Profile] = {
    "diagnose": Profile(
        facets=("technical", "temporal", "organizational"),
        depth=2,
        window_days=7,
        weights={"timeline": 1.5, "paths": 1.0},
        needs=WHAT_HAPPENS,
        subject=True,
        events=True,
    ),
    "change": Profile(
        facets=("technical", "temporal"),
        depth=1,
        window_days=14,
        weights={"timeline": 2.0},
        needs=WHAT_SHIPS,
        subject=True,
        events=True,
    ),
    "ownership": Profile(
        facets=("organizational", "technical"),
        depth=2,
        window_days=30,
        weights={"graph": 1.5, "search": 1.2, "timeline": 0.5},
        relationships=(
            "owns",
            "owned_by",
            "member_of",
            "maintained_by",
            "led_by",
            "reports_to",
            "contributes_to",
            "authored_by",
        ),
        needs=WHO,
        subject=True,
    ),
    "dependency": Profile(
        facets=("technical", "business"),
        depth=2,
        window_days=30,
        weights={"graph": 1.3, "paths": 1.5, "timeline": 0.5},
        relationships=(
            "depends_on",
            "uses",
            "reads_from",
            "deployed_to",
            "runs_in",
            "part_of",
            "implements",
            "realizes",
            "supported_by",
            "in_network",
            "child_of",
        ),
        needs=WHAT_RUNS,
        subject=True,
    ),
    "compliance": Profile(
        facets=("business", "technical", "organizational"),
        depth=2,
        window_days=90,
        weights={"content": 1.5, "search": 1.2},
        needs=WHAT_IS_WRITTEN,
    ),
    "migration": Profile(
        facets=("technical", "business", "organizational"),
        depth=2,
        window_days=30,
        weights={"graph": 1.3, "paths": 1.3},
        needs=WHAT_RUNS,
        subject=True,
    ),
    "knowledge": Profile(
        facets=("technical",),
        depth=1,
        window_days=90,
        weights={"content": 2.0, "search": 1.3, "timeline": 0.5},
        needs=WHAT_IS_WRITTEN,
    ),
    "general": Profile(facets=("technical", "temporal"), depth=1, window_days=14),
}

FACETS: dict[str, Facet] = {
    "application": "business",
    "business_capability": "business",
    "business_process": "business",
    "team": "organizational",
    "person": "organizational",
    "project": "organizational",
}
BUSINESS: tuple[str, ...] = ("application", "business_capability", "business_process")


def facet_of(entity_type: str) -> Facet:
    """Which side of the company a thing is: business, organizational —
    or technical, everything a system is made of."""
    return FACETS.get(entity_type, "technical")


def kind_of(text: str) -> tuple[IntentKind, list[str]]:
    """Its kind, and the words that said it — general when none did."""
    found = kinds_said(text)
    return found[0] if found else ("general", [])


def kinds_said(text: str) -> list[tuple[IntentKind, list[str]]]:
    """Every kind its words say, the most said first — the first declared
    on a tie — with the words that said each (LEKA-385: two kinds said as
    much are two goals to choose between)."""
    said = fold(text).split()
    # « Qu'est-ce qui a changé », « ce qui dépend »: what, not who (LEKA-440).
    said = [w for i, w in enumerate(said) if not (w == "qui" and i and said[i - 1] == "ce")]
    found: list[tuple[IntentKind, list[str]]] = []
    for kind, words_of in KIND_WORDS.items():
        words_found = list(dict.fromkeys(word for word in said if word in words_of))
        if words_found:
            found.append((kind, words_found))
    return sorted(found, key=lambda item: -len(item[1]))


# ── when ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Said:
    """A period read from words: since, until, the words — or an event it
    is read from (« since the deploy »), found later in the model."""

    since: datetime | None
    until: datetime | None
    said: str
    anchor: str | None = None


_UNITS: dict[str, timedelta] = {
    "minute": timedelta(minutes=1),
    "minutes": timedelta(minutes=1),
    "min": timedelta(minutes=1),
    "heure": timedelta(hours=1),
    "heures": timedelta(hours=1),
    "h": timedelta(hours=1),
    "hour": timedelta(hours=1),
    "hours": timedelta(hours=1),
    "jour": timedelta(days=1),
    "jours": timedelta(days=1),
    "j": timedelta(days=1),
    "day": timedelta(days=1),
    "days": timedelta(days=1),
    "semaine": timedelta(weeks=1),
    "semaines": timedelta(weeks=1),
    "week": timedelta(weeks=1),
    "weeks": timedelta(weeks=1),
    "mois": timedelta(days=30),
    "month": timedelta(days=30),
    "months": timedelta(days=30),
}
_WEEKDAYS = {
    "lundi": 0,
    "monday": 0,
    "mardi": 1,
    "tuesday": 1,
    "mercredi": 2,
    "wednesday": 2,
    "jeudi": 3,
    "thursday": 3,
    "vendredi": 4,
    "friday": 4,
    "samedi": 5,
    "saturday": 5,
    "dimanche": 6,
    "sunday": 6,
}
_MONTHS = {
    "janvier": 1,
    "january": 1,
    "jan": 1,
    "fevrier": 2,
    "february": 2,
    "feb": 2,
    "fev": 2,
    "mars": 3,
    "march": 3,
    "mar": 3,
    "avril": 4,
    "april": 4,
    "apr": 4,
    "avr": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "jun": 6,
    "juillet": 7,
    "july": 7,
    "jul": 7,
    "juil": 7,
    "aout": 8,
    "august": 8,
    "aug": 8,
    "septembre": 9,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "octobre": 10,
    "october": 10,
    "oct": 10,
    "novembre": 11,
    "november": 11,
    "nov": 11,
    "decembre": 12,
    "december": 12,
    "dec": 12,
}
_ANCHORS = {
    "deploiement": "deployment",
    "deploy": "deployment",
    "deployment": "deployment",
    "mise en production": "deployment",
    "release": "release",
    "livraison": "release",
    "version": "release",
    "changement": "change",
    "change": "change",
    "incident": "incident",
}
_ANCHOR = re.compile(
    r"\b(?:depuis|since) (?:le |la |l |the )?(?:dernier |derniere |last )?"
    r"(mise en production|deploiement|deployment|deploy|release|livraison|version|changement"
    r"|change|incident)\b"
)
_ISO = re.compile(r"\b(\d{4}) (\d{1,2}) (\d{1,2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r")\b")
_MONTH_DAY = re.compile(r"\b(" + "|".join(_MONTHS) + r") (\d{1,2})\b")
_LAST_N = re.compile(
    r"\b(\d{1,3}) ?(?:derniers |dernieres |last |past )?(" + "|".join(_UNITS) + r")\b"
)
_SINCE_WEEKDAY = re.compile(r"\b(?:depuis|since) (" + "|".join(_WEEKDAYS) + r")\b")


def period_of(text: str, now: datetime) -> Said | None:
    """When its words say it looks — none when they do not say."""
    said = fold(text)
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if found := _ANCHOR.search(said):
        return Said(None, now, found.group(0), anchor=_ANCHORS[found.group(1)])
    since_word = re.search(r"\b(?:depuis|since|from|a partir du|a partir de)\b", said)
    for day in _dates(said, now):
        starts = day.replace(tzinfo=UTC)
        if since_word:
            return Said(starts, now, f"{since_word.group(0)} {starts.date().isoformat()}")
        return Said(starts, starts + timedelta(days=1), starts.date().isoformat())
    if found := _LAST_N.search(said):
        count, unit = int(found.group(1)), found.group(2)
        if count > 0:
            return Said(now - count * _UNITS[unit], now, found.group(0))
    if found := _SINCE_WEEKDAY.search(said):
        back = (today.weekday() - _WEEKDAYS[found.group(1)]) % 7
        return Said(today - timedelta(days=back), now, found.group(0))
    named: tuple[tuple[str, datetime, datetime], ...] = (
        (r"\b(?:la semaine derniere|semaine passee|last week)\b", *_last_week(today)),
        (r"\b(?:le mois dernier|mois passe|last month)\b", *_last_month(today)),
        (r"\b(?:cette semaine|this week)\b", today - timedelta(days=today.weekday()), now),
        (r"\b(?:ce mois ci|ce mois|this month)\b", today.replace(day=1), now),
        (r"\b(?:cette nuit|last night|tonight)\b", today - timedelta(hours=6), now),
        (r"\b(?:hier|yesterday)\b", today - timedelta(days=1), now),
        (r"\b(?:aujourd hui|today|ce matin|this morning)\b", today, now),
    )
    for pattern, since, until in named:
        if found := re.search(pattern, said):
            return Said(since, until, found.group(0))
    return None


def _dates(said: str, now: datetime) -> Iterable[datetime]:
    """The days its words name: 2026-10-03, « 3 octobre », « october 3 »."""
    for year, month, day in _ISO.findall(said):
        if found := _day(int(year), int(month), int(day)):
            yield found
    for day, month in _DAY_MONTH.findall(said):
        if found := _day(now.year, _MONTHS[month], int(day), before=now):
            yield found
    for month, day in _MONTH_DAY.findall(said):
        if found := _day(now.year, _MONTHS[month], int(day), before=now):
            yield found


def _day(year: int, month: int, day: int, *, before: datetime | None = None) -> datetime | None:
    try:
        found = datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None
    # « le 28 décembre », asked in January, is last year's.
    if before is not None and found > before:
        return _day(year - 1, month, day)
    return found


def _last_week(today: datetime) -> tuple[datetime, datetime]:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=1), monday


def _last_month(today: datetime) -> tuple[datetime, datetime]:
    first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    return previous, first


# ── where ───────────────────────────────────────────────────────────────────

ENVIRONMENT_WORDS: dict[str, tuple[str, ...]] = {
    "production": ("production", "prod", "prd", "live"),
    "staging": ("staging", "preprod", "preproduction", "recette", "uat"),
    "development": ("development", "developpement", "dev"),
    "test": ("test", "testing", "qa"),
}


def environment_of(
    text: str, known: Sequence[str], *, besides: Iterable[str] = ()
) -> tuple[str, str] | None:
    """Where its words say it looks, as the model names it — and the word
    that said it. « en prod » is production when the model knows a
    production; an environment the model knows by name is itself. The
    words of a thing's name — `besides` — say nothing of where."""
    left_out = set(besides)
    said = [word for word in fold(text).split() if word not in left_out]
    names = {fold(name): name for name in known}
    for word in said:
        if word in names and word not in STOPWORDS:
            return names[word], word
    for canonical, aliases in ENVIRONMENT_WORDS.items():
        for word in said:
            if word in aliases:
                found = next((names[n] for n in names if n == canonical or n in aliases), None)
                return (found or canonical), word
    return None


# ── what it names ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Named:
    """A thing its words name, how surely, by which words."""

    entity: EntityBrief
    confidence: float
    said: str


def named(text: str, candidates: Iterable[EntityBrief]) -> list[Named]:
    """The things `text` names, the surest first: by its name or key as
    written (1), or by every word of its name, in either language (0.8);
    by half its words, a guess (0.5). A word a name takes as written names
    nothing else: « Billing API » is not also the Invoicing its « billing »
    could mean."""
    folded = f" {fold(text)} "
    things = list(candidates)
    found: list[Named] = []
    taken: set[str] = set()
    for entity in things:
        name = fold(entity.name)
        if not name:
            continue
        if f" {name} " in folded or f" {fold(entity.key)} " in folded:
            found.append(Named(entity, 1.0, entity.name))
            taken |= set(name.split())
    # A repository by its name without its owner — unless a name as written
    # took those words: « Billing API » is the service, not acme/billing-api.
    for entity in things:
        short = _short(entity)
        if (
            short
            and f" {short} " in folded
            and not set(short.split()) <= taken
            and entity.id not in {n.entity.id for n in found}
        ):
            found.append(Named(entity, NAMED, short))
            taken |= set(short.split())
    exact = {n.entity.id for n in found}
    left = [word for word in fold(text).split() if word not in taken]
    vocabulary = set(left) | set(expanded(w for w in words(text) if w not in taken))
    for entity in things:
        name = fold(entity.name)
        if not name or entity.id in exact:
            continue
        parts = [part for part in name.split() if part not in STOPWORDS] or name.split()
        covered = [part for part in parts if _held(part, vocabulary)]
        if not covered:
            continue
        share = len(covered) / len(parts)
        if share == 1:
            found.append(Named(entity, NAMED, " ".join(covered)))
        elif share >= PARTIAL and len(parts) > 1:
            found.append(Named(entity, PARTIAL, " ".join(covered)))
    return sorted(found, key=lambda n: (-n.confidence, n.entity.name.casefold(), str(n.entity.id)))


def _short(entity: EntityBrief) -> str | None:
    """A repository's name without its owner — « leka » of « Haitam-elh/Leka »:
    what the people who work on it call it (2026-10-29: « déployer sur
    leka » named nothing)."""
    if entity.type.value != "repository" or "/" not in entity.name:
        return None
    short = fold(entity.name.rsplit("/", 1)[-1])
    return short if len(short) > 2 and short not in STOPWORDS else None


def _held(part: str, vocabulary: set[str]) -> bool:
    """A word of a name, in the words said — its singular too."""
    return any(form in vocabulary for form in (part, part.removesuffix("s")) if len(form) > 1)


# ── what is missing ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Readable:
    """A source an intention can read: what it is, what it can read."""

    source_id: uuid.UUID
    name: str
    kind: str
    capabilities: frozenset[str]


def plan_gaps(
    kind: IntentKind,
    *,
    subjects: int,
    guesses: Sequence[Named],
    ambiguous: Mapping[str, Sequence[EntityBrief]],
    unknown_services: Sequence[uuid.UUID],
    environment: tuple[str, str] | None,
    known_environments: Sequence[str],
    sources: Sequence[Readable],
    anchor: str | None,
    anchored: bool,
    tried: Sequence[str],
) -> list[IntentGap]:
    """What an intention needs that is missing, before anything is read."""
    profile = PROFILES[kind]
    gaps: list[IntentGap] = []
    if profile.subject and subjects == 0:
        gaps.append(
            IntentGap(
                kind="no_subject",
                severity="critical",
                said="Nothing in the company model is named by the intention: the context is "
                "what its words find, not what it is about.",
                detail={
                    "tried": list(tried),
                    "maybe": [g.entity.name for g in guesses[:3]],
                    # By id, to be chosen (LEKA-439).
                    "maybe_things": [
                        {"id": str(g.entity.id), "name": g.entity.name, "type": g.entity.type.value}
                        for g in guesses[:3]
                    ],
                },
            )
        )
    for said, things in ambiguous.items():
        gaps.append(
            IntentGap(
                kind="ambiguous_subject",
                severity="warning",
                said=f"« {said} » names {len(things)} things; each is read.",
                detail={
                    "said": said,
                    "things": [
                        {"id": str(t.id), "name": t.name, "type": t.type.value} for t in things
                    ],
                },
            )
        )
    if unknown_services:
        gaps.append(
            IntentGap(
                kind="unknown_service",
                severity="critical",
                said=f"{len(unknown_services)} thing(s) asked for are not in the company model.",
                detail={"ids": [str(i) for i in unknown_services]},
            )
        )
    if environment and known_environments and environment[0] not in known_environments:
        gaps.append(
            IntentGap(
                kind="unknown_environment",
                severity="warning",
                said=f"« {environment[0]} » is no environment the company model knows: "
                "read everywhere.",
                detail={"environment": environment[0], "known": list(known_environments)},
            )
        )
    if profile.needs and not any(profile.needs & source.capabilities for source in sources):
        gaps.append(
            IntentGap(
                kind="no_source_for",
                severity="critical" if profile.events else "warning",
                said="None of the sources read can read what this intention is about: "
                + ", ".join(sorted(profile.needs))
                + ".",
                detail={"needs": sorted(profile.needs), "sources": [s.name for s in sources]},
            )
        )
    if anchor and not anchored:
        gaps.append(
            IntentGap(
                kind="no_event_anchor",
                severity="warning",
                said=f"No {anchor} was found to read since: read over the kind's window.",
                detail={"anchor": anchor},
            )
        )
    return gaps


def version_gaps(
    plan: IntentPlan,
    *,
    retrieval: Sequence[RetrieverRunRead],
    by_type: Mapping[str, int],
    conflicts: Sequence[ContextConflictRead],
    model_built_at: datetime | None,
    assembled_at: datetime,
) -> list[IntentGap]:
    """What a version of an intention's context lacks: an unbuilt or stale
    model, nothing happened when that is the question, a retriever that
    failed, no business side when one is asked, a subject disputed."""
    gaps: list[IntentGap] = []
    if model_built_at is None:
        gaps.append(
            IntentGap(
                kind="model_not_built",
                severity="critical",
                said="The company model has never been built: there is nothing to read yet.",
            )
        )
    elif assembled_at - model_built_at > STALE:
        hours = round((assembled_at - model_built_at).total_seconds() / 3600)
        gaps.append(
            IntentGap(
                kind="model_stale",
                severity="warning",
                said=f"The company model was built {hours} hours before: what changed since is "
                "not in it.",
                detail={"hours": hours},
            )
        )
    profile = PROFILES[plan.kind]
    timeline = next((run for run in retrieval if run.retriever == "timeline"), None)
    if profile.events and (timeline is None or timeline.status != "ok" or timeline.found == 0):
        gaps.append(
            IntentGap(
                kind="nothing_happened",
                severity="critical" if plan.kind == "change" else "warning",
                said="Nothing that happened was found in the period, around what the intention "
                "is about.",
                detail={
                    "since": plan.period.since.isoformat(),
                    "until": plan.period.until.isoformat(),
                },
            )
        )
    for run in retrieval:
        if run.status in {"failed", "timeout"}:
            gaps.append(
                IntentGap(
                    kind="retriever_failed",
                    severity="warning",
                    said=f"The {run.retriever} retriever {run.status}: what it would have found "
                    "is missing.",
                    detail={"retriever": run.retriever, "status": run.status},
                )
            )
    if "business" in plan.facets and not any(by_type.get(kind) for kind in BUSINESS):
        gaps.append(
            IntentGap(
                kind="no_business",
                severity="warning",
                said="Nothing of the business side — application, capability, process — is "
                "tied to what the intention is about.",
            )
        )
    about = {subject.entity_id for subject in plan.subjects}
    for conflict in conflicts:
        if conflict.subject in about:
            gaps.append(
                IntentGap(
                    kind="disputed_subject",
                    severity="warning",
                    said=conflict.said,
                    detail={"conflict": conflict.id, "about": conflict.about},
                )
            )
    return gaps

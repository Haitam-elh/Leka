"""What LEKA understands of an intention (LEKA-385): from its words, what
the asker wants to achieve, what to do, about what — and what it cannot
tell, flagged for clarification rather than guessed.

    the words ──▶ LEKA-373's reading (leka.context, IntentPlan): its kind,
                  the things it names — and those it names ambiguously —
                  when, where
              ──▶ this: the MODE — a question to answer, or a request to
                  act on; the ACTIONS it asks for — restart, roll back,
                  investigate… — and which would change a customer's
                  systems; the GOAL — explain a cause, find an owner,
                  assess an impact, act…; the AMBIGUITIES — what it would
                  ask to go on
              ──▶ Understanding: the structured intent, each part with
                  the words it came from, the words themselves kept beside

An intention whose understanding has a BLOCKING ambiguity is not analysed:
it is said `needs_clarification`, with the questions, until it is asked
again (lifecycle.py).

Deliberately words, not a model — the model gateway does not exist yet
(LEKA-394) — and pure: tested in a millisecond on the examples LEKA's
users ask (tests/test_intention_understanding.py). Each reading says which
words it came from, so what LEKA understood can be checked.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

from leka.context import IntentPlan, kinds_said
from leka.intentions.schemas import (
    ActionRead,
    AmbiguityChoice,
    AmbiguityRead,
    GoalRead,
    Understanding,
    UnderstoodEntity,
)
from leka.intentions.scope import scope_of
from leka.knowledge import fold

# Raised each time intentions are understood differently: kept with each.
# 2: its scope and constraints, and what critical information is missing
#    (LEKA-386).
# 3: an action negated, conditional or doubtful is withheld, not asked; each
#    action on the things said with it (LEKA-434).
# 4: what a question could mean, by id, to be chosen (LEKA-439).
# 5: what is planned, explained or already done is not asked; updating
#    documentation is documenting; a question about something known, with
#    no goal said, asks what is known of it (LEKA-440).
UNDERSTANDING_VERSION = 5

# ── actions ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Verb:
    code: str
    changes_systems: bool
    said: frozenset[str]


def _words(said: str) -> frozenset[str]:
    return frozenset(said.split())


def _verb(code: str, changes: bool, said: str) -> Verb:
    return Verb(code=code, changes_systems=changes, said=_words(said))


# Verbs, folded, French and English — never the nouns: « le déploiement »
# is what happened, « déploie » what is asked.
VERBS: tuple[Verb, ...] = (
    _verb(
        "restart", True, "redemarrer redemarre redemarrez relancer relance relancez restart reboot"
    ),
    _verb("rollback", True, "rollback rollbacker revert reverter"),
    _verb("deploy", True, "deployer deploie deployez redeployer redeploie redeploy"),
    _verb("scale", True, "scaler augmenter augmente augmentez scale upscale downscale"),
    _verb("stop", True, "arreter arrete arretez stopper desactiver desactive desactivez disable"),
    _verb(
        "fix", True, "corriger corrige corrigez reparer repare reparez fix resoudre resous resolve"
    ),
    _verb("update", True, "upgrade upgrader"),
    _verb("migrate", True, "migrer migre migrez migrate"),
    _verb(
        "investigate",
        False,
        "analyser analysez investiguer investigue investigate analyze analyse diagnostiquer",
    ),
    _verb("compare", False, "comparer compare comparez"),
    _verb(
        "assess", False, "evaluer evalue evaluez verifier verifie verifiez check auditer estimer"
    ),
    _verb("list", False, "lister listez list inventorier"),
    _verb("document", False, "documenter documente documentez rediger redige redigez"),
    _verb("notify", False, "prevenir previens prevenez notifier notifie notifiez notify informer"),
)
# Done, though they change no system: a request to do them is to act.
DOING = frozenset({"document", "notify", "ticket"})
# Said in more than a word.
UPDATE = re.compile(r"\b(?:mettre|mets|mettez|met) (?:a|à) jour\b|\bupdate\b")
# What updating them changes is a document, not a system (LEKA-440).
DOCUMENTS = _words(
    "documentation documentations doc docs runbook runbooks page pages wiki procedure "
    "procedures readme fiche fiches notice confluence"
)
ROLL_BACK = re.compile(r"\broll(?:ed)? back\b")
TICKET = re.compile(
    r"\b(?:creer|cree|creez|ouvrir|ouvre|ouvrez|create|open)\b(?: \w+){0,2} (?:ticket|issue)\b"
)

# ── polarity (LEKA-434) ─────────────────────────────────────────────────
# Whether an action is asked: « Ne redémarre pas Billing API » asks for
# nothing to be restarted; « si Billing API tombe, redémarre-la » only if;
# « je ne sais pas s'il faut redémarrer » says no one knows. What is quoted
# — an error message, a log line — is cited, not asked.

QUOTED = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")
SENTENCES = re.compile(r"[.!?;:\n]+")
# Where a clause ends, besides a comma: what one says the other does not.
LINKS = _words("et and puis then mais but ensuite")
# Folded: « n'arrête » is « n arrete », « don't » is « don t ».
NOT_BEFORE = _words("not never no without sans jamais ni nor")
NOT_AFTER = _words("pas plus jamais rien aucun aucune point")
NE = _words("ne n")
CONTRACTED = _words("don doesn didn won shouldn mustn can couldn")
NEGATIONS = NOT_BEFORE | NOT_AFTER | NE
CONDITIONS = _words("si if unless lorsque lorsqu")
AFFIRMED, NEGATED, CONDITIONAL, DOUBTFUL = "affirmed", "negated", "conditional", "ambiguous"
# Already done — « a été redémarrée », « has been restarted »: what happened,
# asked about, never asked for (LEKA-440). Not an action, nor withheld.
DONE = "done"
AUXILIARIES = _words("ai as avons avez ont ete etait etaient sera had has have was were been")
# A participle is never an order; the imperative « redémarre » and the
# participle « redémarré » fold the same, so those need their auxiliary.
PARTICIPLES: dict[str, str] = {
    **dict.fromkeys(
        _words("redemarree redemarrees redemarres relancee relancees restarted rebooted"),
        "restart",
    ),
    **dict.fromkeys(_words("reverted rolled"), "rollback"),
    **dict.fromkeys(
        _words("deployee deployees deployes redeployee redeployees deployed redeployed"), "deploy"
    ),
    **dict.fromkeys(_words("arretee arretees arretes stoppee stoppees stopped"), "stop"),
    **dict.fromkeys(_words("corrigee corrigees corriges reparee reparees fixed repaired"), "fix"),
    **dict.fromkeys(_words("migree migrees migres migrated"), "migrate"),
    **dict.fromkeys(_words("scaled"), "scale"),
    **dict.fromkeys(_words("upgraded"), "update"),
}
# What a plan, a study or a cost is about — « un plan pour migrer », « the
# risk of restarting » — or a way to do it — « comment redémarrer », « how to
# restart »: planned or explained, not asked (LEKA-440).
PLANS = _words(
    """plan plans planning simuler simule simulez simulate simulation scenario scenarios
    strategie strategy roadmap etude etudier study evaluer evalue evaluez estimer estime
    estimez assess estimate risque risques risk cout couts cost faisabilite feasibility"""
)

# ── mode ────────────────────────────────────────────────────────────────

QUESTION_WORDS = _words(
    """pourquoi qui quoi quel quelle quels quelles comment combien quand ou est-ce
    why who what which how where when whose"""
)
# Asked politely, or wanted: a request, even with a question mark.
REQUEST_WORDS = re.compile(
    r"\b(?:peux tu|pourrais tu|pouvez vous|pourriez vous|je veux|je voudrais|il faut|"
    r"merci de|can you|could you|please|i want|i need)\b"
)

# ── goals ───────────────────────────────────────────────────────────────

GOAL_OF_KIND = {
    "diagnose": "explain_cause",
    "change": "find_change",
    "ownership": "find_owner",
    "dependency": "map_dependencies",
    "compliance": "check_compliance",
    "migration": "plan_migration",
    "knowledge": "find_knowledge",
}
IMPACT_WORDS = _words(
    "impact impacts impacte impacter affecte affectes touche touches casse cassera"
)
# Words that say nothing alone: what a request is not made of.
FILLER = _words(
    """le la les un une des de du a au aux et ou en sur pour par avec dans est sont
    the a an of to in on for and or is are it this that ca cela ceci"""
)
# What looks like a system's name — « billing-gateway », « svc_orders » —
# though nothing LEKA knows answers to it: said unknown, never answered as
# if it were something else (LEKA-440).
IDENTIFIER = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+(?![\w-])", re.IGNORECASE)
COMMON = _words(
    """front-end back-end end-to-end real-time read-only on-call follow-up up-to-date e-mail
    week-end pre-prod non-prod sign-in log-in check-in built-in opt-in set-up"""
)
# « dis-moi », « peux-tu », « est-ce »: a verb and its pronoun, not a name.
PRONOUNS = _words("la le les moi toi lui nous vous en y ce il elle on t tu je ils elles")
# How sure a goal is, by how much said it.
SURE, LIKELY, GUESS = 0.8, 0.6, 0.4
MIN_WORDS = 2


@dataclass(frozen=True)
class Found:
    """An action found: its verb, the word that said it, whether it is asked
    — and where it was said (positions in the words read, `_clauses`)."""

    verb: Verb
    said: str
    polarity: str = AFFIRMED
    at: tuple[int, ...] = ()


def _clauses(text: str) -> list[tuple[int, list[str]]]:
    """The words, folded, by clause — with their sentence — quotes left out."""
    out: list[tuple[int, list[str]]] = []
    for number, sentence in enumerate(SENTENCES.split(QUOTED.sub(" ", text))):
        for part in sentence.split(","):
            clause: list[str] = []
            for word in fold(part).split():
                if word in LINKS:
                    if clause:
                        out.append((number, clause))
                    clause = []
                else:
                    clause.append(word)
            if clause:
                out.append((number, clause))
    return out


def _polarity(clause: Sequence[str], at: int, earlier: Sequence[str]) -> str:
    """Whether the verb at `at` of its clause is asked; `earlier`: its
    sentence's words before it."""
    left, right = clause[max(0, at - 3) : at], clause[at + 1 : at + 4]
    contracted = any(w == "t" and i > 0 and left[i - 1] in CONTRACTED for i, w in enumerate(left))
    if (
        set(left) & NOT_BEFORE
        or contracted
        or "pas" in left[-2:]
        or right[:1] == ["pas"]
        or (set(left) & NE and (set(left) | set(right)) & NOT_AFTER)
    ):
        return NEGATED
    if set(clause[:at]) & NEGATIONS:
        return DOUBTFUL
    if set(earlier) & CONDITIONS or any(
        a == "s" and b in ("il", "ils") for a, b in pairwise(earlier)
    ):
        return CONDITIONAL
    return AFFIRMED


def _planned(word: str, left: Sequence[str], earlier: Sequence[str]) -> bool:
    """Whether the verb `word` names what is planned, studied or explained:
    an infinitive a plan word governs, or a way to do something asked."""
    if left[-1:] == ["comment"] or left[-2:] == ["how", "to"]:
        return True
    infinitive = word.endswith(("er", "ir")) or left[-1:] == ["to"]
    return infinitive and bool(set(earlier[-6:]) & PLANS)


def _done(word: str, left: Sequence[str]) -> bool:
    """Whether `word` says what was done: a participle, or a verb after its
    auxiliary — « a redémarré », never « à redémarrer », « j'ai besoin de
    redémarrer », « I have to restart »."""
    if left[-1:] == ["to"] or word.endswith(("er", "ir")):
        return False
    if word in PARTICIPLES or set(left[-3:]) & AUXILIARIES:
        return True
    # « a » before a French participle; never the English article: « do a
    # rollback ».
    return left[-1:] == ["a"] and word.endswith("e")


def actions_of(text: str) -> list[Found]:
    """The actions its words speak of, in the order said, each once — asked
    (affirmed) if any of its mentions is, else as the first said it. What is
    planned or explained is not one; what was done is said done."""
    seen: dict[str, list[Found]] = {}
    position = 0
    sentence_words: dict[int, list[str]] = {}
    for number, clause in _clauses(text):
        earlier = sentence_words.setdefault(number, [])
        joined = " ".join(clause)
        hits = [
            (index, verb, word)
            for index, word in enumerate(clause)
            for verb in VERBS
            if word in verb.said
        ]
        hits += [
            (index, next(v for v in VERBS if v.code == PARTICIPLES[word]), word)
            for index, word in enumerate(clause)
            if word in PARTICIPLES
        ]
        for pattern, verb in (
            (UPDATE, _verb("update", True, "")),
            (ROLL_BACK, next(v for v in VERBS if v.code == "rollback")),
            (TICKET, _verb("ticket", False, "")),
        ):
            for match in pattern.finditer(joined):
                said_verb = verb
                if pattern is UPDATE and set(joined[match.end() :].split()[:3]) & DOCUMENTS:
                    # « Mets à jour la documentation »: written, not deployed.
                    said_verb = next(v for v in VERBS if v.code == "document")
                hits.append((joined[: match.start()].count(" "), said_verb, match.group(0)))
        for index, verb, word in sorted(hits, key=lambda h: h[0]):
            before = [*earlier, *clause[:index]]
            left = clause[max(0, index - 3) : index]
            head = word.split()[0]
            if _planned(head, left, before):
                continue
            polarity = DONE if _done(head, left) else _polarity(clause, index, before)
            seen.setdefault(verb.code, []).append(Found(verb, word, polarity, (position + index,)))
        earlier.extend(clause)
        position += len(clause)
    found = []
    for mentions in seen.values():
        asked = [m for m in mentions if m.polarity == AFFIRMED] or [
            m for m in mentions if m.polarity == mentions[0].polarity
        ]
        first = asked[0]
        found.append(Found(first.verb, first.said, first.polarity, tuple(m.at[0] for m in asked)))
    return sorted(found, key=lambda f: f.at[0])


def targets_of(
    text: str, found: Sequence[Found], entities: Sequence[UnderstoodEntity]
) -> dict[str, list[uuid.UUID]]:
    """What each action is on: the things said after it, before the next
    one — « Redémarre Billing API et rollback Payment API » restarts
    Billing API and rolls back Payment API, never both on both. An action
    said with nothing after it takes what the next one is on (« redémarre
    et scale Billing API »); a thing not found in the words (named by its
    business), every action."""
    words = [w for _, clause in _clauses(text) for w in clause]
    mentions = sorted((at, f.verb.code) for f in found for at in f.at)
    on: dict[int, list[uuid.UUID]] = {at: [] for at, _ in mentions}
    everywhere: list[uuid.UUID] = []
    for entity in entities:
        said = fold(entity.said or "").split()
        where = next(
            (i for i in range(len(words)) if said and words[i : i + len(said)] == said), None
        )
        if where is None or not mentions:
            everywhere.append(entity.entity_id)
            continue
        owner = max((at for at, _ in mentions if at < where), default=mentions[0][0])
        on[owner].append(entity.entity_id)
    for index in range(len(mentions) - 2, -1, -1):
        at, following = mentions[index][0], mentions[index + 1][0]
        if not on[at]:
            on[at] = list(on[following])
    targets: dict[str, list[uuid.UUID]] = {}
    for at, code in mentions:
        targets.setdefault(code, []).extend(on[at])
    return {code: list(dict.fromkeys([*ids, *everywhere])) for code, ids in targets.items()}


def mode_of(text: str, actions: Sequence[Found]) -> tuple[str, str | None]:
    """A question, or a request — and what said it."""
    folded = fold(text)
    asked = REQUEST_WORDS.search(folded)
    if asked and actions:
        return "request", asked.group(0)
    first = folded.split()[0] if folded.split() else ""
    if first in QUESTION_WORDS:
        return "question", first
    if text.strip().endswith("?"):
        return "question", "?"
    if actions:
        return "request", actions[0].said
    return "question", None


def _goal(
    plan: IntentPlan | None,
    kinds: Sequence[tuple[str, list[str]]],
    mode: str,
    actions: Sequence[Found],
    folded: set[str],
    has_entities: bool,
    *,
    done: Sequence[Found] = (),
    asked: bool = False,
) -> GoalRead:
    acting = [a for a in actions if a.verb.changes_systems or a.verb.code in DOING]
    if mode == "request" and acting:
        return GoalRead(
            code="act",
            said=[a.said for a in acting],
            confidence=0.9 if has_entities else 0.5,
        )
    kind = plan.kind if plan is not None else (kinds[0][0] if kinds else "general")
    said = next((found for k, found in kinds if k == kind), list(plan.kind_said) if plan else [])
    if kind in GOAL_OF_KIND:
        code = GOAL_OF_KIND[kind]
        impact = sorted(folded & IMPACT_WORDS)
        if kind == "dependency" and impact:
            code, said = "assess_impact", impact
        return GoalRead(code=code, said=said, confidence=SURE if len(said) > 1 else LIKELY)
    if done:
        # « A-t-elle été redémarrée ? »: what changed is what it asks.
        return GoalRead(code="find_change", said=[a.said for a in done], confidence=LIKELY)
    looking = [a for a in actions if not a.verb.changes_systems and a.verb.code not in DOING]
    if looking:
        return GoalRead(code="investigate", said=[a.said for a in looking], confidence=GUESS)
    if mode == "question" and asked and has_entities:
        # « Quel est le SLA de payment-api ? », « Sur quoi travaille Thomas
        # Berger ? »: what LEKA knows of what it names — never stopped for it.
        return GoalRead(code="find_knowledge", said=[], confidence=GUESS)
    return GoalRead(code="unknown", said=[], confidence=0.0)


def unknown_names(text: str, entities: Sequence[UnderstoodEntity] = ()) -> list[str]:
    """The names its words give that nothing it is about answers to."""
    known = {fold(e.said or e.name) for e in entities} | {fold(e.name) for e in entities}
    found: list[str] = []
    for match in IDENTIFIER.finditer(QUOTED.sub(" ", text)):
        token = match.group(0)
        parts = re.split(r"[-_]", token.casefold())
        if (
            token.casefold() in COMMON
            or parts[-1] in PRONOUNS
            or parts[0] in ("est", "peut", "c", "qu")
            or any(part.isdigit() for part in parts)
            or fold(token) in known
        ):
            continue
        found.append(token)
    return list(dict.fromkeys(found))


def _entities(plan: IntentPlan | None) -> list[UnderstoodEntity]:
    if plan is None:
        return []
    return [
        UnderstoodEntity(
            entity_id=s.entity_id,
            name=s.name,
            type=s.type,
            how=s.how,
            said=s.said,
            confidence=s.confidence,
        )
        for s in plan.subjects
    ]


def _choices(things: object) -> list[AmbiguityChoice]:
    """Things a gap names by id — the context planner's — as choices."""
    if not isinstance(things, list):
        return []
    return [
        AmbiguityChoice(value=str(t["id"]), label=str(t.get("name", "")), type=t.get("type"))
        for t in things
        if isinstance(t, dict) and t.get("id")
    ]


def _ambiguities(
    text: str,
    plan: IntentPlan | None,
    kinds: Sequence[tuple[str, list[str]]],
    goal: GoalRead,
    actions: Sequence[Found],
    entities: Sequence[UnderstoodEntity],
) -> list[AmbiguityRead]:
    found: list[AmbiguityRead] = []
    if len([w for w in fold(text).split() if w not in FILLER and len(w) > 1]) < MIN_WORDS:
        found.append(
            AmbiguityRead(
                kind="too_short",
                blocking=True,
                said="Too few words to tell what is wanted.",
            )
        )
    if goal.code == "unknown":
        found.append(
            AmbiguityRead(
                kind="unclear_goal",
                blocking=True,
                said="What is wanted cannot be told: explain, find, assess, act?",
                options=sorted(set(GOAL_OF_KIND.values())),
            )
        )
    if goal.code != "act" and len(kinds) > 1 and len(kinds[0][1]) == len(kinds[1][1]):
        options = [GOAL_OF_KIND.get(kind, kind) for kind, _ in kinds[:2]]
        found.append(
            AmbiguityRead(
                kind="competing_goals",
                blocking=False,
                said=f"It says {options[0]} as much as {options[1]}: read as the first.",
                options=options,
            )
        )
    for gap in plan.gaps if plan is not None else []:
        detail = gap.detail
        if gap.kind == "no_subject":
            maybe = detail.get("maybe")
            found.append(
                AmbiguityRead(
                    kind="no_subject",
                    # A question about everything — « what changed in
                    # production », « which services have no owner » — is
                    # answered by looking (LEKA's analyst); only an action
                    # needs to know what it acts on.
                    blocking=goal.code == "act",
                    said="It names nothing LEKA knows: which service, application or data?",
                    options=[str(m) for m in maybe] if isinstance(maybe, list) else [],
                    choices=_choices(detail.get("maybe_things")),
                )
            )
        elif gap.kind == "unknown_service":
            found.append(
                AmbiguityRead(
                    kind="unknown_subject",
                    # Asked about: the answer says LEKA does not know it.
                    blocking=goal.code == "act",
                    said="Something asked for is not in the company model.",
                )
            )
        elif gap.kind == "ambiguous_subject":
            things = detail.get("things")
            names = (
                [str(t.get("name")) for t in things if isinstance(t, dict)]
                if isinstance(things, list)
                else []
            )
            found.append(
                AmbiguityRead(
                    kind="ambiguous_subject",
                    # Acting on the wrong one is not a reading to correct later.
                    blocking=goal.code == "act",
                    said=f"« {detail.get('said', '')} » names several things.",
                    options=names,
                    choices=_choices(things),
                )
            )
        elif gap.kind == "unknown_environment":
            known = detail.get("known")
            found.append(
                AmbiguityRead(
                    kind="unknown_environment",
                    blocking=False,
                    said=f"« {detail.get('environment', '')} » is no environment LEKA knows.",
                    options=[str(e) for e in known] if isinstance(known, list) else [],
                )
            )
    strangers = [] if entities else unknown_names(text)
    if strangers and not any(g.kind == "unknown_subject" for g in found):
        # « Pourquoi billing-gateway est en panne ? »: LEKA says it does not
        # know it — never answers about something else (LEKA-440).
        guessed = next((g for g in found if g.kind == "no_subject"), None)
        if guessed is not None:
            found.remove(guessed)
        found.append(
            AmbiguityRead(
                kind="unknown_subject",
                blocking=goal.code == "act",
                said=f"LEKA knows nothing called {', '.join(strangers)}.",
                options=list(guessed.options) if guessed is not None else [],
                choices=list(guessed.choices) if guessed is not None else [],
            )
        )
    if any(a.verb.changes_systems for a in actions) and not entities:
        # One question about what it acts on, not two: what the words could
        # name comes with it (LEKA-439).
        guessed = next((g for g in found if g.kind in ("no_subject", "unknown_subject")), None)
        if guessed is not None:
            found.remove(guessed)
        found.append(
            AmbiguityRead(
                kind="action_without_target",
                blocking=True,
                said="An action is asked, on nothing LEKA knows: on what?",
                options=[a.verb.code for a in actions if a.verb.changes_systems],
                choices=list(guessed.choices) if guessed is not None else [],
            )
        )
    if text.count("?") > 1 or (
        len({a.verb.code for a in actions}) > 1
        and re.search(r"\b(?:et|and|puis|then)\b", fold(text))
    ):
        found.append(
            AmbiguityRead(
                kind="several_requests",
                blocking=False,
                said="It asks several things: each is read, the first leads.",
            )
        )
    return found


def understand(
    text: str,
    plan: IntentPlan | None,
    *,
    lifecycles: Mapping[uuid.UUID, str] | None = None,
    environments: Sequence[str] = (),
    now: datetime | None = None,
) -> Understanding:
    """What LEKA understands of these words, read with LEKA-373's plan —
    and, given what the company model says of each thing and the
    environments it knows, their scope (LEKA-386)."""
    every = actions_of(text)
    # Only what is asked is acted on; the rest is kept, said why (LEKA-434),
    # but what was done is what it asks about (LEKA-440).
    found = [a for a in every if a.polarity == AFFIRMED]
    done = [a for a in every if a.polarity == DONE]
    spoken = [a for a in every if a.polarity != DONE]
    folded = set(fold(text).split())
    # A migration asked with what to assess, study or plan around it is a
    # project to plan — no system changed now (2026-10-14: « Je dois migrer
    # les serveurs AWS vers Azure, évaluer les dépendances » stopped on
    # « à préciser » when no model read it).
    migrating = [a for a in found if a.verb.code == "migrate"]
    project = bool(migrating) and (
        any(not a.verb.changes_systems for a in found) or bool(folded & PLANS)
    )
    if project:
        found = [a for a in found if a.verb.code != "migrate"]
    mode, mode_said = mode_of(text, found)
    kinds = kinds_said(text)
    named = _entities(plan)
    goal = (
        GoalRead(code="plan_migration", said=[a.said for a in migrating], confidence=LIKELY)
        if project
        else _goal(
            plan,
            kinds,
            mode,
            found,
            folded,
            bool(named),
            done=done,
            asked=mode_said is not None,
        )
    )
    actions = [
        ActionRead(code=a.verb.code, said=a.said, changes_systems=a.verb.changes_systems)
        for a in found
    ]
    scope, missing = scope_of(
        text,
        plan,
        goal=goal,
        actions=actions,
        lifecycles=lifecycles or {},
        environments=environments,
        now=now or datetime.now(UTC),
    )
    # What it excludes is not what it is about.
    kept = {thing.entity_id for thing in scope.entities}
    entities = [entity for entity in named if entity.entity_id in kept]
    on = targets_of(text, spoken, entities)
    actions = [a.model_copy(update={"targets": on.get(a.code, [])}) for a in actions]
    withheld = [
        ActionRead(
            code=a.verb.code,
            said=a.said,
            changes_systems=a.verb.changes_systems,
            polarity=a.polarity,
            targets=on.get(a.verb.code, []),
        )
        for a in spoken
        if a.polarity != AFFIRMED
    ]
    doubtful = [a for a in withheld if a.changes_systems and a.polarity != NEGATED]
    ambiguities = [
        *_ambiguities(text, plan, kinds, goal, found, entities),
        *missing,
        *(
            [
                AmbiguityRead(
                    kind="ambiguous_action",
                    # Changing a customer's systems on a doubt is not a
                    # reading to correct later: asked first, never proposed.
                    blocking=True,
                    said="An action is negated, conditional or doubtful: is it asked?",
                    options=[a.code for a in doubtful],
                )
            ]
            if doubtful
            else []
        ),
    ]
    period = None
    if plan is not None:
        period = plan.period.model_dump(mode="json")
    return Understanding(
        version=UNDERSTANDING_VERSION,
        text=text,
        mode=mode,
        mode_said=mode_said,
        kind=plan.kind if plan is not None else (kinds[0][0] if kinds else "general"),
        goal=goal,
        actions=actions,
        withheld=withheld,
        entities=entities,
        period=period,
        environment=plan.environment if plan is not None else None,
        ambiguities=ambiguities,
        clear=not any(a.blocking for a in ambiguities),
        scope=scope,
    )

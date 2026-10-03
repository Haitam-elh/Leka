"""Entity resolution (LEKA-357): which candidates are one real thing.

Normalisation gives every record's entity, and every person, service and
team a record names, a CANONICAL KEY and ALIASES (docs/normalisation.md).
This decides, across a workspace's sources, which of them are one thing —
and says how sure it is, and why.

    1. DETERMINISTIC, merged at the confidence of the fact:
       the same key, seen by several sources          same_key       1.0
       a key and its alias — an account and the
       addresses it was seen with, a Jira issue and
       its ticket:PAY-42                               alias          1.0
       an address that says its account (noreply),
       a plus address and its mailbox                  github_noreply 0.99
                                                       plus_address   0.95
    2. SEMANTIC, between what step 1 left apart — people, services, teams,
       by what their names mean (signals.py). Two families of signals —
       what a person is CALLED (a full name, a handle read as a name) and
       how they SIGN IN (the same handle in two tools) — each scored; two
       families agreeing are worth more than either. A service's or a
       team's core name.
    3. DECIDED:  ≥ 0.9 merged — one thing;  0.6 to 0.9 linked — probably one
       thing, kept apart for what reads it to weigh;  below, nothing.

WHAT IS NOT MERGED, and why — the false positives this is built against:
- two people each with their own address are never merged by their names
  (two "Alex Kim" are two): linked at most;
- a short ticket key naming tickets in two tools (`ENG-42` in Jira and in
  Linear) is `ambiguous`, and names neither;
- an account seen with more than SHARED_ACCOUNT addresses is a shared one,
  not a person's;
- a bot is never matched by its name; a generic or short handle ("admin",
  "dev") says nothing;
- a match tied between two candidates that are not one another is
  `ambiguous` rather than a guess;
- a name too common in the workspace (more than CROWD holders) says nothing.

CONFLICTS ARE KEPT: where the sources of one thing disagree — a name, a
state — one value is chosen (the most recent, then the surest) and every
value is kept beside it with its source, in `conflicts`.

Pure: mentions in, identities and decisions out; the job reads and writes.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from typing import Literal

from leka.ingestion.resolution import signals as sig

# 2: quarantined records left out, and each entity's quality (LEKA-358).
# 3: applications named alike are one, as services and teams (LEKA-362).
# 4: a service's no-reply address and GitHub's merge account are bots,
#    never matched by their names (LEKA-369).
RESOLVER_VERSION = 4
MERGE = 0.9
LINK = 0.6
# The kinds one by name — "Billing API" and "billing" — and the words that
# say what a name is rather than which one it is.
NAME_WORDS = {
    "service": sig.SERVICE_WORDS,
    "team": sig.TEAM_WORDS,
    "application": sig.APPLICATION_WORDS,
}
SEMANTIC_CAP = 0.95
# Below MERGE: what two people with their own addresses can reach by name.
KEPT_APART = 0.89
SHARED_ACCOUNT = 5
CROWD = 5
# Attributes that say where a candidate came from, not what the thing is:
# never compared, never chosen between.
PROVENANCE = frozenset({"url", "source_kind", "quality"})
PROVENANCE_SUFFIXES = ("_at", "_raw", "_confidence")

Kind = Literal["merge", "link", "ambiguous"]
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class Mention:
    """One key as one source says it — every record of that source that
    names it, taken together."""

    key: str
    type: str
    source_id: uuid.UUID
    name: str
    aliases: set[str] = field(default_factory=set)
    attributes: dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    # As the record itself, and as named by another record.
    records: int = 0
    named: int = 0
    # A normalised_records row that says it.
    example: uuid.UUID | None = None
    # The best quality validation gave the source's records that are it.
    quality: float | None = None


@dataclass(frozen=True)
class Decision:
    kind: Kind
    rule: str
    confidence: float
    keys: tuple[str, ...]
    evidence: str


@dataclass
class KeySeen:
    """Provenance: a key, as one source gave it — its own, an alias it
    asserted, or one derived from it."""

    key: str
    source_id: uuid.UUID
    kind: Literal["key", "alias", "derived"]
    name: str | None = None
    records: int = 0
    named: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    example: uuid.UUID | None = None


@dataclass
class Identity:
    """One real thing, as the workspace's sources show it."""

    type: str
    key: str
    name: str
    names: list[str]
    attributes: dict[str, object]
    conflicts: list[dict[str, object]]
    confidence: float
    keys: list[KeySeen]
    decisions: list[Decision]
    sources: list[uuid.UUID]
    quality: float | None = None


@dataclass
class Resolution:
    identities: list[Identity]
    # (identity, other identity, the link) — probably one thing, kept apart.
    links: list[tuple[int, int, Decision]]


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, left: str, right: str) -> bool:
        a, b = self.find(left), self.find(right)
        if a == b:
            return False
        # The smaller root wins: the same input gives the same roots.
        self.parent[max(a, b)] = min(a, b)
        return True


def resolve(mentions: Iterable[Mention]) -> Resolution:
    by_key: dict[str, list[Mention]] = defaultdict(list)
    for mention in mentions:
        by_key[mention.key].append(mention)

    keys = _Union()
    merges: list[Decision] = []
    ambiguous: list[Decision] = []
    derived_from: dict[str, tuple[str, uuid.UUID]] = {}
    for key, seen in by_key.items():
        keys.add(key)
        sources = {m.source_id for m in seen}
        if len(sources) > 1:
            merges.append(
                Decision("merge", "same_key", 1.0, (key,), f"seen by {len(sources)} sources")
            )
        for other, rule, confidence in sig.derived(key):
            keys.union(key, other)
            derived_from.setdefault(other, (key, seen[0].source_id))
            merges.append(Decision("merge", rule, confidence, (key, other), f"{key} is {other}"))

    tickets: dict[str, set[str]] = defaultdict(set)
    accounts: dict[str, set[str]] = defaultdict(set)
    for key, seen in by_key.items():
        for alias in sorted({alias for m in seen for alias in m.aliases} - {key}):
            if alias.startswith("ticket:"):
                tickets[alias].add(key)
            elif sig.account_of(alias) and sig.email_of(key):
                accounts[alias].add(key)
            elif keys.union(key, alias):
                merges.append(Decision("merge", "alias", 1.0, (key, alias), f"{key} is {alias}"))
    for account, addresses in accounts.items():
        if len(addresses) > SHARED_ACCOUNT:
            for address in sorted(addresses):
                ambiguous.append(
                    Decision(
                        "ambiguous",
                        "shared_account",
                        0.0,
                        (account, address),
                        f"{account} signs in with {len(addresses)} addresses: shared, not "
                        "one person's",
                    )
                )
            continue
        for address in sorted(addresses):
            if keys.union(address, account):
                merges.append(
                    Decision("merge", "alias", 1.0, (address, account), f"{address} is {account}")
                )
    for ticket, primaries in tickets.items():
        owners = {keys.find(primary) for primary in primaries}
        if len(owners) == 1:
            primary = min(primaries)
            if keys.union(primary, ticket):
                merges.append(
                    Decision("merge", "alias", 1.0, (primary, ticket), f"{primary} is {ticket}")
                )
            continue
        for primary in sorted(primaries):
            others = ", ".join(sorted(primaries - {primary}))
            ambiguous.append(
                Decision(
                    "ambiguous",
                    "ambiguous_alias",
                    0.0,
                    (ticket, primary),
                    f"{ticket} names {primary} and {others}: neither is assumed",
                )
            )

    clusters: dict[str, list[str]] = defaultdict(list)
    for key in by_key:
        clusters[keys.find(key)].append(key)
    for node in list(keys.parent):
        root = keys.find(node)
        if root in clusters and node not in by_key:
            clusters[root].append(node)
    groups = [_Group(members, by_key) for members in clusters.values()]

    semantic = _Semantic(groups)
    identities: list[Identity] = []
    index_of: dict[int, int] = {}
    for final in semantic.merged():
        members = [groups[g] for g in final]
        for g in final:
            index_of[g] = len(identities)
        inside = semantic.decisions_within(final)
        identities.append(_identity(members, by_key, merges, ambiguous, inside, derived_from))

    links: dict[tuple[int, int], Decision] = {}
    for a, b, decision in semantic.links():
        i, j = sorted((index_of[a], index_of[b]))
        if i != j and (links.get((i, j)) is None or links[(i, j)].confidence < decision.confidence):
            links[(i, j)] = decision
    return Resolution(identities, [(i, j, d) for (i, j), d in sorted(links.items())])


# ── the groups step 1 made ───────────────────────────────────────────────────


class _Group:
    """Keys joined by what they themselves say: one thing, surely."""

    def __init__(self, members: list[str], by_key: dict[str, list[Mention]]) -> None:
        self.keys = sorted(members)
        self.mentions = [m for key in self.keys for m in by_key.get(key, [])]
        self.type = Counter(m.type for m in self.mentions).most_common(1)[0][0]
        self.emails = {e for key in self.keys if (e := sig.email_of(key))}
        self.bot = any(sig.is_bot(m.key, m.name) for m in self.mentions)
        self.handles = {h for key in self.keys for h in sig.handles(key)}
        self.parts = {tuple(sorted(p)) for key in self.keys for p in sig.handle_parts(key)}
        # A full name, order-free, and how it was written.
        self.full_names = {
            n: m.name for m in reversed(self.mentions) if (n := sig.full_name(m.name))
        }
        self.cores = {
            sig.core(key, NAME_WORDS.get(self.type, sig.SERVICE_WORDS))
            for key in self.keys
            if key.startswith(self.type + ":")
        }


# ── step 2: what names mean ──────────────────────────────────────────────────


@dataclass
class _Evidence:
    name: tuple[float, str, str] | None = None
    handle: tuple[float, str, str] | None = None
    service: tuple[float, str, str] | None = None

    def offer(self, family: str, score: float, rule: str, why: str) -> None:
        current = getattr(self, family)
        if current is None or current[0] < score:
            setattr(self, family, (score, rule, why))

    def decision(self, apart: bool) -> Decision:
        found = [e for e in (self.name, self.handle, self.service) if e is not None]
        score = 1.0
        for weight, _, _ in found:
            score *= 1 - weight
        score = min(1 - score, SEMANTIC_CAP) if len(found) > 1 else found[0][0]
        rule = "+".join(rule for _, rule, _ in found)
        why = "; ".join(why for _, _, why in found)
        if apart and score >= MERGE:
            score, why = KEPT_APART, why + "; each has an address of its own: kept apart"
        kind: Kind = "merge" if score >= MERGE else "link"
        return Decision(kind, rule, round(score, 2), (), why)


class _Semantic:
    def __init__(self, groups: list[_Group]) -> None:
        self.groups = groups
        self.pairs: dict[tuple[int, int], _Evidence] = defaultdict(_Evidence)
        people = [i for i, g in enumerate(groups) if g.type == "person" and not g.bot]
        self._people(people)
        for kind in NAME_WORDS:
            self._named(kind, [i for i, g in enumerate(groups) if g.type == kind])
        self.decided = {
            pair: evidence.decision(self._apart(*pair)) for pair, evidence in self.pairs.items()
        }
        self.decided = {p: d for p, d in self.decided.items() if d.confidence >= LINK}
        self._ambiguity()

    def _offer(self, a: int, b: int, family: str, score: float, rule: str, why: str) -> None:
        if a != b:
            self.pairs[(min(a, b), max(a, b))].offer(family, score, rule, why)

    def _people(self, people: list[int]) -> None:
        by_name: dict[tuple[str, ...], list[int]] = defaultdict(list)
        written: dict[tuple[str, ...], str] = {}
        by_handle: dict[str, list[int]] = defaultdict(list)
        by_parts: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i in people:
            group = self.groups[i]
            for name, as_written in group.full_names.items():
                by_name[name].append(i)
                written.setdefault(name, as_written)
            for handle in group.handles:
                by_handle[handle].append(i)
            for parts in group.parts:
                by_parts[parts].append(i)
        for name, holders in by_name.items():
            if len(holders) > CROWD:
                continue
            said = written[name]
            for a, b in combinations(holders, 2):
                self._offer(a, b, "name", 0.8, "same_full_name", f"both are named {said!r}")
            for b in by_parts.get(name, []):
                for a in holders:
                    self._offer(
                        a, b, "name", 0.85, "handle_reads_as_name", f"a handle reads {said!r}"
                    )
            for a in holders:
                for handle, weight in sig.name_handles(name).items():
                    signing = by_handle.get(handle, [])
                    if len(signing) > CROWD:
                        continue
                    for b in signing:
                        self._offer(
                            a,
                            b,
                            "name",
                            weight,
                            "handle_matches_name",
                            f"{handle!r} is how {said!r} is written",
                        )
        for handle, holders in by_handle.items():
            if len(holders) > CROWD:
                continue
            for a, b in combinations(holders, 2):
                self._offer(a, b, "handle", 0.75, "same_handle", f"both sign in as {handle!r}")

    def _named(self, kind: str, members: list[int]) -> None:
        by_core: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
        for i in members:
            for core, environment in self.groups[i].cores:
                by_core[core].append((i, environment))
        for core, holders in by_core.items():
            for (a, env_a), (b, env_b) in combinations(holders, 2):
                if env_a == env_b:
                    self._offer(a, b, "service", 0.9, "same_name", f"both are {kind} {core!r}")
                else:
                    self._offer(
                        a,
                        b,
                        "service",
                        0.7,
                        "environment_variant",
                        f"{kind} {core!r} in {env_a or 'no environment'} and "
                        f"{env_b or 'no environment'}",
                    )
        cores = sorted(by_core)
        for left, right in combinations(cores, 2):
            if left[:2] == right[:2] and sig.spelled_alike(left, right):
                for a, _ in by_core[left]:
                    for b, _ in by_core[right]:
                        self._offer(
                            a,
                            b,
                            "service",
                            0.65,
                            "similar_spelling",
                            f"{left!r} and {right!r} are spelled alike",
                        )

    def _apart(self, a: int, b: int) -> bool:
        """Two people each with an address of their own: never one by name."""
        return bool(self.groups[a].emails and self.groups[b].emails)

    def _ambiguity(self) -> None:
        """A group merged with two that are not one another: none of the
        three merges holds — a guess is not a decision."""
        partners: dict[int, set[int]] = defaultdict(set)
        for (a, b), decision in self.decided.items():
            if decision.kind == "merge":
                partners[a].add(b)
                partners[b].add(a)
        self.torn: dict[int, list[int]] = {}
        for group, others in partners.items():
            for x, y in combinations(sorted(others), 2):
                pair = (min(x, y), max(x, y))
                if self.decided.get(pair) is None or self.decided[pair].kind != "merge":
                    self.torn[group] = sorted(others)
                    break
        for group in self.torn:
            for other in partners[group]:
                pair = (min(group, other), max(group, other))
                d = self.decided[pair]
                self.decided[pair] = Decision(
                    "link",
                    d.rule,
                    KEPT_APART,
                    (),
                    d.evidence + "; it matches others too: kept apart",
                )

    def merged(self) -> list[list[int]]:
        union = _Union()
        for i in range(len(self.groups)):
            union.add(str(i))
        for (a, b), decision in self.decided.items():
            if decision.kind == "merge":
                union.union(str(a), str(b))
        finals: dict[str, list[int]] = defaultdict(list)
        for i in range(len(self.groups)):
            finals[union.find(str(i))].append(i)
        return list(finals.values())

    def decisions_within(self, final: list[int]) -> list[Decision]:
        inside = set(final)
        found = []
        for (a, b), decision in sorted(self.decided.items()):
            if decision.kind == "merge" and a in inside and b in inside:
                pair = (self.groups[a].keys[0], self.groups[b].keys[0])
                found.append(
                    Decision("merge", decision.rule, decision.confidence, pair, decision.evidence)
                )
        for group in final:
            if group in self.torn:
                keys = tuple(self.groups[g].keys[0] for g in [group, *self.torn[group]])
                found.append(
                    Decision(
                        "ambiguous",
                        "tied_match",
                        0.0,
                        keys,
                        f"{keys[0]} matches {len(keys) - 1} others that are not one another",
                    )
                )
        return found

    def links(self) -> list[tuple[int, int, Decision]]:
        return [
            (
                a,
                b,
                Decision(
                    "link",
                    d.rule,
                    d.confidence,
                    (self.groups[a].keys[0], self.groups[b].keys[0]),
                    d.evidence,
                ),
            )
            for (a, b), d in sorted(self.decided.items())
            if d.kind == "link"
        ]


# ── step 3: one identity ─────────────────────────────────────────────────────


def _identity(
    groups: list[_Group],
    by_key: dict[str, list[Mention]],
    merges: list[Decision],
    ambiguous: list[Decision],
    semantic: list[Decision],
    derived_from: dict[str, tuple[str, uuid.UUID]],
) -> Identity:
    own = {key for group in groups for key in group.keys}
    mentions = [m for group in groups for m in group.mentions]
    kind = Counter(m.type for m in mentions).most_common(1)[0][0]
    decisions = [d for d in merges if d.keys and d.keys[0] in own]
    decisions += [d for d in ambiguous if d.keys[1] in own]
    decisions += semantic
    confidence = min(
        [d.confidence for d in decisions if d.kind == "merge"]
        + [max(m.confidence for m in mentions)]
    )
    names, name_conflict = _names(kind, mentions, own)
    attributes, conflicts = _attributes(mentions)
    if name_conflict:
        conflicts.insert(0, name_conflict)
    return Identity(
        type=kind,
        key=_chosen_key(kind, own, by_key),
        name=names[0],
        names=names,
        attributes=attributes,
        conflicts=conflicts,
        confidence=round(confidence, 2),
        keys=_provenance(own, mentions, by_key, derived_from),
        decisions=decisions,
        sources=sorted({m.source_id for m in mentions}, key=str),
        quality=max((m.quality for m in mentions if m.quality is not None), default=None),
    )


def _chosen_key(kind: str, own: set[str], by_key: dict[str, list[Mention]]) -> str:
    """The key that says it best: a person's working address, a ticket on
    its site — the key sources give the thing itself, then the most said."""

    def rank(key: str) -> tuple[object, ...]:
        seen = by_key.get(key, [])
        email = sig.email_of(key)
        return (
            not seen,
            kind == "person" and not (email and not sig.NOREPLY.search(email)),
            key.startswith("ticket:"),
            -sum(m.records for m in seen),
            -sum(m.records + m.named for m in seen),
            len(key),
            key,
        )

    return min(own, key=rank)


def _names(
    kind: str, mentions: list[Mention], own: set[str]
) -> tuple[list[str], dict[str, object] | None]:
    """Its name — a real one before a handle, what the thing's own records
    say before what others call it, the surest, the latest — every other it
    goes by, and a conflict when two of them are not the same name."""
    squeezed_keys = {sig.fold(k.rsplit(":", 1)[-1]).replace(" ", "") for k in own}

    def real(name: str) -> bool:
        return "@" not in name and sig.fold(name).replace(" ", "") not in squeezed_keys

    ranked = sorted(
        mentions,
        key=lambda m: (
            not real(m.name),
            m.records == 0,
            -m.confidence,
            -(m.last_seen or EPOCH).timestamp(),
            m.name,
        ),
    )
    names: list[str] = []
    for mention in ranked:
        if sig.fold(mention.name) not in {sig.fold(n) for n in names}:
            names.append(mention.name)
    reals = [m for m in ranked if real(m.name)]
    if kind == "person":
        different = _people_differ(reals)
    elif kind in NAME_WORDS:
        different = len({sig.core(m.name, NAME_WORDS[kind])[0] for m in reals}) > 1
    else:
        described = [m for m in reals if m.records]
        different = len({sig.fold(m.name) for m in described}) > 1
        reals = described
    if not different:
        return names, None
    return names, {
        "attribute": "name",
        "chosen": names[0],
        "values": [_said(m.name, m) for m in reals],
    }


def _people_differ(mentions: list[Mention]) -> bool:
    """Two full names neither of which holds the other: 'Sara Martin' and
    'Sara Martin-Dupont' are one person named twice; 'Sara Martin' and
    'Sarah Johnson' under one address are a conflict."""
    full = {n for m in mentions if (n := sig.full_name(m.name))}
    return any(
        not set(a) <= set(b) and not set(b) <= set(a) for a, b in combinations(sorted(full), 2)
    )


def _attributes(
    mentions: list[Mention],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """What the thing is, from what its own records say (else from what
    others say of it): where the sources agree, their value; where they do
    not, the most recent, then the surest — and every value, kept."""
    speaking = [m for m in mentions if m.records] or mentions
    values: dict[str, list[tuple[object, Mention]]] = defaultdict(list)
    for mention in speaking:
        for name, value in mention.attributes.items():
            if name in PROVENANCE or name.endswith(PROVENANCE_SUFFIXES):
                continue
            values[name].append((value, mention))
    chosen: dict[str, object] = {}
    conflicts: list[dict[str, object]] = []
    for name in sorted(values):
        said = values[name]
        ranked = sorted(
            said,
            key=lambda pair: (-(pair[1].last_seen or EPOCH).timestamp(), -pair[1].confidence),
        )
        chosen[name] = ranked[0][0]
        if len({_canonical(value) for value, _ in said}) > 1:
            conflicts.append(
                {
                    "attribute": name,
                    "chosen": ranked[0][0],
                    "values": [_said(value, mention) for value, mention in ranked],
                }
            )
    return chosen, conflicts


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _said(value: object, mention: Mention) -> dict[str, object]:
    return {
        "value": value,
        "source_id": str(mention.source_id),
        "key": mention.key,
        "observed_at": mention.last_seen.isoformat() if mention.last_seen else None,
    }


def _provenance(
    own: set[str],
    mentions: list[Mention],
    by_key: dict[str, list[Mention]],
    derived_from: dict[str, tuple[str, uuid.UUID]],
) -> list[KeySeen]:
    """Every key the thing goes by, per source that gave it."""
    rows: dict[tuple[str, uuid.UUID], KeySeen] = {}
    for mention in mentions:
        rows[(mention.key, mention.source_id)] = KeySeen(
            key=mention.key,
            source_id=mention.source_id,
            kind="key",
            name=mention.name,
            records=mention.records,
            named=mention.named,
            first_seen=mention.first_seen,
            last_seen=mention.last_seen,
            example=mention.example,
        )
    for mention in mentions:
        for alias in sorted(mention.aliases):
            rows.setdefault(
                (alias, mention.source_id),
                KeySeen(key=alias, source_id=mention.source_id, kind="alias"),
            )
    for key in sorted(own):
        if key in derived_from and key not in by_key:
            _origin, source_id = derived_from[key]
            rows.setdefault((key, source_id), KeySeen(key=key, source_id=source_id, kind="derived"))
    return sorted(rows.values(), key=lambda row: (row.kind != "key", row.key, str(row.source_id)))

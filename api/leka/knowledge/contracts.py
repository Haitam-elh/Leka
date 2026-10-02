"""Relationship contracts (LEKA-368): what each kind of relationship may
join, what makes a set of them contradict itself — and what changed since
the last build. Pure: a build's relationships in; those kept, the issues
found and the changes out.

    wrong_end        an end of a kind its contract does not take — a team
                     that `reports_to` someone: dropped, an error
    cycle_broken     an inferred link closing a loop of a kind that may
                     have none — A part of B, part of A: the weakest
                     inferred one dropped, a warning
    cycle            a loop its sources state, or of a dependency: kept,
                     a warning
    several_targets  a thing with more than one of what it has one of — two
                     managers, two parent pages: kept, a warning

A relationship's history: `added` the first build it is in, `removed` the
first it is not, `changed` when its origin, its rule, its environments
change — or its confidence, by CHANGED at least: an inference that moves
with the clock is no news.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from leka.knowledge.models import RelationshipType
from leka.knowledge.registry import RELATIONSHIP_KINDS

Key = tuple[uuid.UUID, uuid.UUID, str]
Row = dict[str, object]
# How much a confidence must move to be a change.
CHANGED = 0.05


@dataclass(frozen=True)
class Issue:
    """What is wrong with a relationship — or with a set of them."""

    type: str
    issue: str
    severity: str
    from_id: uuid.UUID
    to_id: uuid.UUID
    origin: str
    rule: str
    confidence: float
    detail: dict[str, object]

    def row(self) -> Row:
        return {
            "type": self.type,
            "issue": self.issue,
            "severity": self.severity,
            "from_entity_id": self.from_id,
            "to_entity_id": self.to_id,
            "origin": self.origin,
            "rule": self.rule,
            "confidence": self.confidence,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Previous:
    """A relationship as the last build left it."""

    first_seen_at: datetime | None
    changed_at: datetime | None
    confidence: float
    origin: str
    rule: str
    environments: tuple[str, ...]


def check(edges: dict[Key, Row], types: dict[uuid.UUID, str]) -> tuple[dict[Key, Row], list[Issue]]:
    """The relationships kept and the issues found: ends their contract
    does not take dropped; loops where none may be broken — an inferred link
    dropped — or said; more than one of what a thing has one of, said."""
    issues: list[Issue] = []
    kept: dict[Key, Row] = {}
    for key, row in edges.items():
        kind = RELATIONSHIP_KINDS[RelationshipType(str(row["type"]))]
        ends = (("from", key[0], kind.sources), ("to", key[1], kind.targets))
        wrong = next(
            (
                (end, types.get(thing))
                for end, thing, allowed in ends
                if allowed is not None and types.get(thing) not in {t.value for t in allowed}
            ),
            None,
        )
        if wrong is None:
            kept[key] = row
            continue
        end, found = wrong
        allowed = kind.sources if end == "from" else kind.targets
        issues.append(
            _issue(
                row,
                "wrong_end",
                "error",
                {
                    "end": end,
                    "found": found,
                    "expected": sorted(t.value for t in allowed or ()),
                },
            )
        )
    for kind in RELATIONSHIP_KINDS.values():
        if kind.acyclic:
            issues += _break_cycles(kept, kind.type.value)
        elif kind.dependency:
            issues += _say_cycles(kept, kind.type.value)
        if kind.single:
            issues += _several(kept, kind.type.value)
    return kept, issues


def history(edges: dict[Key, Row], previous: dict[Key, Previous], now: datetime) -> list[Row]:
    """What changed since the last build — each relationship's
    `first_seen_at` and `changed_at` set on the way."""
    changes: list[Row] = []
    for key, row in edges.items():
        after = _state(row)
        before = previous.get(key)
        if before is None:
            row["first_seen_at"] = row["changed_at"] = now
            changes.append(_change(key, "added", None, after, now))
            continue
        row["first_seen_at"] = before.first_seen_at or now
        was = {
            "confidence": before.confidence,
            "origin": before.origin,
            "rule": before.rule,
            "environments": list(before.environments),
        }
        if _differs(was, after):
            row["changed_at"] = now
            changes.append(_change(key, "changed", was, after, now))
        else:
            row["changed_at"] = before.changed_at or now
    for key, before in previous.items():
        if key not in edges:
            was = {
                "confidence": before.confidence,
                "origin": before.origin,
                "rule": before.rule,
                "environments": list(before.environments),
            }
            changes.append(_change(key, "removed", was, None, now))
    return changes


# ── loops ────────────────────────────────────────────────────────────────────


def _break_cycles(kept: dict[Key, Row], kind: str) -> list[Issue]:
    """A kind that may have no loop: while an inferred link closes one, the
    weakest such link is dropped; a loop its sources state is kept, and
    said."""
    issues: list[Issue] = []
    while True:
        loops = _loops(kept, kind)
        broken = False
        for loop in loops:
            inferred = [k for k in loop if kept[k]["origin"] != "stated"]
            if not inferred:
                continue
            weakest = min(inferred, key=lambda k: (float(str(kept[k]["confidence"])), str(k)))
            detail: dict[str, object] = {"members": _members(loop)}
            issues.append(_issue(kept.pop(weakest), "cycle_broken", "warning", detail))
            broken = True
        if not broken:
            break
    issues += [_said(kept, loop) for loop in loops]
    return issues


def _say_cycles(kept: dict[Key, Row], kind: str) -> list[Issue]:
    """A dependency loop — two services each needing the other: kept, said."""
    return [_said(kept, loop) for loop in _loops(kept, kind)]


def _said(kept: dict[Key, Row], loop: list[Key]) -> Issue:
    first = min(loop, key=str)
    return _issue(kept[first], "cycle", "warning", {"members": _members(loop)})


def _members(loop: list[Key]) -> list[str]:
    return sorted({str(end) for key in loop for end in key[:2]})


def _loops(kept: dict[Key, Row], kind: str) -> list[list[Key]]:
    """The loops of one kind: each strongly connected set of things it
    joins — more than one — with the links inside it."""
    edges = [key for key, row in kept.items() if row["type"] == kind]
    following: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for a, b, _ in edges:
        following[a].append(b)
    found: list[list[Key]] = []
    for component in _strongly_connected(following):
        if len(component) < 2:
            continue
        found.append([k for k in edges if k[0] in component and k[1] in component])
    return found


def _strongly_connected(following: dict[uuid.UUID, list[uuid.UUID]]) -> list[set[uuid.UUID]]:
    """Tarjan's strongly connected components — without recursion: a
    hierarchy of thousands of things is not a stack of thousands of calls."""
    index: dict[uuid.UUID, int] = {}
    low: dict[uuid.UUID, int] = {}
    on_stack: set[uuid.UUID] = set()
    stack: list[uuid.UUID] = []
    components: list[set[uuid.UUID]] = []
    counter = 0
    for root in list(following):
        if root in index:
            continue
        work: list[tuple[uuid.UUID, int]] = [(root, 0)]
        while work:
            node, step = work.pop()
            if step == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            nexts = following.get(node, [])
            if step < len(nexts):
                work.append((node, step + 1))
                target = nexts[step]
                if target not in index:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index[target])
                continue
            for target in nexts:
                if target in on_stack:
                    low[node] = min(low[node], low[target])
            if low[node] == index[node]:
                component: set[uuid.UUID] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                components.append(component)
    return components


# ── one of a kind ────────────────────────────────────────────────────────────


def _several(kept: dict[Key, Row], kind: str) -> list[Issue]:
    """More than one of what a thing has one of: all kept — the surest
    first — the others said."""
    by_source: dict[uuid.UUID, list[Key]] = defaultdict(list)
    for key, row in kept.items():
        if row["type"] == kind:
            by_source[key[0]].append(key)
    issues: list[Issue] = []
    for keys in by_source.values():
        if len(keys) < 2:
            continue
        ranked = sorted(
            keys,
            key=lambda k: (kept[k]["origin"] != "stated", -float(str(kept[k]["confidence"]))),
        )
        targets = [str(k[1]) for k in ranked]
        for other in ranked[1:]:
            issues.append(_issue(kept[other], "several_targets", "warning", {"targets": targets}))
    return issues


# ── helpers ──────────────────────────────────────────────────────────────────


def _issue(row: Row, issue: str, severity: str, detail: dict[str, object]) -> Issue:
    return Issue(
        type=str(row["type"]),
        issue=issue,
        severity=severity,
        from_id=_uuid(row["from_entity_id"]),
        to_id=_uuid(row["to_entity_id"]),
        origin=str(row["origin"]),
        rule=str(row["rule"]),
        confidence=float(str(row["confidence"])),
        detail=detail,
    )


def _uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _state(row: Row) -> dict[str, object]:
    attributes = row.get("attributes")
    environments = attributes.get("environments") if isinstance(attributes, dict) else None
    return {
        "confidence": float(str(row["confidence"])),
        "origin": str(row["origin"]),
        "rule": str(row["rule"]),
        "environments": [str(e) for e in environments] if isinstance(environments, list) else [],
    }


def _differs(before: dict[str, object], after: dict[str, object]) -> bool:
    moved = abs(float(str(before["confidence"])) - float(str(after["confidence"])))
    return moved >= CHANGED or any(
        before[name] != after[name] for name in ("origin", "rule", "environments")
    )


def _change(
    key: Key,
    change: str,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    now: datetime,
) -> Row:
    return {
        "from_entity_id": key[0],
        "to_entity_id": key[1],
        "type": key[2],
        "change": change,
        "before": before,
        "after": after,
        "recorded_at": now,
    }

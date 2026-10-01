"""The parsing engine: an ExtractedRecord in, its facts out, failures isolated.

Every record is read the same way — its text for references and people,
then the rules of its kind — so there is no "unsupported" record: one the
rules know nothing of still has its text read. What can fail is the input
(not an ExtractedRecord) or a rule choking on it; either is a ParseFailure
for that record alone.

PARSER_VERSION is raised when what parsing finds changes: the records parsed
by the old one are then parsed again.
"""

from __future__ import annotations

from pydantic import ValidationError

from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.parsing import rules, text
from leka.ingestion.parsing.contract import (
    Fact,
    Parsed,
    ParsedRecord,
    ParseFailure,
    ParseFailureCode,
    Quality,
)

# 2: application and criticality tags (LEKA-362); `tier` read by its value.
# 3: what resources are in — accounts, subscriptions, resource groups,
#    projects — and the cluster a machine is a node of (LEKA-363).
PARSER_VERSION = 3
CODE_HOSTS = frozenset({"github", "gitlab", "bitbucket"})
MAX_FACTS = 500  # a page listing a thousand tickets says little about each


def parse(record: ExtractedRecord) -> Parsed:
    """One extracted record's facts, structure and quality — or why not."""
    try:
        kind = record.provenance.source_kind.value
        system = kind if kind in CODE_HOSTS else None
        texts = ([("title", record.title)] if record.title else []) + [
            (f"content.{c.role}", c.text) for c in record.content
        ]
        facts: list[Fact] = []
        for field, body in texts:
            facts += text.facts(field, body, system=system)
        facts += rules.for_record(record)
        return ParsedRecord(
            provenance=record.provenance,
            extractor=record.extractor,
            extractor_version=record.extractor_version,
            parser_version=PARSER_VERSION,
            facts=_strongest(facts)[:MAX_FACTS],
            structure=text.structure([t for t in texts if t[0] != "title"]),
            quality=_quality(record),
        )
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError) as error:
        return ParseFailure(
            provenance=record.provenance,
            parser_version=PARSER_VERSION,
            code=ParseFailureCode.MALFORMED,
            message=f"unexpected shape ({type(error).__name__})",
        )


def parse_stored(result: object) -> Parsed:
    """An extraction row's `result`, parsed. A result that is not an
    ExtractedRecord — a contract changed under it — is a failure, named by
    field, never quoted."""
    try:
        record = ExtractedRecord.model_validate(result)
    except ValidationError as error:
        where = sorted(
            {".".join(str(p) for p in e["loc"]) + f" ({e['type']})" for e in error.errors()}
        )
        return ParseFailure(
            provenance=None,
            parser_version=PARSER_VERSION,
            code=ParseFailureCode.MALFORMED,
            message=("not an extracted record: " + ", ".join(where))[:500],
        )
    return parse(record)


def _strongest(facts: list[Fact]) -> list[Fact]:
    """One fact per (type, value, target): the surest, first found."""
    best: dict[tuple[str, str | None, str | None, str | None], Fact] = {}
    for fact in facts:
        key = (
            fact.type.value,
            fact.value if fact.target is None else None,
            fact.target.kind if fact.target else None,
            fact.target.key if fact.target else None,
        )
        if key not in best or fact.confidence > best[key].confidence:
            best[key] = fact
    return list(best.values())


def _quality(record: ExtractedRecord) -> Quality:
    """How much there was to read. Work items are meant to be described;
    a commit, a branch, a resource are not."""
    score, notes = 1.0, list[str]()
    if not record.title:
        score, notes = score - 0.3, [*notes, "no title"]
    described = record.provenance.capability.value in {"pull_requests", "issues", "projects"}
    if described and not record.content:
        score, notes = score - 0.2, [*notes, "no description"]
    if any(c.truncated for c in record.content):
        score, notes = score - 0.2, [*notes, "text cut at 100 000 characters"]
    return Quality(score=round(max(score, 0.0), 2), notes=notes)

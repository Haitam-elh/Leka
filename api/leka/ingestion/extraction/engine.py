"""The extraction engine: one strategy per kind of record, failures isolated.

A strategy is a pure function of one payload — no database, no network, no
clock — registered for the (source kind, capability) pairs it knows. The
engine finds it, runs it, and turns whatever goes wrong into an
ExtractionFailure for that record alone.

A strategy has a version. Changing what it extracts means raising it: the
records extracted by the old one are then extracted again (LEKA-354, the
job), and parsing knows which version it is reading.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from leka.connectors import Capability, RawRecord, SourceKind
from leka.ingestion.extraction.contract import (
    Extracted,
    ExtractedRecord,
    Extraction,
    ExtractionFailure,
    FailureCode,
    Provenance,
)
from leka.ingestion.sync import checksum

Payload = dict[str, object]


class MalformedPayloadError(ValueError):
    """The payload is not the shape the strategy knows. Its message names
    what is wrong — a field — and never carries a value from the payload."""


@dataclass(frozen=True)
class Strategy:
    name: str
    version: int
    extract: Callable[[Payload], Extracted]


_STRATEGIES: dict[tuple[SourceKind, Capability], Strategy] = {}


def strategy(
    name: str, version: int, *targets: tuple[SourceKind, Capability]
) -> Callable[[Callable[[Payload], Extracted]], Callable[[Payload], Extracted]]:
    """Register a function as the strategy for these (kind, capability) pairs."""

    def register(function: Callable[[Payload], Extracted]) -> Callable[[Payload], Extracted]:
        for target in targets:
            if target in _STRATEGIES:
                msg = f"{target} already has the strategy {_STRATEGIES[target].name}"
                raise ValueError(msg)
            _STRATEGIES[target] = Strategy(name, version, function)
        return function

    return register


def strategy_for(kind: SourceKind, capability: Capability) -> Strategy | None:
    return _STRATEGIES.get((kind, capability))


def supported() -> frozenset[tuple[SourceKind, Capability]]:
    return frozenset(_STRATEGIES)


def extract(
    record: RawRecord,
    *,
    source_id: uuid.UUID,
    source_kind: SourceKind,
    payload_key: str | None = None,
) -> Extraction:
    """One stored record, extracted — or the reason it was not. Never raises
    for what is in the payload."""
    provenance = Provenance(
        source_id=source_id,
        source_kind=source_kind,
        capability=record.kind,
        external_id=record.external_id,
        container=record.container,
        fetched_at=record.fetched_at,
        checksum=checksum(record),
        payload_key=payload_key,
    )
    found = strategy_for(source_kind, record.kind)
    if found is None:
        return ExtractionFailure(
            provenance=provenance,
            extractor=None,
            extractor_version=None,
            code=FailureCode.UNSUPPORTED,
            message=f"no extraction for {source_kind.value} {record.kind.value} yet",
        )
    try:
        fields = found.extract(record.payload)
        return ExtractedRecord(
            provenance=provenance,
            extractor=found.name,
            extractor_version=found.version,
            **dict(fields),
        )
    except (
        MalformedPayloadError,
        ValidationError,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ) as error:
        return ExtractionFailure(
            provenance=provenance,
            extractor=found.name,
            extractor_version=found.version,
            code=FailureCode.MALFORMED,
            message=_describe(error),
        )


def _describe(error: Exception) -> str:
    """What went wrong, without a value from the payload: a customer's
    ticket text has no business in a diagnostic."""
    if isinstance(error, MalformedPayloadError):
        return str(error)
    if isinstance(error, ValidationError):
        where = sorted(
            {".".join(str(p) for p in e["loc"]) + f" ({e['type']})" for e in error.errors()}
        )
        return "invalid: " + ", ".join(where)
    if isinstance(error, KeyError):
        return f"missing field {error.args[0]!r}" if error.args else "missing field"
    return f"unexpected shape ({type(error).__name__})"

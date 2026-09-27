"""The normalisation engine: an extraction and its parse in, candidates out.

Failures are isolated per record, and named: `unsupported` (no mapping for
this kind of record), `invalid` (it cannot be an entity — no name, no
number), `malformed` (the stored inputs are not what they should be). What
normalisation could map but not fully — a state no table knows — is not a
failure: it is kept as the vendor wrote it, and said in `diagnostics`.

NORMALISER_VERSION is raised when the rules change: what the old ones
normalised is normalised again.
"""

from __future__ import annotations

from pydantic import ValidationError

from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.normalisation.contract import (
    NormalisationFailure,
    NormalisationFailureCode,
    Normalised,
    NormalisedRecord,
)
from leka.ingestion.normalisation.mapping import (
    Build,
    InvalidRecordError,
    UnsupportedRecordError,
    entity,
)
from leka.ingestion.parsing import ParsedRecord

NORMALISER_VERSION = 1


def normalise(extracted: ExtractedRecord, parsed: ParsedRecord) -> Normalised:
    """One record's candidates — or why there are none."""
    if extracted.provenance != parsed.provenance:
        return _failure(
            extracted,
            NormalisationFailureCode.MALFORMED,
            "the parse is not of this extraction (provenance differs)",
        )
    build = Build(record=extracted, parsed=parsed)
    try:
        main = entity(build)
    except UnsupportedRecordError as error:
        return _failure(extracted, NormalisationFailureCode.UNSUPPORTED, str(error))
    except InvalidRecordError as error:
        return _failure(extracted, NormalisationFailureCode.INVALID, str(error))
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError) as error:
        return _failure(
            extracted,
            NormalisationFailureCode.MALFORMED,
            f"unexpected shape ({type(error).__name__})",
        )
    return NormalisedRecord(
        provenance=extracted.provenance,
        extractor_version=extracted.extractor_version,
        parser_version=parsed.parser_version,
        normaliser_version=NORMALISER_VERSION,
        entity=main,
        related=[e for e in build.related.values() if e.key != main.key],
        relationships=list(build.relationships.values()),
        diagnostics=sorted(set(build.diagnostics)),
    )


def normalise_stored(extracted: object, parsed: object) -> Normalised:
    """From an extraction row's and a parse row's `result`. Inputs that no
    longer read are a failure, named by field, never quoted."""
    try:
        record = ExtractedRecord.model_validate(extracted)
        parse = ParsedRecord.model_validate(parsed)
    except ValidationError as error:
        where = sorted(
            {".".join(str(p) for p in e["loc"]) + f" ({e['type']})" for e in error.errors()}
        )
        return NormalisationFailure(
            provenance=None,
            normaliser_version=NORMALISER_VERSION,
            code=NormalisationFailureCode.MALFORMED,
            message=("inputs do not read: " + ", ".join(where))[:500],
        )
    return normalise(record, parse)


def _failure(
    record: ExtractedRecord, code: NormalisationFailureCode, message: str
) -> NormalisationFailure:
    return NormalisationFailure(
        provenance=record.provenance,
        normaliser_version=NORMALISER_VERSION,
        code=code,
        message=message,
    )

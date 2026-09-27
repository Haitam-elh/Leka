"""Normalisation (LEKA-356): an extraction and its parse in, candidates in
LEKA's common structures out — canonical keys, canonical attributes,
provenance. Rules: docs/normalisation.md.
"""

from leka.ingestion.normalisation.contract import (
    NormalisationFailure,
    NormalisationFailureCode,
    Normalised,
    NormalisedRecord,
)
from leka.ingestion.normalisation.engine import (
    NORMALISER_VERSION,
    normalise,
    normalise_stored,
)

__all__ = [
    "NORMALISER_VERSION",
    "NormalisationFailure",
    "NormalisationFailureCode",
    "Normalised",
    "NormalisedRecord",
    "normalise",
    "normalise_stored",
]

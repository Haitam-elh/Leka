"""Validation (LEKA-358): whether a processed record may become the
company's knowledge — valid, warning, or quarantined — why, what to do, and
how good it is. Rules: docs/validation.md."""

from leka.ingestion.validation.rules import (
    VALIDATOR_VERSION,
    Issue,
    Severity,
    Validation,
    validate,
)

__all__ = ["VALIDATOR_VERSION", "Issue", "Severity", "Validation", "validate"]

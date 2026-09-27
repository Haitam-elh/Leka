"""Parsing (LEKA-355): an extracted record in, what it means out — facts,
each with its confidence and its evidence. Contract: docs/parsing.md.
"""

from leka.ingestion.parsing.contract import (
    MAX_EXCERPT,
    Evidence,
    Fact,
    FactType,
    Parsed,
    ParsedRecord,
    ParseFailure,
    ParseFailureCode,
    Quality,
    Target,
    TextStructure,
)
from leka.ingestion.parsing.engine import PARSER_VERSION, parse, parse_stored

__all__ = [
    "MAX_EXCERPT",
    "PARSER_VERSION",
    "Evidence",
    "Fact",
    "FactType",
    "ParseFailure",
    "ParseFailureCode",
    "Parsed",
    "ParsedRecord",
    "Quality",
    "Target",
    "TextStructure",
    "parse",
    "parse_stored",
]

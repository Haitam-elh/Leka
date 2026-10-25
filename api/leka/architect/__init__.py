"""The application architect's core (2026-10-25): what it reads, what it
asks, what it delivers — the same on LEKA and wherever it is installed.

    pages       Confluence pages and their tree
    confluence  Confluence read: its API (Cloud, Data Center) or an export
    llm         the model asked: Anthropic, or any OpenAI-compatible API
    prompts     what the model is told
    analysis    the steps: pages → batches → the dossier
    model       the dossier, structured as ArchiMate 3.1, its evidence
    render      the dossier written: Markdown, Word, PDF
    compare     the dossier against a reference document

Standing alone: it imports nothing of LEKA's, only the standard library
(reportlab for the PDF), and runs on any Python from 3.9. LEKA uses it as
leka.architect; the downloadable agent ships it as leka_architect — the
same files.
"""

from __future__ import annotations

from .analysis import Budget, analyse, analyse_async, batches, merge, perimeter
from .compare import Comparison, compare, reference
from .confluence import Client, ConfluenceError, Site, read_folder, read_space, text_of
from .llm import LLM, LLMError, from_env
from .model import (
    ELEMENT_TYPES,
    LAYERS,
    RELATION_TYPES,
    SCHEMA,
    SECTIONS,
    Dossier,
    DossierError,
    Element,
    Evidence,
    Relation,
    Section,
    dossier_of,
    parsed,
    problems,
)
from .pages import Node, Page, Tree
from .render import MEDIA_TYPES, RenderError, docx, markdown, pdf

__version__ = "1.0.0"

__all__ = [
    "ELEMENT_TYPES",
    "LAYERS",
    "LLM",
    "MEDIA_TYPES",
    "RELATION_TYPES",
    "SCHEMA",
    "SECTIONS",
    "Budget",
    "Client",
    "Comparison",
    "ConfluenceError",
    "Dossier",
    "DossierError",
    "Element",
    "Evidence",
    "LLMError",
    "Node",
    "Page",
    "Relation",
    "RenderError",
    "Section",
    "Site",
    "Tree",
    "__version__",
    "analyse",
    "analyse_async",
    "batches",
    "compare",
    "docx",
    "dossier_of",
    "from_env",
    "markdown",
    "merge",
    "parsed",
    "pdf",
    "perimeter",
    "problems",
    "read_folder",
    "read_space",
    "reference",
    "text_of",
]

"""An agent's deck, drawn: the content the model delivers (deck.py), laid
out on the agent's template (layout.py), written as an editable PowerPoint
(pptx_writer.py) and as its PDF (pdf_writer.py). Pure: no I/O, no model.
"""

from __future__ import annotations

from dataclasses import dataclass

from leka.capabilities.deliverables.deck import ArchitectureDeck
from leka.capabilities.deliverables.layout import deck_slides
from leka.capabilities.deliverables.pdf_writer import write_pdf
from leka.capabilities.deliverables.pptx_writer import write_pptx

MEDIA_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


@dataclass(frozen=True)
class Rendered:
    pptx: bytes
    pdf: bytes
    slides: int

    def of(self, fmt: str) -> bytes:
        return self.pptx if fmt == "pptx" else self.pdf


def render(deck: ArchitectureDeck) -> Rendered:
    slides = deck_slides(deck)
    title = f"Architecture applicative - Parcours {deck.parcours}"
    return Rendered(pptx=write_pptx(slides), pdf=write_pdf(slides, title), slides=len(slides))


__all__ = ["MEDIA_TYPES", "ArchitectureDeck", "Rendered", "render"]

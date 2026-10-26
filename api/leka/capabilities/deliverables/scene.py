"""What a slide is made of, drawn the same in a PowerPoint and a PDF: shapes
placed in inches on a 13.333 by 7.5 in landscape slide, in the order they are
drawn — the first at the back.

Text is measured with Helvetica's metrics (reportlab), Arial's twin, so that
a line wrapped here wraps the same in both files.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth

WIDTH, HEIGHT = 13.333, 7.5
MARGIN = 0.4

# The template's colours.
NAVY = "1F3864"
ORANGE = "F4802A"
GREY_TEXT = "6B6B6B"
WHITE = "FFFFFF"
BLACK = "000000"
LIFELINE = "3A3A3A"
STEEL = "6E97C2"
SERVICE = "9DC3E6"
SERVICE_LINE = "5E86B3"
FRONT = "7FC6EC"
BAND = "DCDCDC"
YELLOW = "FBF3C5"
CREAM = "FCFAE6"
OLIVE = "9A8B55"
TAG = "CDE6B4"
RED = "C00000"
ZEBRA = "F2F2F2"
ACTOR = "5B7FA6"
EXTERNAL = "BFBFBF"
NEW = "00A86B"

Shape = Literal["rect", "round", "ellipse", "hexagon", "chevron", "can"]


@dataclass(frozen=True)
class Box:
    """A shape, filled or not, with its text."""

    x: float
    y: float
    w: float
    h: float
    shape: Shape = "rect"
    fill: str | None = None
    line: str | None = None
    line_width: float = 0.75
    dashed: bool = False
    text: str = ""
    size: float = 9
    bold: bool = False
    italic: bool = False
    color: str = BLACK
    align: Literal["left", "center", "right"] = "center"
    valign: Literal["top", "middle", "bottom"] = "middle"
    inset: float = 0.04


@dataclass(frozen=True)
class Stroke:
    """A straight line, an arrow at its end or not."""

    x1: float
    y1: float
    x2: float
    y2: float
    color: str = BLACK
    width: float = 0.75
    dashed: bool = False
    arrow: bool = False


@dataclass(frozen=True)
class Cell:
    text: str
    color: str = BLACK
    bold: bool = False
    fill: str | None = None


@dataclass(frozen=True)
class Table:
    """A native table: its header row, its rows, each column's width."""

    x: float
    y: float
    widths: tuple[float, ...]
    header: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    heights: tuple[float, ...]  # the header's first
    size: float = 8
    header_fill: str = NAVY
    header_color: str = WHITE
    zebra: str = ZEBRA
    margin: float = 0.03


Item = Box | Stroke | Table


@dataclass
class Slide:
    items: list[Item] = field(default_factory=list)

    def add(self, *items: Item) -> None:
        self.items.extend(items)


# ── text, measured ──────────────────────────────────────────────────────────


def font_of(bold: bool = False, italic: bool = False) -> str:
    if bold and italic:
        return "Helvetica-BoldOblique"
    if bold:
        return "Helvetica-Bold"
    if italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def text_width(text: str, size: float, bold: bool = False, italic: bool = False) -> float:
    """In inches."""
    return float(stringWidth(text, font_of(bold, italic), size)) / 72


def wrap(text: str, width: float, size: float, bold: bool = False) -> list[str]:
    """`text` cut into lines no wider than `width` inches."""
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        lines.extend(simpleSplit(paragraph, font_of(bold), size, max(width, 0.1) * 72) or [""])
    return lines


def line_height(size: float) -> float:
    return size * 1.2 / 72


def text_height(text: str, width: float, size: float, bold: bool = False) -> float:
    return len(wrap(text, width, size, bold)) * line_height(size)


def fit_size(
    text: str, width: float, height: float, size: float, least: float = 5.5, bold: bool = False
) -> float:
    """The largest size, down to `least`, at which `text` fits the box — its
    height, and its widest line: a word longer than the box is never cut, so
    the size comes down for it (2026-10-25: « Enregistrement » ran out of its
    step)."""
    while size > least and (
        text_height(text, width, size, bold) > height
        or max((text_width(line, size, bold) for line in wrap(text, width, size, bold)), default=0)
        > width
    ):
        size -= 0.5
    return size


def side_inset(shape: str, w: float, h: float, inset: float) -> float:
    """A shape's text margin left and right: a chevron's or a hexagon's
    points take room from its text."""
    if shape == "chevron":
        return inset + min(w, h) * 0.375
    if shape == "hexagon":
        return inset + min(w, h) * 0.2
    return inset


def row_heights(
    rows: Sequence[Sequence[str]], widths: Sequence[float], size: float, margin: float
) -> list[float]:
    """Each row's height: its tallest cell, wrapped, plus its margins."""
    found = []
    for row in rows:
        tallest = max(
            (text_height(text, w - 2 * margin, size) for text, w in zip(row, widths, strict=True)),
            default=line_height(size),
        )
        found.append(tallest + 2 * margin + 0.02)
    return found


__all__ = [
    "HEIGHT",
    "MARGIN",
    "WIDTH",
    "Box",
    "Cell",
    "Item",
    "Shape",
    "Slide",
    "Stroke",
    "Table",
    "fit_size",
    "font_of",
    "line_height",
    "row_heights",
    "side_inset",
    "text_height",
    "text_width",
    "wrap",
]

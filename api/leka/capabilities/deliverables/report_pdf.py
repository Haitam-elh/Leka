"""Every agent's deliverable as a PDF (Karim, 2026-10-23: « un vrai
livrable, pas que du texte » — the architect's deck has its own, every other
agent this one).

The report as the agent wrote it in markdown, laid out on A4: LEKA's band,
the agent and when it delivered, then its headings, paragraphs, lists,
tables and code — bold, italics and inline code kept. Drawn on demand from
what the run kept, never stored: the report is the source.

Helvetica writes Windows-1252: what it cannot draw is said in what it can
(pdf_writer.plain). The ids an agent cites ([uuid]) stay out of the page,
as on the screen.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import BaseDocTemplate

from leka.capabilities.deliverables.pdf_writer import plain

NAVY = colors.HexColor("#0B1F4D")
VIOLET = colors.HexColor("#5B3DF5")
MUTED = colors.HexColor("#5F6B85")
LINE = colors.HexColor("#E3E7F0")
CANVAS = colors.HexColor("#F5F7FB")

_ID = r"\[[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\]"
_CITED = re.compile(rf"(?:\s*(?:,|\bet\b|\band\b)?\s*{_ID})+", re.IGNORECASE)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=NAVY, alignment=TA_LEFT
    )
    return {
        "body": body,
        "h1": ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20,
                             spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=17,
                             spaceBefore=12, spaceAfter=4, textColor=VIOLET),
        "h3": ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=11, leading=15,
                             spaceBefore=8, spaceAfter=3),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11),
        "head": ParagraphStyle("head", parent=body, fontName="Helvetica-Bold", fontSize=8.5,
                               leading=11),
        "code": ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8, leading=10.5,
                               backColor=CANVAS, borderPadding=4, leftIndent=4),
        "meta": ParagraphStyle("meta", parent=body, fontSize=8.5, textColor=MUTED),
    }  # fmt: skip


def _inline(text: str) -> str:
    """One line of markdown as reportlab's markup: escaped first, then
    bold, italics, code and links."""
    said = escape(plain(_CITED.sub("", text)))
    said = _CODE.sub(lambda m: f'<font face="Courier">{m.group(1)}</font>', said)
    said = _BOLD.sub(r"<b>\1</b>", said)
    said = _ITALIC.sub(r"<i>\1</i>", said)
    return _LINK.sub(r'<link href="\2" color="#5B3DF5">\1</link>', said)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _blocks(markdown: str, s: dict[str, ParagraphStyle]) -> Iterator[Flowable]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    paragraph: list[str] = []

    def flush() -> Iterator[Flowable]:
        if paragraph:
            yield Paragraph(_inline(" ".join(paragraph)), s["body"])
            yield Spacer(1, 4)
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            yield from flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(plain(lines[i]))
                i += 1
            yield Preformatted("\n".join(code), s["code"], maxLineLength=110)
            yield Spacer(1, 6)
            i += 1
            continue
        if not line.strip() or _RULE.match(line):
            yield from flush()
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            yield from flush()
            level = min(len(heading.group(1)), 3)
            yield Paragraph(_inline(heading.group(2)), s[f"h{level}"])
            i += 1
            continue
        if _ROW.match(line) and i + 1 < len(lines) and _DIVIDER.match(lines[i + 1]):
            yield from flush()
            head = _cells(line)
            rows = [[Paragraph(_inline(c), s["head"]) for c in head]]
            i += 2
            while i < len(lines) and _ROW.match(lines[i]):
                cells = (_cells(lines[i]) + [""] * len(head))[: len(head)]
                rows.append([Paragraph(_inline(c), s["cell"]) for c in cells])
                i += 1
            table = Table(rows, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), CANVAS),
                        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            yield table
            yield Spacer(1, 8)
            continue
        listed = _BULLET.match(line) or _NUMBERED.match(line)
        if listed:
            yield from flush()
            numbered = bool(_NUMBERED.match(line))
            pattern = _NUMBERED if numbered else _BULLET
            texts: list[str] = []
            while i < len(lines):
                item = pattern.match(lines[i])
                if item is not None:
                    texts.append(item.group(2))
                elif texts and lines[i].strip() and lines[i].startswith((" ", "\t")):
                    # A line that continues the item before.
                    texts[-1] = f"{texts[-1]} {lines[i].strip()}"
                else:
                    break
                i += 1
            items = [ListItem(Paragraph(_inline(text), s["body"])) for text in texts]
            yield ListFlowable(
                items,
                bulletType="1" if numbered else "bullet",
                start="1" if numbered else None,
                bulletFormat="%s." if numbered else None,
                leftIndent=14,
                bulletFontSize=8 if not numbered else 9,
            )
            yield Spacer(1, 6)
            continue
        paragraph.append(line.strip())
        i += 1
    yield from flush()


def report_pdf(*, title: str, agent: str, when: datetime | None, markdown: str) -> bytes:
    """The deliverable laid out as a PDF: its band, its title, then the
    report."""
    s = _styles()
    out = BytesIO()

    def band(c: Canvas, doc: BaseDocTemplate) -> None:
        width, height = A4
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, height - 14 * mm, width, 14 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(18 * mm, height - 9 * mm, "LEKA")
        c.setFont("Helvetica", 8)
        c.drawRightString(width - 18 * mm, height - 9 * mm, plain(agent)[:90])
        c.setFillColor(MUTED)
        c.drawRightString(width - 18 * mm, 10 * mm, str(doc.page))
        c.restoreState()

    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=plain(title),
        author="LEKA",
    )
    story: list[Flowable] = [
        KeepTogether(
            [
                Paragraph(_inline(title), s["h1"]),
                Paragraph(
                    _inline(f"{agent}" + (f" — {when:%d/%m/%Y %H:%M}" if when else "")), s["meta"]
                ),
                Spacer(1, 8),
            ]
        ),
        *_blocks(markdown, s),
    ]
    doc.build(story, onFirstPage=band, onLaterPages=band)
    return out.getvalue()


__all__ = ["report_pdf"]

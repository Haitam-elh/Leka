"""The same slides, drawn as a PDF — one landscape page per slide, each
shape where the PowerPoint has it, in the same order, Helvetica for Arial.
"""

from __future__ import annotations

import math
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from leka.capabilities.deliverables.scene import (
    HEIGHT,
    WIDTH,
    Box,
    Cell,
    Slide,
    Stroke,
    Table,
    font_of,
    line_height,
    side_inset,
)

PT = 72  # points per inch

# What Helvetica cannot draw (it writes Windows-1252), said in what it can.
_PLAIN = str.maketrans(
    {
        "\u2192": "->",
        "\u2190": "<-",
        "\u21d2": "=>",
        "\u2194": "<->",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u2260": "!=",
        "\u2713": "v",
        "\u2714": "v",
        "\u2715": "x",
        "\u2717": "x",
        "\u202f": " ",
        "\u00a0": " ",
    }
)


def plain(text: str) -> str:
    text = text.translate(_PLAIN)
    return text.encode("cp1252", errors="replace").decode("cp1252")


class _Page:
    """A slide's page: inches from the top left, as the scene places them."""

    def __init__(self, canvas: Canvas) -> None:
        self.c = canvas

    @staticmethod
    def x(value: float) -> float:
        return value * PT

    @staticmethod
    def y(value: float) -> float:
        return (HEIGHT - value) * PT

    def _pen(self, colour: str | None, width: float, dashed: bool) -> None:
        if colour:
            self.c.setStrokeColor(HexColor("#" + colour))
        self.c.setLineWidth(width)
        self.c.setDash(3, 2) if dashed else self.c.setDash()

    def box(self, box: Box) -> None:
        c = self.c
        fill = 1 if box.fill else 0
        stroke = 1 if box.line else 0
        if box.fill:
            c.setFillColor(HexColor("#" + box.fill))
        self._pen(box.line, box.line_width, box.dashed)
        x, y, w, h = self.x(box.x), self.y(box.y + box.h), box.w * PT, box.h * PT
        short = min(w, h)
        if fill or stroke:
            if box.shape == "round":
                c.roundRect(x, y, w, h, short * 0.16667, stroke=stroke, fill=fill)
            elif box.shape == "ellipse":
                c.ellipse(x, y, x + w, y + h, stroke=stroke, fill=fill)
            elif box.shape == "hexagon":
                d = short * 0.25
                self._polygon(
                    [
                        (x, y + h / 2),
                        (x + d, y + h),
                        (x + w - d, y + h),
                        (x + w, y + h / 2),
                        (x + w - d, y),
                        (x + d, y),
                    ],
                    stroke,
                    fill,
                )
            elif box.shape == "chevron":
                d = min(short * 0.5, w / 2)
                self._polygon(
                    [
                        (x, y + h),
                        (x + w - d, y + h),
                        (x + w, y + h / 2),
                        (x + w - d, y),
                        (x, y),
                        (x + d, y + h / 2),
                    ],
                    stroke,
                    fill,
                )
            elif box.shape == "can":
                e = short * 0.25
                c.rect(x, y + e / 2, w, h - e, stroke=0, fill=fill)
                if stroke:
                    c.line(x, y + e / 2, x, y + h - e / 2)
                    c.line(x + w, y + e / 2, x + w, y + h - e / 2)
                c.ellipse(x, y, x + w, y + e, stroke=stroke, fill=fill)
                c.ellipse(x, y + h - e, x + w, y + h, stroke=stroke, fill=fill)
            else:
                c.rect(x, y, w, h, stroke=stroke, fill=fill)
        if box.text:
            inset = side_inset(box.shape, box.w, box.h, box.inset)
            self.text(
                box.text,
                box.x + inset,
                box.y + box.inset,
                box.w - 2 * inset,
                box.h - 2 * box.inset,
                box.size,
                box.bold,
                box.italic,
                box.color,
                box.align,
                box.valign,
            )

    def _polygon(self, points: list[tuple[float, float]], stroke: int, fill: int) -> None:
        path = self.c.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.close()
        self.c.drawPath(path, stroke=stroke, fill=fill)

    def text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        size: float,
        bold: bool,
        italic: bool,
        colour: str,
        align: str,
        valign: str,
    ) -> None:
        c = self.c
        font = font_of(bold, italic)
        lines: list[str] = []
        for paragraph in plain(text).split("\n"):
            lines.extend(simpleSplit(paragraph, font, size, max(w, 0.1) * PT) or [""])
        step = line_height(size)
        total = len(lines) * step
        top = y if valign == "top" else y + h - total if valign == "bottom" else y + (h - total) / 2
        c.setFillColor(HexColor("#" + colour))
        c.setFont(font, size)
        for i, line in enumerate(lines):
            base = self.y(top + i * step + size * 0.95 / PT)
            if align == "left":
                c.drawString(self.x(x), base, line)
            elif align == "right":
                c.drawRightString(self.x(x + w), base, line)
            else:
                c.drawCentredString(self.x(x + w / 2), base, line)

    def stroke(self, stroke: Stroke) -> None:
        c = self.c
        self._pen(stroke.color, stroke.width, stroke.dashed)
        x1, y1, x2, y2 = self.x(stroke.x1), self.y(stroke.y1), self.x(stroke.x2), self.y(stroke.y2)
        length = math.hypot(x2 - x1, y2 - y1)
        if stroke.arrow and length > 0:
            head = min(5.5 + stroke.width, length)
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            bx, by = x2 - ux * head, y2 - uy * head
            c.line(x1, y1, bx, by)
            c.setDash()
            c.setFillColor(HexColor("#" + stroke.color))
            half = head * 0.45
            self._polygon(
                [(x2, y2), (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)], 0, 1
            )
        else:
            c.line(x1, y1, x2, y2)

    def table(self, table: Table) -> None:
        c = self.c
        y = table.y
        head = tuple(
            Cell(text, table.header_color, True, table.header_fill) for text in table.header
        )
        rows = [head, *table.rows]
        for r, (row, height) in enumerate(zip(rows, table.heights, strict=True)):
            x = table.x
            for cell, width in zip(row, table.widths, strict=True):
                ground = table.zebra if r % 2 == 0 else "FFFFFF"
                text, colour, bold, fill = cell.text, cell.color, cell.bold, cell.fill or ground
                c.setFillColor(HexColor("#" + fill))
                self._pen("BFBFBF", 0.5, False)
                c.rect(self.x(x), self.y(y + height), width * PT, height * PT, stroke=1, fill=1)
                m = table.margin
                self.text(
                    text,
                    x + m,
                    y + m,
                    width - 2 * m,
                    height - 2 * m,
                    table.size,
                    bold,
                    False,
                    colour,
                    "left",
                    "middle",
                )
                x += width
            y += height


def write_pdf(slides: list[Slide], title: str = "") -> bytes:
    out = BytesIO()
    canvas = Canvas(out, pagesize=(WIDTH * PT, HEIGHT * PT))
    if title:
        canvas.setTitle(plain(title))
    canvas.setAuthor("LEKA")
    for scene in slides:
        page = _Page(canvas)
        canvas.setFillColor(HexColor("#FFFFFF"))
        canvas.rect(0, 0, WIDTH * PT, HEIGHT * PT, stroke=0, fill=1)
        for item in scene.items:
            if isinstance(item, Box):
                page.box(item)
            elif isinstance(item, Stroke):
                page.stroke(item)
            else:
                page.table(item)
        canvas.showPage()
    canvas.save()
    return out.getvalue()


__all__ = ["plain", "write_pdf"]

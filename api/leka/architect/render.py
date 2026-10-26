"""The dossier, written: Markdown, Word (.docx) and PDF — the same sections,
the same tables, the same evidence, whichever is opened.

    markdown()   text, links to each page cited
    docx()       a Word document, written as Word reads it (no dependency)
    pdf()        a PDF, through reportlab — RenderError when it is not there

Each section ends with its evidence: the Confluence pages it was read from,
each a link. The last part lists every page cited.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from xml.sax.saxutils import escape

from .model import SECTIONS, Dossier, Element, Evidence, Relation

# The flows: what goes from one element to another; the rest are dependencies.
FLOWS = ("Flux", "Déclenchement")
TO_CONFIRM = "À confirmer"


class RenderError(RuntimeError):
    """A format that cannot be written here: said why."""


def _flows(dossier: Dossier) -> list[Relation]:
    return [r for r in dossier.relations if r.type in FLOWS]


def _dependencies(dossier: Dossier) -> list[Relation]:
    return [r for r in dossier.relations if r.type not in FLOWS]


def _name(dossier: Dossier, element_id: str) -> str:
    element = dossier.element(element_id)
    return element.name if element is not None else element_id


def _rows(
    dossier: Dossier, key: str
) -> tuple[list[str], list[list[str]], list[Sequence[Evidence]]]:
    """A section's table: its header, its rows, each row's evidence."""
    if key in ("metier", "application", "technologie"):
        elements: list[Element] = dossier.of_layer(key)
        return (
            ["Type", "Élément", "Description", "Statut"],
            [
                [e.type, e.name, e.description, TO_CONFIRM if e.to_confirm else "Documenté"]
                for e in elements
            ],
            [e.evidence for e in elements],
        )
    if key in ("flux", "dependances"):
        relations = _flows(dossier) if key == "flux" else _dependencies(dossier)
        return (
            ["De", "Relation", "Vers", "Précision"],
            [
                [_name(dossier, r.source), r.type, _name(dossier, r.target), r.label]
                for r in relations
            ],
            [r.evidence for r in relations],
        )
    return [], [], []


# ── Markdown ─────────────────────────────────────────────────────────────────


def _md_cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _md_link(evidence: Evidence) -> str:
    title = evidence.title.replace("[", "(").replace("]", ")")
    return f"[{title}]({evidence.url})" if evidence.url else title


def markdown(dossier: Dossier) -> str:
    lines = [f"# {dossier.title}", "", f"*{dossier.scope}*", ""]
    lines += [
        "Dossier structuré selon ArchiMate 3.1, produit par l'Architecte applicatif LEKA "
        f"à partir de {len(dossier.pages_read)} pages Confluence, citées section par section.",
        "",
        "## Sommaire",
        "",
    ]
    lines += [f"{n}. {title}" for n, (_, title) in enumerate(SECTIONS, 1)]
    lines.append("")
    for n, (key, title) in enumerate(SECTIONS, 1):
        lines += [f"## {n}. {title}", ""]
        section = dossier.section(key)
        if key == "points":
            points = dossier.points or ([section.summary] if section and section.summary else [])
            lines += [f"{i}. {p}" for i, p in enumerate(points, 1)] if points else ["Aucun."]
            lines.append("")
            continue
        lines += [
            section.summary
            if section and section.summary
            else "Non documenté dans les pages lues.",
            "",
        ]
        header, rows, evidence = _rows(dossier, key)
        if rows:
            lines.append("| " + " | ".join([*header, "Sources"]) + " |")
            lines.append("|" + "---|" * (len(header) + 1))
            for row, cited in zip(rows, evidence):
                said = ", ".join(_md_link(e) for e in cited) or TO_CONFIRM
                lines.append("| " + " | ".join(_md_cell(c) for c in [*row, said]) + " |")
            lines.append("")
        if section and section.evidence:
            lines += ["**Sources :** " + ", ".join(_md_link(e) for e in section.evidence), ""]
    lines += ["## Pages consultées", ""]
    lines += [f"- {_md_link(e)}" for e in dossier.pages_read] or ["Aucune."]
    if dossier.dropped:
        lines += ["", "## Écarté à la vérification", ""]
        lines += [f"- {d}" for d in dossier.dropped]
    return "\n".join(lines).rstrip() + "\n"


# ── Word ─────────────────────────────────────────────────────────────────────

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {_W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="21"/><w:lang w:val="fr-FR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:color w:val="C55A11"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="1F5FBF"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:color="BFBFBF"/><w:left w:val="single" w:sz="4" w:color="BFBFBF"/><w:bottom w:val="single" w:sz="4" w:color="BFBFBF"/><w:right w:val="single" w:sz="4" w:color="BFBFBF"/><w:insideH w:val="single" w:sz="4" w:color="BFBFBF"/><w:insideV w:val="single" w:sz="4" w:color="BFBFBF"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""


class _Word:
    def __init__(self) -> None:
        self.body: list[str] = []
        self.links: list[str] = []

    def _run(self, text: str, *, bold: bool = False, italic: bool = False, color: str = "") -> str:
        props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "")
        props += f'<w:color w:val="{color}"/>' if color else ""
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'

    def _link(self, evidence: Evidence) -> str:
        if not evidence.url:
            return self._run(evidence.title)
        self.links.append(evidence.url)
        rid = f"rIdL{len(self.links)}"
        return (
            f'<w:hyperlink r:id="{rid}"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(evidence.title)}</w:t></w:r></w:hyperlink>'
        )

    def paragraph(self, runs: str, style: str = "") -> None:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        self.body.append(f"<w:p>{ppr}{runs}</w:p>")

    def text(self, text: str, style: str = "") -> None:
        self.paragraph(self._run(text), style)

    def cited(self, label: str, evidence: Sequence[Evidence]) -> None:
        runs = self._run(label, bold=True)
        for n, e in enumerate(evidence):
            runs += (self._run(", ") if n else "") + self._link(e)
        self.paragraph(runs)

    def table(
        self, header: list[str], rows: list[list[str]], cited: list[Sequence[Evidence]]
    ) -> None:
        def cell(content: str, *, head: bool = False) -> str:
            shade = (
                '<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="1F3864"/></w:tcPr>'
                if head
                else ""
            )
            return f"<w:tc>{shade}<w:p>{content}</w:p></w:tc>"

        xml = '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>'
        xml += (
            "<w:tr>"
            + "".join(
                cell(self._run(h, bold=True, color="FFFFFF"), head=True)
                for h in [*header, "Sources"]
            )
            + "</w:tr>"
        )
        for row, evidence in zip(rows, cited):
            said = "".join(
                (self._run(", ") if n else "") + self._link(e) for n, e in enumerate(evidence)
            )
            xml += "<w:tr>" + "".join(cell(self._run(c)) for c in row)
            xml += cell(said or self._run(TO_CONFIRM, color="C55A11")) + "</w:tr>"
        self.body.append(xml + "</w:tbl>")
        self.paragraph("")

    def document(self) -> bytes:
        sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>{"".join(self.body)}{sect}</w:body></w:document>'
        rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        for n, url in enumerate(self.links, 1):
            rels += f'<Relationship Id="rIdL{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{escape(url, {chr(34): "&quot;"})}" TargetMode="External"/>'
        rels += "</Relationships>"
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("[Content_Types].xml", _CONTENT_TYPES)
            zipped.writestr("_rels/.rels", _ROOT_RELS)
            zipped.writestr("word/document.xml", document)
            zipped.writestr("word/styles.xml", _STYLES)
            zipped.writestr("word/_rels/document.xml.rels", rels)
        return out.getvalue()


def docx(dossier: Dossier) -> bytes:
    word = _Word()
    word.text(dossier.title, "Title")
    word.text(dossier.scope, "Subtitle")
    word.text(
        "Dossier structuré selon ArchiMate 3.1, produit par l'Architecte applicatif LEKA à partir "
        f"de {len(dossier.pages_read)} pages Confluence, citées section par section."
    )
    for n, (key, title) in enumerate(SECTIONS, 1):
        word.text(f"{n}. {title}", "Heading1")
        section = dossier.section(key)
        if key == "points":
            points = dossier.points or ([section.summary] if section and section.summary else [])
            for i, point in enumerate(points or ["Aucun."], 1):
                word.text(f"{i}. {point}" if points else point)
            continue
        word.text(
            section.summary if section and section.summary else "Non documenté dans les pages lues."
        )
        header, rows, evidence = _rows(dossier, key)
        if rows:
            word.table(header, rows, evidence)
        if section and section.evidence:
            word.cited("Sources : ", section.evidence)
    word.text("Pages consultées", "Heading1")
    for read in dossier.pages_read:
        word.paragraph(word._link(read))
    if dossier.dropped:
        word.text("Écarté à la vérification", "Heading1")
        for dropped in dossier.dropped:
            word.text(dropped)
    return word.document()


# ── PDF ──────────────────────────────────────────────────────────────────────


def pdf(dossier: Dossier) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:  # pragma: no cover - reportlab ships with LEKA
        raise RenderError("le PDF demande reportlab : pip install reportlab") from error

    navy, orange = colors.HexColor("#1F3864"), colors.HexColor("#C55A11")
    sheet = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=sheet["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13
    )
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=small, textColor=colors.white, fontName="Helvetica-Bold")
    title = ParagraphStyle(
        "title", parent=sheet["Title"], fontName="Helvetica-Bold", textColor=navy, alignment=0
    )
    h1 = ParagraphStyle("h1", parent=sheet["Heading2"], fontName="Helvetica-Bold", textColor=navy)
    sub = ParagraphStyle("sub", parent=body, fontName="Helvetica-Oblique", textColor=orange)

    def link(e: Evidence) -> str:
        said = escape(e.title)
        return (
            f'<link href="{escape(e.url)}" color="#1F5FBF"><u>{said}</u></link>' if e.url else said
        )

    flow: list[object] = [
        Paragraph(escape(dossier.title), title),
        Paragraph(escape(dossier.scope), sub),
        Spacer(1, 0.3 * cm),
        Paragraph(
            escape(
                "Dossier structuré selon ArchiMate 3.1, produit par l'Architecte applicatif LEKA "
                f"à partir de {len(dossier.pages_read)} pages Confluence, citées section par section."
            ),
            body,
        ),
    ]
    for n, (key, name) in enumerate(SECTIONS, 1):
        flow.append(Paragraph(escape(f"{n}. {name}"), h1))
        section = dossier.section(key)
        if key == "points":
            points = dossier.points or ([section.summary] if section and section.summary else [])
            flow += [Paragraph(escape(f"{i}. {p}"), body) for i, p in enumerate(points, 1)] or [
                Paragraph("Aucun.", body)
            ]
            continue
        flow.append(
            Paragraph(
                escape(
                    section.summary
                    if section and section.summary
                    else "Non documenté dans les pages lues."
                ),
                body,
            )
        )
        header, rows, evidence = _rows(dossier, key)
        if rows:
            data = [[Paragraph(escape(h), head) for h in [*header, "Sources"]]]
            for row, cited in zip(rows, evidence):
                said = (
                    ", ".join(link(e) for e in cited)
                    or f'<font color="#C55A11">{TO_CONFIRM}</font>'
                )
                data.append([Paragraph(escape(c), small) for c in row] + [Paragraph(said, small)])
            width = 17.5 * cm
            table = Table(
                data, colWidths=[width * w for w in (0.17, 0.2, 0.33, 0.1, 0.2)], repeatRows=1
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), navy),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#F2F2F2")],
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            flow += [Spacer(1, 0.2 * cm), table]
        if section and section.evidence:
            flow += [
                Spacer(1, 0.15 * cm),
                Paragraph(
                    "<b>Sources :</b> " + ", ".join(link(e) for e in section.evidence), small
                ),
            ]
    flow.append(Paragraph("Pages consultées", h1))
    flow += [Paragraph(link(e), small) for e in dossier.pages_read] or [Paragraph("Aucune.", small)]
    if dossier.dropped:
        flow.append(Paragraph("Écarté à la vérification", h1))
        flow += [Paragraph(escape(d), small) for d in dossier.dropped]
    out = io.BytesIO()
    SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=dossier.title,
        author="LEKA, Architecte applicatif",
    ).build(flow)
    return out.getvalue()


MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "json": "application/json",
}

__all__ = ["MEDIA_TYPES", "RenderError", "docx", "markdown", "pdf"]

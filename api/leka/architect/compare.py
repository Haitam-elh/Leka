"""The architect's dossier against a reference document — the one another
agent produced on the same Confluence: section by section, what both cover,
what the reference has that the dossier lacks, what the dossier adds; and
which of the dossier's elements the reference names too.

    reference()   a document read: Markdown, HTML, Word (.docx) or text —
                  its headings and its text
    compare()     the two, side by side
    markdown()    the comparison, written

What decides a section is covered: its title's words, as architects write
them (« couche métier », « business layer », « vue applicative »…), found
among the reference's headings. Nothing is sent anywhere.
"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .model import SECTIONS, Dossier

# What each section is called, in French and English, in architecture documents.
SAID: dict[str, tuple[str, ...]] = {
    "synthese": (
        "synthese",
        "resume",
        "parcours en clair",
        "objectif",
        "summary",
        "overview",
        "contexte",
    ),
    "metier": ("metier", "business", "processus", "acteurs", "parcours"),
    "application": ("application", "applicati", "logiciel", "composant", "sequence", "si "),
    "technologie": (
        "technolog",
        "infrastructure",
        "technique",
        "hebergement",
        "deploiement",
        "reseau",
    ),
    "flux": ("flux", "echange", "interface", "integration", "api", "message"),
    "dependances": ("dependance", "dependencies", "adherence", "impact"),
    "points": (
        "points de controle",
        "a confirmer",
        "points d'attention",
        "questions",
        "risques",
        "manques",
    ),
}
# What a reference may hold that the dossier does not write as a section.
OTHERS: dict[str, tuple[str, ...]] = {
    "Règles de gestion": ("regles de gestion", "regle", "business rules"),
    "Contacts et responsabilités (RACI)": ("raci", "contacts", "responsabilit"),
    "Sources consultées": ("sources", "references", "bibliograph"),
}


def _plain(text: str) -> str:
    table = str.maketrans("éèêëàâäîïôöùûüçœ’", "eeeeaaaiioouuuco'")  # noqa: RUF001
    return " ".join(text.lower().translate(table).split())


@dataclass
class Reference:
    name: str
    headings: list[str]
    text: str


def reference(path: Path) -> Reference:
    """A reference document, read: its headings and its text."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as zipped:
            xml = zipped.read("word/document.xml").decode("utf-8", "replace")
        headings: list[str] = []
        texts: list[str] = []
        for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL):
            said = html.unescape(
                "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, re.DOTALL))
            )
            if not said.strip():
                continue
            texts.append(said)
            if re.search(r'<w:pStyle w:val="(Heading|Titre|Title)[^"]*"', paragraph):
                headings.append(said.strip())
        return Reference(path.name, headings, "\n".join(texts))
    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix in (".html", ".htm"):
        headings = [
            html.unescape(re.sub(r"<[^>]+>", "", h)).strip()
            for h in re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", raw, re.DOTALL | re.IGNORECASE)
        ]
        text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
        return Reference(path.name, [h for h in headings if h], text)
    headings = [m.group(2).strip() for m in re.finditer(r"^(#{1,6})\s+(.+)$", raw, re.MULTILINE)]
    if not headings:
        # Plain text: numbered lines, or lines in capitals, are its headings.
        headings = [
            line.strip()
            for line in raw.splitlines()
            if re.match(r"^\s*(\d+[.)]|[IVX]+[.)])\s+\S", line)
            or (line.strip().isupper() and len(line.strip()) > 3)
        ]
    return Reference(path.name, headings, raw)


@dataclass
class Row:
    key: str
    title: str
    ours: bool
    theirs: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.ours and self.theirs:
            return "couverte des deux côtés"
        if self.theirs:
            return "manquante chez LEKA"
        if self.ours:
            return "en plus chez LEKA"
        return "absente des deux"


@dataclass
class Comparison:
    reference: str
    rows: list[Row]
    others: list[tuple[str, list[str]]]
    unmatched: list[str]
    found: list[str]
    absent: list[str]

    @property
    def coverage(self) -> int:
        """The share of the reference's sections the dossier covers."""
        theirs = [r for r in self.rows if r.theirs]
        return round(100 * sum(1 for r in theirs if r.ours) / len(theirs)) if theirs else 100


def compare(dossier: Dossier, ref: Reference) -> Comparison:
    plain_headings = [(h, _plain(h)) for h in ref.headings]
    used: set[str] = set()
    rows: list[Row] = []
    for key, title in SECTIONS:
        section = dossier.section(key)
        ours = bool(
            (section and section.summary and "non documente" not in _plain(section.summary))
            or (key in ("metier", "application", "technologie") and dossier.of_layer(key))
            or (key == "points" and dossier.points)
        )
        theirs = [h for h, p in plain_headings if any(word in p for word in SAID[key])]
        used.update(theirs)
        rows.append(Row(key, title, ours, theirs))
    others = []
    for title, words in OTHERS.items():
        theirs = [h for h, p in plain_headings if any(word in p for word in words)]
        used.update(theirs)
        if theirs:
            others.append((title, theirs))
    text = _plain(ref.text)
    found: list[str] = []
    absent: list[str] = []
    for element in dossier.elements:
        (found if _plain(element.name) in text else absent).append(element.name)
    return Comparison(
        reference=ref.name,
        rows=rows,
        others=others,
        unmatched=[h for h, _ in plain_headings if h not in used],
        found=found,
        absent=absent,
    )


def markdown(comparison: Comparison, title: str) -> str:
    lines = [
        f"# Comparaison — {title}",
        "",
        f"Référence : {comparison.reference}. Sections de la référence couvertes : "
        f"{comparison.coverage} %.",
        "",
        "| Section | LEKA | Référence | Statut |",
        "|---|---|---|---|",
    ]
    for row in comparison.rows:
        lines.append(
            f"| {row.title} | {'oui' if row.ours else 'non'} | "
            f"{', '.join(row.theirs) or '—'} | {row.status} |"
        )
    if comparison.others:
        lines += ["", "## Dans la référence, hors des sections ArchiMate", ""]
        lines += [f"- {title} : {', '.join(h)}" for title, h in comparison.others]
    if comparison.unmatched:
        lines += ["", "## Titres de la référence sans équivalent", ""]
        lines += [f"- {h}" for h in comparison.unmatched]
    total = len(comparison.found) + len(comparison.absent)
    lines += [
        "",
        f"## Éléments de LEKA nommés aussi par la référence : {len(comparison.found)} sur {total}",
        "",
    ]
    lines += [f"- {name}" for name in comparison.found] or ["Aucun."]
    if comparison.absent:
        lines += ["", "## Éléments de LEKA absents de la référence", ""]
        lines += [f"- {name}" for name in comparison.absent]
    return "\n".join(lines) + "\n"


__all__ = ["Comparison", "Reference", "Row", "compare", "markdown", "reference"]

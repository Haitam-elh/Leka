"""The dossier written in a folder — what a terminal or an MCP client gets:
the same four files LEKA delivers.

    dossier-architecture.md     Markdown, each page cited a link
    dossier-architecture.pdf    PDF (reportlab), the same sections
    dossier-architecture.docx   Word
    dossier-architecture.json   the dossier itself, to compare or render again
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Dossier
from .render import RenderError, docx, markdown, pdf

NAME = "dossier-architecture"


def write_dossier(dossier: Dossier, folder: Path) -> list[Path]:
    """Its files in `folder`, made when it is not there — the PDF left out,
    said so, where reportlab is not installed."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    md = folder / f"{NAME}.md"
    md.write_text(markdown(dossier), encoding="utf-8")
    written.append(md)
    word = folder / f"{NAME}.docx"
    word.write_bytes(docx(dossier))
    written.append(word)
    data = folder / f"{NAME}.json"
    data.write_text(json.dumps(dossier.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(data)
    try:
        drawn = pdf(dossier)
    except RenderError as error:
        (folder / "PDF-NON-GENERE.txt").write_text(f"{error}\n", encoding="utf-8")
    else:
        out = folder / f"{NAME}.pdf"
        out.write_bytes(drawn)
        written.append(out)
    return written


def read_dossier(path: Path) -> Dossier:
    """A dossier's JSON, as written here — or a folder holding it."""
    if path.is_dir():
        path = path / f"{NAME}.json"
    return Dossier.from_json(json.loads(path.read_text(encoding="utf-8")))


__all__ = ["NAME", "read_dossier", "write_dossier"]

"""The knowledge files an architect is given (2026-10-25): a directory of
contacts in Excel, a governance export, notes — read with the standard
library only, from one folder (--connaissances, ARCHITECT_KNOWLEDGE_DIR).

    files()      the files of the folder it may read
    sheets()     an Excel workbook, sheet by sheet, row by row
    rows_of()    any of them as rows: a workbook's, a CSV's, a text's lines
    relevant()   the rows naming what the pages name — the bricks of a
                 journey, its contacts — the headers kept

Nothing outside that folder is ever read: a path that leaves it is refused.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from xml.etree import ElementTree

READ = (".xlsx", ".xlsm", ".csv", ".txt", ".md")
_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_COLUMN = re.compile(r"([A-Z]+)")


class KnowledgeError(Exception):
    """A knowledge file that cannot be read, or one outside its folder."""


def files(folder: Path) -> list[Path]:
    """The files of `folder` it reads, by name."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in READ)


def inside(folder: Path, name: str) -> Path:
    """`name` within `folder` — never a path that leaves it."""
    top = folder.resolve()
    found = (top / name).resolve()
    if found != top and top not in found.parents:
        raise KnowledgeError(f"{name} n'est pas dans le dossier des Connaissances.")
    if not found.is_file():
        raise KnowledgeError(f"Aucun fichier {name} dans le dossier des Connaissances.")
    return found


def _index(cell: str) -> int:
    letters = _COLUMN.match(cell)
    n = 0
    for letter in letters.group(1) if letters else "A":
        n = n * 26 + ord(letter) - 64
    return n - 1


def _xml(data: bytes) -> ElementTree.Element:
    """A part of a workbook, parsed — refused when it declares a DOCTYPE: no
    workbook has one, and entities are how XML is turned against its reader."""
    if b"<!DOCTYPE" in data[:2048].upper():
        raise KnowledgeError("Classeur refusé : il déclare un DOCTYPE.")
    return ElementTree.fromstring(data)  # noqa: S314 - no DOCTYPE, so no entity to expand


def _text(node: ElementTree.Element | None) -> str:
    return "".join(node.itertext()) if node is not None else ""


def sheets(path: Path) -> dict[str, list[list[str]]]:
    """An Excel workbook, its sheets in order, each its rows of cells."""
    try:
        book = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise KnowledgeError(f"{path.name} n'est pas un classeur Excel lisible.") from error
    with book:
        names = set(book.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = _xml(book.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.findall("m:si", _NS)]
        targets: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rels = _xml(book.read("xl/_rels/workbook.xml.rels"))
            for rel in rels.findall("p:Relationship", _NS):
                link = rel.get("Target", "").lstrip("/")
                targets[rel.get("Id", "")] = link if link.startswith("xl/") else f"xl/{link}"
        workbook = _xml(book.read("xl/workbook.xml"))
        found: dict[str, list[list[str]]] = {}
        for sheet in workbook.findall("m:sheets/m:sheet", _NS):
            target = targets.get(sheet.get(f"{{{_NS['r']}}}id", ""), "")
            if not target or target not in names:
                continue
            rows: list[list[str]] = []
            for row in _xml(book.read(target)).iter(f"{{{_NS['m']}}}row"):
                cells: list[str] = []
                for cell in row.findall("m:c", _NS):
                    kind = cell.get("t")
                    if kind == "s":
                        value = _text(cell.find("m:v", _NS))
                        said = (
                            shared[int(value)]
                            if value.isdigit() and int(value) < len(shared)
                            else ""
                        )
                    elif kind == "inlineStr":
                        said = _text(cell.find("m:is", _NS))
                    else:
                        said = _text(cell.find("m:v", _NS))
                    at = _index(cell.get("r", "")) if cell.get("r") else len(cells)
                    cells.extend([""] * (at - len(cells)))
                    cells.append(said.strip())
                rows.append(cells)
            found[sheet.get("name", target)] = rows
        return found


def rows_of(path: Path) -> dict[str, list[list[str]]]:
    """Any knowledge file as rows, by sheet: a workbook's sheets, a CSV, a
    text's lines."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return sheets(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix == ".csv":
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else None
        reader = (
            csv.reader(io.StringIO(text), dialect) if dialect else csv.reader(io.StringIO(text))
        )
        return {path.stem: [list(row) for row in reader]}
    return {path.stem: [[line] for line in text.splitlines()]}


def said(name: str, rows: Sequence[Sequence[str]], *, first: int = 0, most: int = 200) -> str:
    """Rows as a table one reads: its sheet, each row its number."""
    shown = [f"## {name}"]
    for n, row in enumerate(rows[first : first + most], first + 1):
        if any(cell for cell in row):
            shown.append(f"{n} | " + " | ".join(cell.replace("\n", " ") for cell in row))
    if len(rows) > first + most:
        shown.append(
            f"… {len(rows) - first - most} lignes de plus (première ligne : {first + most + 1})."
        )
    return "\n".join(shown)


def relevant(
    tables: Iterable[tuple[str, str, list[list[str]]]], corpus: str, *, most: int = 400
) -> str:
    """The rows naming what `corpus` names — the cells of four letters or
    more found in it, case aside —, each sheet's first rows kept (their
    headers); at most `most` rows in all."""
    words = corpus.lower()
    kept: list[str] = []
    left = most
    for file, sheet, rows in tables:
        if left <= 0:
            break
        found = [
            (n, row)
            for n, row in enumerate(rows, 1)
            if n <= 2
            or any(
                len(cell) >= 4 and not cell.replace(".", "").isdigit() and cell.lower() in words
                for cell in row
            )
        ]
        if len(found) <= 2:
            continue
        kept.append(f"## {file} — onglet « {sheet} »")
        for n, row in found[:left]:
            kept.append(f"{n} | " + " | ".join(cell.replace("\n", " ") for cell in row))
        left -= len(found)
    return "\n".join(kept)


def tables(folder: Path) -> list[tuple[str, str, list[list[str]]]]:
    """Every file of the folder as (file, sheet, rows) — the unreadable left out."""
    found: list[tuple[str, str, list[list[str]]]] = []
    for path in files(folder):
        try:
            for sheet, rows in rows_of(path).items():
                found.append((path.name, sheet, rows))
        except (KnowledgeError, OSError, csv.Error, ElementTree.ParseError):
            continue
    return found


__all__ = [
    "READ",
    "KnowledgeError",
    "files",
    "inside",
    "relevant",
    "rows_of",
    "said",
    "sheets",
    "tables",
]

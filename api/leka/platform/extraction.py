"""What a file says, as text a model reads — one joined to an intention first
(2026-10-28, Haitam: « que le LLM et LEKA lisent bien le fichier, n'importe
lequel »).

    text, CSV, Markdown, JSON   as written (UTF-8)
    PDF                         its text, page by page (pypdf); a page that
                                holds none — scanned — read by OCR
    PNG, JPEG                   read by OCR
    Word, Excel, PowerPoint     their text, from the XML they are made of

OCR is Tesseract's, on the machine, in French and English: nothing leaves
LEKA, nothing is paid. Where it is not installed, the file is said
unreadable as an image, never read as empty. Every model is given the same
text — whichever answers.

Nothing here runs what a file holds: a PDF's scripts, an Office file's
macros are never read, only their text.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import structlog

logger = structlog.get_logger(__name__)

# What a model is given of one file, at most, and of all an intention's.
MOST_CHARS = 40_000
MOST_ALL = 100_000
# A PDF page with less text than this is taken as scanned: read by OCR.
SCANNED_BELOW = 25
# Pages of a scanned PDF read by OCR, at most: each takes seconds.
MOST_OCR_PAGES = 20
# Seconds one OCR may take.
OCR_SECONDS = 60

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TEXTS = frozenset({"text/plain", "text/csv", "text/markdown", "application/json"})
IMAGES = frozenset({"image/png", "image/jpeg"})


@dataclass(frozen=True)
class Extracted:
    """A file's text, how it was read, and whether it was cut to MOST_CHARS
    — `how`: text, pdf, ocr, pdf+ocr, office; `unreadable` with `why`."""

    text: str
    how: str
    cut: bool = False
    why: str | None = None


def ocr_ready() -> bool:
    """Whether Tesseract is on this machine."""
    return shutil.which("tesseract") is not None


def _ocr(image: bytes) -> str:
    """An image's text, by Tesseract, French and English."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "image"
        path.write_bytes(image)
        done = subprocess.run(  # noqa: S603 — a fixed binary, no shell, our own file
            ["tesseract", str(path), "stdout", "-l", "fra+eng"],  # noqa: S607
            capture_output=True,
            timeout=OCR_SECONDS,
            check=False,
        )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace")[:300])
    return done.stdout.decode("utf-8", "replace")


def _pages_as_images(data: bytes, pages: list[int]) -> list[bytes]:
    """Scanned pages of a PDF drawn as images (poppler's pdftoppm), for OCR."""
    if shutil.which("pdftoppm") is None:
        return []
    drawn: list[bytes] = []
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "file.pdf"
        source.write_bytes(data)
        for number in pages:
            target = Path(folder) / f"page{number}"
            subprocess.run(  # noqa: S603 — a fixed binary, no shell, our own file
                [  # noqa: S607
                    "pdftoppm",
                    "-r",
                    "200",
                    "-png",
                    "-singlefile",
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    str(source),
                    str(target),
                ],
                capture_output=True,
                timeout=OCR_SECONDS,
                check=False,
            )
            image = target.with_suffix(".png")
            if image.exists():
                drawn.append(image.read_bytes())
    return drawn


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return Extracted("", "unreadable", why="encrypted")
    texts: list[str] = []
    scanned: list[int] = []
    for number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        texts.append(text)
        if len(text.strip()) < SCANNED_BELOW:
            scanned.append(number)
    how = "pdf"
    if scanned and ocr_ready():
        for number, image in zip(
            scanned[:MOST_OCR_PAGES], _pages_as_images(data, scanned[:MOST_OCR_PAGES]), strict=False
        ):
            try:
                texts[number - 1] = _ocr(image)
                how = "pdf+ocr"
            except Exception:
                logger.warning("attachment_page_not_read", page=number, exc_info=True)
    said = "\n\n".join(f"[Page {n}]\n{t.strip()}" for n, t in enumerate(texts, 1) if t.strip())
    if not said:
        why = "scanned_no_ocr" if scanned and not ocr_ready() else "no_text"
        return Extracted("", "unreadable", why=why)
    return Extracted(said, how)


_TAG = re.compile(r"\{[^}]*\}")


def _xml_texts(
    xml: bytes, tag: str, *, block: str | None = None, keep_empty: bool = False
) -> list[str]:
    """The text of every `tag` element, a `block` element ending a line —
    the empty ones kept when their place counts (a sheet's shared strings)."""
    lines: list[str] = []
    current: list[str] = []
    # The standard parser: it resolves no external entity, and Python's
    # expat refuses the expanding ones; nothing of the file is run.
    for element in ElementTree.iterparse(io.BytesIO(xml), events=("end",)):  # noqa: S314
        _event, node = element
        name = _TAG.sub("", node.tag)
        if name == tag and node.text:
            current.append(node.text)
        elif block is not None and name == block:
            lines.append("".join(current))
            current = []
    if current:
        lines.append("".join(current))
    return lines if keep_empty else [line for line in lines if line.strip()]


# What one part of an Office file may unpack to, at most: a file of a few
# megabytes that unpacks to gigabytes is not read.
MOST_PART = 30_000_000


def _part(archive: zipfile.ZipFile, name: str) -> bytes:
    if archive.getinfo(name).file_size > MOST_PART:
        raise ValueError(f"{name} unpacks too large")
    return archive.read(name)


def _office(data: bytes, content_type: str) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if content_type == DOCX:
            texts = _xml_texts(_part(archive, "word/document.xml"), "t", block="p")
        elif content_type == PPTX:
            slides = sorted(
                (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.findall(r"\d+", n)[-1]),
            )
            texts = []
            for number, slide in enumerate(slides, 1):
                lines = _xml_texts(_part(archive, slide), "t", block="p")
                if lines:
                    texts.append(f"[Diapositive {number}]\n" + "\n".join(lines))
        else:
            shared = (
                _xml_texts(_part(archive, "xl/sharedStrings.xml"), "t", block="si", keep_empty=True)
                if "xl/sharedStrings.xml" in names
                else []
            )
            texts = []
            sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
            for sheet in sheets:
                rows = _sheet_rows(_part(archive, sheet), shared)
                if rows:
                    texts.append(f"[{Path(sheet).stem}]\n" + "\n".join(rows))
    said = "\n".join(texts)
    return Extracted(said, "office") if said.strip() else Extracted("", "unreadable", why="no_text")


def _sheet_rows(xml: bytes, shared: list[str]) -> list[str]:
    """A sheet's rows, cells joined by « | », shared strings resolved."""
    rows: list[str] = []
    root = ElementTree.fromstring(xml)  # noqa: S314 — a file's own sheet, parsed, never run
    for row in root.iter():
        if _TAG.sub("", row.tag) != "row":
            continue
        cells: list[str] = []
        for cell in row:
            if _TAG.sub("", cell.tag) != "c":
                continue
            kind = cell.get("t")
            value = next((c.text or "" for c in cell if _TAG.sub("", c.tag) == "v"), "")
            inline = "".join(t.text or "" for t in cell.iter() if _TAG.sub("", t.tag) == "t")
            if kind == "s" and value.isdigit() and int(value) < len(shared):
                cells.append(shared[int(value)])
            else:
                cells.append(inline or value)
        if any(c.strip() for c in cells):
            rows.append(" | ".join(cells))
    return rows


def text_of(content_type: str, data: bytes) -> Extracted:
    """What a file says, as text a model reads — cut to MOST_CHARS — or why
    it could not be read. Never raises: a file unreadable is said so."""
    try:
        if content_type in TEXTS:
            said = data.decode("utf-8", "replace")
            if content_type == "application/json":
                with contextlib.suppress(ValueError):
                    said = json.dumps(json.loads(said), ensure_ascii=False, indent=1)
            found = Extracted(said, "text")
        elif content_type == "application/pdf":
            found = _pdf(data)
        elif content_type in IMAGES:
            if not ocr_ready():
                return Extracted("", "unreadable", why="no_ocr")
            said = _ocr(data)
            found = (
                Extracted(said, "ocr")
                if said.strip()
                else Extracted("", "unreadable", why="no_text")
            )
        elif content_type in (DOCX, XLSX, PPTX):
            found = _office(data, content_type)
        else:
            return Extracted("", "unreadable", why="type")
    except Exception:
        logger.warning("attachment_not_read", content_type=content_type, exc_info=True)
        return Extracted("", "unreadable", why="error")
    if found.how == "unreadable":
        return found
    text = re.sub(r"\n{3,}", "\n\n", found.text).strip()
    if len(text) > MOST_CHARS:
        return Extracted(text[:MOST_CHARS], found.how, cut=True)
    return Extracted(text, found.how)


__all__ = [
    "DOCX",
    "IMAGES",
    "MOST_ALL",
    "MOST_CHARS",
    "PPTX",
    "TEXTS",
    "XLSX",
    "Extracted",
    "ocr_ready",
    "text_of",
]

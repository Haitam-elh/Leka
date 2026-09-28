"""The text of an office file — Word, Excel, PowerPoint — for the connectors
that read a drive (Google Workspace, Microsoft 365).

A record is JSON, and a .docx is a zip of XML: storing the bytes would put
megabytes of base64 in a payload nobody can read. Google converts its own
formats to text itself (the export); for Office Open XML files nobody does,
so this does — the least it can: the words, in reading order, paragraph by
paragraph, slide by slide, sheet by sheet. Layout, styles and pictures are
left behind.

WHAT IT WILL NOT DO. It never parses XML: the text is taken from the
elements that hold it (<w:t>, <a:t>, <t>) by a regular expression, so no
entity is ever expanded and no external reference ever fetched. It never
unzips more than MAX_UNZIPPED bytes, whatever the archive claims: a zip
bomb ends as a truncated text, not as a full disk. A file that is not what
its name says is None — no text — never an error.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass

MAX_UNZIPPED = 50 * 1024 * 1024  # bytes read out of one archive, all parts together
MAX_TEXT = 1024 * 1024  # characters kept of one file's text

WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
POWERPOINT = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PLAIN = frozenset({"text/plain", "text/markdown", "text/csv"})
OFFICE = frozenset({WORD, EXCEL, POWERPOINT})
# What a file's name says it is, when its type is not given.
BY_EXTENSION = {
    ".docx": WORD,
    ".xlsx": EXCEL,
    ".pptx": POWERPOINT,
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}

# The parts that hold the text, in reading order, and the element in each.
_WORD_PARTS = re.compile(r"^word/(document|footnotes|endnotes)\.xml$")
_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SHEET = re.compile(r"^xl/worksheets/sheet(\d+)\.xml$")
_PARAGRAPH = re.compile(r"<(?:w|a):p[ >].*?</(?:w|a):p>", re.DOTALL)
_RUN_TEXT = re.compile(r"<(?:w|a):t(?: [^>]*)?>([^<]*)</(?:w|a):t>")
_SHARED = re.compile(r"<si>(.*?)</si>", re.DOTALL)
_CELL = re.compile(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", re.DOTALL)
_TEXT = re.compile(r"<t(?: [^>]*)?>([^<]*)</t>")
_VALUE = re.compile(r"<v>([^<]*)</v>")


@dataclass(frozen=True)
class Text:
    text: str
    truncated: bool


def kind_of(mime_type: str | None, name: str | None) -> str | None:
    """What a file is, for reading its text — its type, else its name's
    extension; None when its text is not read."""
    if mime_type in OFFICE or mime_type in PLAIN:
        return mime_type
    lowered = (name or "").lower()
    for extension, kind in BY_EXTENSION.items():
        if lowered.endswith(extension):
            return kind
    return None


def text_of(data: bytes, kind: str) -> Text | None:
    """The text of a file of this kind, or None when it is not one."""
    if kind in PLAIN:
        return _cut(data.decode("utf-8", errors="replace"))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    with archive:
        reader = _Reader(archive)
        if kind == WORD:
            parts = sorted(n for n in archive.namelist() if _WORD_PARTS.match(n))
            text = "\n".join(_paragraphs(reader.read(n)) for n in parts)
        elif kind == POWERPOINT:
            slides = _numbered(archive.namelist(), _SLIDE)
            text = "\n\n".join(_paragraphs(reader.read(n)) for n in slides)
        elif kind == EXCEL:
            shared = [
                _joined(_TEXT, s) for s in _SHARED.findall(reader.read("xl/sharedStrings.xml"))
            ]
            sheets = _numbered(archive.namelist(), _SHEET)
            text = "\n\n".join(_cells(reader.read(n), shared) for n in sheets)
        else:
            return None
    cut = _cut(text.strip())
    return Text(cut.text, cut.truncated or reader.truncated)


class _Reader:
    """Parts of an archive, as text, never more than MAX_UNZIPPED in all."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive
        self._left = MAX_UNZIPPED
        self.truncated = False

    def read(self, name: str) -> str:
        if self._left <= 0:
            self.truncated = True
            return ""
        try:
            with self._archive.open(name) as part:
                data = part.read(self._left + 1)
        except KeyError:
            return ""
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
            self.truncated = True
            return ""
        if len(data) > self._left:
            data, self.truncated = data[: self._left], True
        self._left -= len(data)
        return data.decode("utf-8", errors="replace")


def _numbered(names: list[str], pattern: re.Pattern[str]) -> list[str]:
    """Slides, sheets: in their number's order, not the archive's."""
    found = [(int(m.group(1)), n) for n in names if (m := pattern.match(n))]
    return [name for _, name in sorted(found)]


def _paragraphs(xml: str) -> str:
    return "\n".join(
        line for line in (_joined(_RUN_TEXT, p) for p in _PARAGRAPH.findall(xml)) if line
    )


def _cells(xml: str, shared: list[str]) -> str:
    """A sheet's cells, row after row, a tab between cells."""
    rows: list[str] = []
    for row in re.findall(r"<row[ >].*?</row>", xml, re.DOTALL):
        values: list[str] = []
        for attributes, body in _CELL.findall(row):
            body = body or ""
            if 't="s"' in attributes:
                index = _VALUE.search(body)
                number = int(index.group(1)) if index and index.group(1).isdigit() else -1
                values.append(shared[number] if 0 <= number < len(shared) else "")
            elif 't="inlineStr"' in attributes:
                values.append(_joined(_TEXT, body))
            else:
                value = _VALUE.search(body)
                values.append(html.unescape(value.group(1)) if value else "")
        line = "\t".join(values).rstrip("\t")
        if line:
            rows.append(line)
    return "\n".join(rows)


def _joined(pattern: re.Pattern[str], xml: str) -> str:
    return html.unescape("".join(pattern.findall(xml)))


def _cut(text: str) -> Text:
    return Text(text[:MAX_TEXT], len(text) > MAX_TEXT)

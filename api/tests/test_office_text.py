"""The text of an office file, as the drive connectors read it (LEKA-346).

The files are built here, as Word, PowerPoint and Excel write them — a zip
of XML parts — small enough to read, shaped enough to be real. What
matters: the words in reading order, nothing else of the XML, and no way
for a file to make LEKA unzip more than it allows or expand an entity.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from leka.connectors import office
from leka.connectors.office import EXCEL, POWERPOINT, WORD, kind_of, text_of

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def archive(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as built:
        for name, text in parts.items():
            built.writestr(name, text)
    return buffer.getvalue()


def docx(*paragraphs: str) -> bytes:
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr><w:r><w:t xml:space="preserve">{p}'
        "</w:t></w:r></w:p>"
        for p in paragraphs
    )
    return archive({"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})


def test_a_word_document_is_its_paragraphs_in_order() -> None:
    found = text_of(docx("Architecture", "The API calls the worker &amp; the queue."), WORD)

    assert found == office.Text("Architecture\nThe API calls the worker & the queue.", False)


def test_a_paragraph_split_in_runs_is_read_whole() -> None:
    runs = (
        "<w:p><w:r><w:t>Deploy </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>daily</w:t></w:r></w:p>"
    )
    data = archive({"word/document.xml": f"<w:document {W}><w:body>{runs}</w:body></w:document>"})

    assert text_of(data, WORD) == office.Text("Deploy daily", False)


def test_slides_are_read_in_their_order_not_the_archive_s() -> None:
    def slide(text: str) -> str:
        return f"<p:sld {A}><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"

    data = archive(
        {
            "ppt/slides/slide10.xml": slide("Ten"),
            "ppt/slides/slide2.xml": slide("Two"),
            "ppt/slides/slide1.xml": slide("One"),
            "ppt/notesSlides/notesSlide1.xml": slide("Not a slide"),
        }
    )

    assert text_of(data, POWERPOINT) == office.Text("One\n\nTwo\n\nTen", False)


def test_a_sheet_is_its_rows_with_shared_inline_and_plain_values() -> None:
    shared = "<sst><si><t>Service</t></si><si><r><t>Own</t></r><r><t>er</t></r></si></sst>"
    sheet = (
        "<worksheet><sheetData>"
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>api</t></is></c><c r="B2"><v>42</v></c></row>'
        '<row r="3"><c r="A3" t="s"><v>99</v></c></row>'
        "</sheetData></worksheet>"
    )
    data = archive({"xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})

    assert text_of(data, EXCEL) == office.Text("Service\tOwner\napi\t42", False)


def test_plain_text_is_itself() -> None:
    assert text_of("café\n".encode(), "text/plain") == office.Text("café\n", False)


def test_a_file_that_is_not_what_it_says_has_no_text() -> None:
    assert text_of(b"%PDF-1.7 not a zip", WORD) is None


def test_an_entity_is_never_expanded() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;">]>'
        f"<w:document {W}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>"
    )

    found = text_of(archive({"word/document.xml": bomb}), WORD)

    assert found is not None and "aaaa" not in found.text


def test_an_archive_that_unzips_too_far_is_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office, "MAX_UNZIPPED", 1000)
    words = " ".join(["word"] * 2000)  # compresses to little, unzips to 10 kB

    found = text_of(docx(words), WORD)

    assert found is not None and found.truncated
    assert len(found.text) < 1000


def test_a_long_text_is_cut_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office, "MAX_TEXT", 10)

    found = text_of(b"a" * 50, "text/plain")

    assert found == office.Text("a" * 10, True)


@pytest.mark.parametrize(
    ("mime", "name", "kind"),
    [
        (WORD, "whatever", WORD),
        (None, "Plan.DOCX", WORD),
        ("application/octet-stream", "deck.pptx", POWERPOINT),
        (None, "notes.md", "text/markdown"),
        ("application/pdf", "spec.pdf", None),
        (None, "photo.png", None),
    ],
)
def test_a_file_s_kind_is_its_type_else_its_name(
    mime: str | None, name: str, kind: str | None
) -> None:
    assert kind_of(mime, name) == kind

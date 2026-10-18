"""Markdown, as Jira and Confluence write it — for what LEKA publishes there.

    jira_wiki(md)        Jira's wiki markup (an issue's description, API v2)
    confluence_xhtml(md) Confluence's storage format (a page's body)

What an agent writes is markdown: headings, paragraphs, lists (nested by
indentation), code blocks, tables, quotes, rules, and inline bold, italic,
code and links. Both outputs are built here, line by line — no dependency,
nothing interpreted: text is escaped for Confluence, links are kept only
when they are http(s), and code stays code.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import cast

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
FENCE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
TABLE_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
QUOTE = re.compile(r"^\s*>\s?(.*)$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])|(?<![_\w])_([^_\n]+)_(?![_\w])")


def _depth(indent: str) -> int:
    return len(indent.replace("\t", "  ")) // 2 + 1


def _cells(line: str) -> list[str]:
    found = TABLE_ROW.match(line)
    inner = found.group(1) if found else line
    return [cell.strip() for cell in inner.split("|")]


def _blocks(md: str) -> list[tuple[str, object]]:
    """The markdown, as blocks: ("heading", (level, text)), ("para", text),
    ("list", [(ordered, depth, text)]), ("code", (language, text)),
    ("table", [cells…]), ("quote", text), ("rule", None)."""
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[tuple[str, object]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = FENCE.match(line)
        if fence:
            body: list[str] = []
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(("code", (fence.group(1), "\n".join(body))))
            i += 1
            continue
        heading = HEADING.match(line)
        if heading:
            blocks.append(("heading", (len(heading.group(1)), heading.group(2).strip())))
            i += 1
            continue
        if RULE.match(line):
            blocks.append(("rule", None))
            i += 1
            continue
        if TABLE_ROW.match(line) and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
            rows = [_cells(line)]
            i += 2
            while i < len(lines) and TABLE_ROW.match(lines[i]):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.append(("table", rows))
            continue
        if BULLET.match(line) or NUMBERED.match(line):
            items: list[tuple[bool, int, str]] = []
            while i < len(lines) and (BULLET.match(lines[i]) or NUMBERED.match(lines[i])):
                bullet = BULLET.match(lines[i])
                found = bullet or NUMBERED.match(lines[i])
                assert found is not None
                items.append((bullet is None, _depth(found.group(1)), found.group(2).strip()))
                i += 1
            blocks.append(("list", items))
            continue
        if QUOTE.match(line):
            said: list[str] = []
            while i < len(lines) and (quoted := QUOTE.match(lines[i])):
                said.append(quoted.group(1))
                i += 1
            blocks.append(("quote", " ".join(s.strip() for s in said if s.strip())))
            continue
        paragraph: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not any(p.match(lines[i]) for p in (FENCE, HEADING, BULLET, NUMBERED, QUOTE, RULE))
            and not (
                TABLE_ROW.match(lines[i]) and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1])
            )
        ):
            paragraph.append(lines[i].strip())
            i += 1
        blocks.append(("para", " ".join(paragraph)))
    return blocks


# ── Jira ─────────────────────────────────────────────────────────────────────


def _jira_inline(text: str) -> str:
    codes: list[str] = []

    def keep(found: re.Match[str]) -> str:
        codes.append(found.group(1))
        return f"\x00{len(codes) - 1}\x00"

    said = CODE.sub(keep, text)
    said = LINK.sub(
        lambda m: (
            f"[{m.group(1)}|{m.group(2)}]"
            if m.group(2).startswith(("http://", "https://"))
            else m.group(1)
        ),
        said,
    )
    said = BOLD.sub(lambda m: f"\x01{m.group(1) or m.group(2)}\x01", said)
    said = ITALIC.sub(lambda m: f"_{m.group(1) or m.group(2)}_", said)
    said = said.replace("\x01", "*")
    return re.sub(r"\x00(\d+)\x00", lambda m: "{{" + codes[int(m.group(1))] + "}}", said)


def jira_wiki(md: str) -> str:
    """Markdown as Jira's wiki markup."""
    out: list[str] = []
    for kind, value in _blocks(md):
        if kind == "heading":
            level, text = cast(tuple[int, str], value)
            out.append(f"h{level}. {_jira_inline(text)}")
        elif kind == "para":
            out.append(_jira_inline(str(value)))
        elif kind == "list":
            out.append(
                "\n".join(
                    ("#" if ordered else "*") * depth + " " + _jira_inline(text)
                    for ordered, depth, text in cast(list[tuple[bool, int, str]], value)
                )
            )
        elif kind == "code":
            language, text = cast(tuple[str, str], value)
            out.append(
                f"{{code:{language}}}\n{text}\n{{code}}"
                if language
                else f"{{code}}\n{text}\n{{code}}"
            )
        elif kind == "table":
            rows = cast(list[list[str]], value)
            lines = ["||" + "||".join(_jira_inline(c) for c in rows[0]) + "||"]
            lines += ["|" + "|".join(_jira_inline(c) or " " for c in row) + "|" for row in rows[1:]]
            out.append("\n".join(lines))
        elif kind == "quote":
            out.append(f"bq. {_jira_inline(str(value))}")
        elif kind == "rule":
            out.append("----")
    return "\n\n".join(out)


# ── Confluence ───────────────────────────────────────────────────────────────


def _xhtml_inline(text: str) -> str:
    codes: list[str] = []
    links: list[str] = []

    def keep(found: re.Match[str]) -> str:
        codes.append(found.group(1))
        return f"\x00{len(codes) - 1}\x00"

    def link(found: re.Match[str]) -> str:
        label, address = found.group(1), found.group(2)
        if not address.startswith(("http://", "https://")):
            return label
        links.append(f'<a href="{html.escape(address, quote=True)}">{html.escape(label)}</a>')
        return f"\x02{len(links) - 1}\x02"

    said = LINK.sub(link, CODE.sub(keep, text))
    said = html.escape(said, quote=False)
    said = BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", said)
    said = ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", said)
    said = re.sub(r"\x02(\d+)\x02", lambda m: links[int(m.group(1))], said)
    return re.sub(
        r"\x00(\d+)\x00", lambda m: f"<code>{html.escape(codes[int(m.group(1))])}</code>", said
    )


def _xhtml_list(items: list[tuple[bool, int, str]], inline: Callable[[str], str]) -> str:
    out: list[str] = []
    stack: list[str] = []
    for ordered, depth, text in items:
        tag = "ol" if ordered else "ul"
        while len(stack) > depth:
            out.append(f"</li></{stack.pop()}>")
        if len(stack) == depth:
            out.append("</li>")
        while len(stack) < depth:
            out.append(f"<{tag}>")
            stack.append(tag)
        out.append(f"<li>{inline(text)}")
    while stack:
        out.append(f"</li></{stack.pop()}>")
    return "".join(out)


def confluence_xhtml(md: str) -> str:
    """Markdown as Confluence's storage format."""
    out: list[str] = []
    for kind, value in _blocks(md):
        if kind == "heading":
            level, text = cast(tuple[int, str], value)
            out.append(f"<h{level}>{_xhtml_inline(text)}</h{level}>")
        elif kind == "para":
            out.append(f"<p>{_xhtml_inline(str(value))}</p>")
        elif kind == "list":
            out.append(_xhtml_list(cast(list[tuple[bool, int, str]], value), _xhtml_inline))
        elif kind == "code":
            language, text = cast(tuple[str, str], value)
            safe = str(text).replace("]]>", "]]]]><![CDATA[>")
            parameter = (
                f'<ac:parameter ac:name="language">{html.escape(language)}</ac:parameter>'
                if language
                else ""
            )
            out.append(
                f'<ac:structured-macro ac:name="code">{parameter}'
                f"<ac:plain-text-body><![CDATA[{safe}]]></ac:plain-text-body>"
                "</ac:structured-macro>"
            )
        elif kind == "table":
            rows = cast(list[list[str]], value)
            head = "".join(f"<th>{_xhtml_inline(c)}</th>" for c in rows[0])
            body = "".join(
                "<tr>" + "".join(f"<td>{_xhtml_inline(c)}</td>" for c in row) + "</tr>"
                for row in rows[1:]
            )
            out.append(f"<table><tbody><tr>{head}</tr>{body}</tbody></table>")
        elif kind == "quote":
            out.append(f"<blockquote><p>{_xhtml_inline(str(value))}</p></blockquote>")
        elif kind == "rule":
            out.append("<hr />")
    return "".join(out)


__all__ = ["confluence_xhtml", "jira_wiki"]
